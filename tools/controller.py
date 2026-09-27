#!/usr/bin/env python3
"""Bounded original v1.42 controller execution with explicit MMIO models; offline only."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import struct
import sys

from control_flow import walk
from emulate_platform import APP_BASE, RETURN, SOURCE, engine, inputs
from firmware import digest, revision

BASE = 0x3fefa000
ROUTINES = {
    'restore_mapping': (0x20024850, 0x20024904),
    'wait_not_busy': (0x20024904, 0x2002497c),
    'wait_write_enable': (0x2002497c, 0x200249f4),
    'program': (0x20024a60, 0x20024bb8),
    'erase': (0x20024bb8, 0x20024cd0),
    'enter_command': (0x20024cd0, 0x20024d60),
    'read_masked_register': (0x20360b44, 0x20360b54),
}
RUNTIME_HELPERS = {0x200b9008, 0x200b9098}
SCENARIOS = ('immediate', 'delayed', 'transfer_stuck', 'busy_stuck', 'write_enable_stuck', 'status_extra_bits')
READ_OFFSETS = {0, 0xc, 0x10, 0x14, 0x1c, 0x38, 0x48, 0x58, 0x5c}
WRITE_OFFSETS = {0, 0xc, 0x10, 0x14, 0x1c, 0x20, 0x24, 0x28, 0x30, 0x40, 0x58, 0x5c}


class ControllerModel:
    """Scripted status responses, not a qualified controller/flash implementation."""
    def __init__(self, scenario):
        if scenario not in SCENARIOS:
            raise ValueError('Unknown controller scenario')
        self.scenario = scenario
        self.registers = {}
        self.events = []
        self.counts = Counter()
        self.event_hash = hashlib.sha256()
        self.total_events = 0
        self.transfer_reads = 0
        self.status_reads = 0
        self.write_enabled = False
        self.waiting_enable = False
        self.pending_data = None
        self.program_words = []
        self.erase_offsets = []
        self.program_position = 0

    def event(self, operation, **detail):
        event = dict(operation=operation, **detail)
        self.counts[operation] += 1
        self.total_events += 1
        self.event_hash.update(json.dumps(event, sort_keys=True).encode() + b'\n')
        if len(self.events) < 2048:
            self.events.append(event)

    def read(self, address, size):
        offset = address - BASE
        if size != 4 or offset not in READ_OFFSETS:
            raise ValueError(f'Unknown MMIO read {address:#x}/{size}')
        if offset == 0x48:
            self.transfer_reads += 1
            value = int(self.scenario != 'transfer_stuck' and
                        (self.scenario != 'delayed' or self.transfer_reads > 2))
        elif offset == 0x38:
            self.status_reads += 1
            if self.waiting_enable:
                enabled = self.write_enabled and self.scenario != 'write_enable_stuck'
                if self.scenario == 'delayed' and self.status_reads <= 2:
                    enabled = False
                value = 2 if enabled else 0
            else:
                busy = self.scenario == 'busy_stuck' or (self.scenario == 'delayed' and self.status_reads <= 2)
                value = int(busy)
            if self.scenario == 'status_extra_bits':
                value |= 0xfc
        else:
            value = self.registers.get(offset, 0)
        self.event('read', address=hex(address), value=value)
        return value

    def write(self, address, size, value):
        offset = address - BASE
        if size != 4 or offset not in WRITE_OFFSETS:
            raise ValueError(f'Unknown MMIO write {address:#x}/{size}')
        self.registers[offset] = value
        self.event('write', address=hex(address), value=value)
        if offset == 0x40:
            self.pending_data = value
        if offset != 0x20:
            return
        self.transfer_reads = 0
        command = (self.registers.get(0x24, 0) >> 16) & 0xff
        self.event('command', opcode=hex(command), control=hex(value))
        # These command interpretations are explicit stimulus-model assumptions.
        if command == 0x06:
            self.write_enabled = True
            self.waiting_enable = True
            self.status_reads = 0
        elif (command == 0x01 and value == 3) or command == 0xd8:
            self.write_enabled = False
            self.waiting_enable = False
            self.status_reads = 0
            if command == 0xd8:
                self.erase_offsets.append(self.registers.get(0x28, 0))
        elif command == 0x02:
            if value == 0x101:
                self.program_position = self.registers.get(0x28, 0)
            elif value in (0x103, 3):
                if self.pending_data is None:
                    raise ValueError('Program transfer without a data word')
                self.program_words.append((self.program_position, self.pending_data))
                self.program_position += 4
                self.pending_data = None
                if value == 3:
                    self.write_enabled = False
                    self.waiting_enable = False
                    self.status_reads = 0

    def summary(self):
        return dict(events=self.events, event_count=self.total_events,
                    events_truncated=self.total_events > len(self.events),
                    event_sha256=self.event_hash.hexdigest(), counts=dict(self.counts),
                    erase_offsets=[hex(x) for x in self.erase_offsets],
                    program_word_count=len(self.program_words),
                    program_words_sha256=digest(b''.join(struct.pack('<II', *word) for word in self.program_words)))


def run_controller(app, routine, *, scenario='immediate', destination=0x10000,
                   payload=b'ABCD' * 4, end=None, budget=100000, model_runtime=True):
    if routine not in ROUTINES or routine == 'read_masked_register':
        raise ValueError('Unsupported controller entry')
    if not 0 <= destination < 0x800000 or destination % 4:
        raise ValueError('Invalid modeled destination')
    if end is None:
        end = destination
    if routine == 'erase' and (destination % 0x10000 or end < destination or end >= 0x800000):
        raise ValueError('Invalid modeled erase bounds')
    if routine == 'program' and (not payload or len(payload) % 4 or destination + len(payload) > 0x800000):
        raise ValueError('Invalid modeled word-aligned payload')
    if budget <= 0 or budget > 2000000:
        raise ValueError('Invalid instruction budget')
    uc, u, a = engine()
    uc.mem_map(0x20000000, 0x600000)
    uc.mem_write(APP_BASE, app)
    uc.mem_map(BASE, 0x1000)
    span = (len(payload) + 4095) & ~4095
    uc.mem_map(SOURCE, span, u.UC_PROT_READ)
    source = SOURCE + span - len(payload)
    uc.mem_write(source, payload)
    model = ControllerModel(scenario)
    if routine == 'wait_write_enable':
        model.write_enabled = True
        model.waiting_enable = True
    stopped = {}
    visited = set()
    executed = Counter()
    modeled_helpers = set()
    instruction_count = 0

    def stop(outcome, **details):
        stopped.update(outcome=outcome, pc=hex(uc.reg_read(a.UC_ARM_REG_PC)), **details)
        uc.emu_stop()

    def code(machine, address, size, user):
        nonlocal instruction_count
        instruction_count += 1
        visited.add(address)
        if address in RUNTIME_HELPERS:
            if not model_runtime:
                stop('UNRESOLVED', reason='Runtime mapping/cache helper requires separate qualification', target=hex(address))
                return
            modeled_helpers.add(address)
            model.event('modeled_runtime_helper', address=hex(address))
            uc.reg_write(a.UC_ARM_REG_PC, uc.reg_read(a.UC_ARM_REG_LR))
            return
        for name, (lo, hi) in ROUTINES.items():
            if lo <= address < hi:
                executed[name] += 1
                return
        stop('UNRESOLVED', reason='Execution left reviewed routine bounds', target=hex(address))

    def memory(machine, access, address, size, value, user):
        try:
            if access == u.UC_MEM_READ:
                uc.mem_write(address, struct.pack('<I', model.read(address, size)))
            else:
                model.write(address, size, value)
        except ValueError as exc:
            stop('UNKNOWN_MMIO', reason=str(exc), address=hex(address), size=size)

    def invalid(machine, access, address, size, value, user):
        stopped.update(outcome='UNMAPPED_MEMORY', pc=hex(uc.reg_read(a.UC_ARM_REG_PC)),
                       address=hex(address), size=size, access=access)
        return False

    uc.hook_add(u.UC_HOOK_CODE, code)
    uc.hook_add(u.UC_HOOK_MEM_READ | u.UC_HOOK_MEM_WRITE, memory, begin=BASE, end=BASE + 0xfff)
    uc.hook_add(u.UC_HOOK_MEM_INVALID, invalid)
    for reg, value in [(a.UC_ARM_REG_R0, destination),
                       (a.UC_ARM_REG_R1, end if routine == 'erase' else source),
                       (a.UC_ARM_REG_R2, len(payload))]:
        uc.reg_write(reg, value)
    try:
        uc.emu_start(ROUTINES[routine][0], RETURN, timeout=30000000, count=budget)
    except u.UcError as exc:
        if not stopped:
            stopped.update(outcome='EMULATION_ERROR', reason=str(exc), pc=hex(uc.reg_read(a.UC_ARM_REG_PC)))
    if not stopped:
        pc = uc.reg_read(a.UC_ARM_REG_PC)
        stopped.update(outcome='RETURNED' if pc == RETURN else 'LIMIT', pc=hex(pc))
        if pc != RETURN:
            stopped['reason'] = 'Instruction or wall-time budget exhausted; no firmware timeout observed'
    return dict(routine=routine, scenario=scenario, **stopped,
                return_register=uc.reg_read(a.UC_ARM_REG_R0) if stopped['outcome'] == 'RETURNED' else None,
                instructions=instruction_count, executed_routines=dict(executed),
                visited_sha256=digest(b''.join(struct.pack('<I', x) for x in sorted(visited))),
                modeled_helpers=[hex(x) for x in sorted(modeled_helpers)],
                limits={'instructions': budget, 'wall_seconds': 30}, **model.summary())


def selector_references(main, app):
    """Exact aligned-word candidates plus literal/immediate refs in reviewed routines."""
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM
    from capstone.arm import ARM_OP_IMM
    words = []
    ranges = ((0x7f0000, 0x800000), (0x187f0000, 0x18800000))
    for label, data, base in [('loader', main[0x4000:0x4650], 0x20004000), ('application', app, APP_BASE)]:
        for offset in range(0, len(data) - 3, 4):
            value = struct.unpack_from('<I', data, offset)[0]
            if any(lo <= value < hi for lo, hi in ranges):
                words.append(dict(source=label, address=hex(base + offset), value=hex(value), kind='aligned-word candidate'))
    refs = []
    cs = Cs(CS_ARCH_ARM, CS_MODE_ARM)
    cs.detail = True
    for lo, hi in list(ROUTINES.values()) + [(0x20024d60, 0x20024db8)]:
        for ins in cs.disasm(app[lo - APP_BASE:hi - APP_BASE], lo):
            for operand in ins.operands:
                if operand.type == ARM_OP_IMM and any(a <= operand.imm < b for a, b in ranges):
                    refs.append(dict(address=hex(ins.address), value=hex(operand.imm), kind='reviewed immediate reference'))
    return dict(candidates=words, reviewed_immediates=refs,
                application_reader_window=walk(app, APP_BASE, 0x20062ca4, 0x20062cd0),
                application_comparison_marker_matches_loader=app[0x20062d38-APP_BASE:0x20062d48-APP_BASE] == main[0x4564:0x4574],
                known_accesses=[dict(entry='0x20024d60', role='record writer; requests erase at 0x7f0000 and 16-byte program'),
                                dict(entry='0x20004374', role='loader reads selector marker at 0x187f0000'),
                                dict(entry='0x20062ca4', role='conditional startup path compares 16 bytes at 0x187f0000, stores equality=0/inequality=1 at 0x20390398')],
                limitations=['Aligned data words can be unrelated constants or instruction bytes.',
                             'Application reader is a static internal window; preceding startup calls and entry condition are not executed.',
                             'Bounded ARM immediate scan excludes other routines and computed/indirect addresses.',
                             'No complete reader/writer inventory or ownership of the remaining 64 KiB is established.'])


def prepare_call_results(app, scenario, blocks):
    """Execute separately: nested Unicorn emu_start inside a code hook is unsafe.

    Callers match exact destinations/payload hashes before applying these results.
    This composes control-flow evidence, not a shared hardware-state simulation.
    """
    budget = 2000000 if scenario in ('immediate', 'delayed', 'status_extra_bits') else 10000
    results = {}
    for name in ('enter_command', 'restore_mapping'):
        results[(name, None)] = run_controller(app, name, scenario=scenario, budget=budget)
    for destination, payload in blocks:
        results[('erase', destination)] = run_controller(app, 'erase', scenario=scenario, destination=destination,
                                                        end=destination, budget=budget)
        evidence = run_controller(app, 'program', scenario=scenario, destination=destination,
                                  payload=payload, budget=budget)
        evidence['input_sha256'] = digest(payload)
        results[('program', destination)] = evidence
    return results


def behavior_report(path):
    import capstone
    import unicorn
    from runtime_helpers import helper_report
    data, main, app, _ = inputs(path)
    flows = {name: walk(app, APP_BASE, lo, hi) for name, (lo, hi) in ROUTINES.items()}
    scenarios = {f'{name}:{scenario}': run_controller(app, name, scenario=scenario)
                 for name in ('erase', 'program', 'enter_command', 'restore_mapping') for scenario in SCENARIOS}
    for name in ('enter_command', 'restore_mapping'):
        scenarios[name + ':runtime_unmodeled'] = run_controller(app, name, model_runtime=False)
    from emulate_platform import transfer
    from updater_stages import activation_record
    integration = {scenario: {
        'transfer': transfer(app, b'ABCD' * 4, controller_scenario=scenario),
        'activation': activation_record(app, main, current_selector=1, controller_scenario=scenario),
    } for scenario in ('immediate', 'transfer_stuck', 'busy_stuck', 'write_enable_stuck')}
    return dict(schema_version=1, source_revision=revision(), image_sha256=digest(data),
                tool_sha256={name: digest(Path(__file__).with_name(name).read_bytes()) for name in
                             ('controller.py', 'control_flow.py', 'emulate_platform.py', 'updater_stages.py', 'firmware.py', 'runtime_helpers.py')},
                dependencies=dict(capstone=capstone.__version__, unicorn=unicorn.__version__),
                routine_flow=flows, scenarios=scenarios, integration=integration,
                runtime_helper_evidence=helper_report(app),
                selector_references=selector_references(main, app),
                modeled=['Zero-initialized controller registers outside scripted status reads',
                         'Command interpretation, transfer completion, write-enable and busy response scripts',
                         'Mapping/cache helpers 0x200b9008 and 0x200b9098 where explicitly listed',
                         'Caller flash effects, file reads and other dependencies retained from existing harness',
                         'Caller integration applies separately executed routine results after matching exact destinations and payload hashes; not shared controller state'],
                not_established=['Physical controller errors, flash geometry or persistence',
                                 'Runtime mapping/cache helper effects', 'Complete selector-block ownership',
                                 'DSP/FPGA state machines', 'Recovery or modified-image acceptance'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--verify-repeat', action='store_true')
    args = parser.parse_args()
    result = behavior_report(args.image)
    if args.verify_repeat:
        repeated = behavior_report(args.image)
        if result != repeated:
            raise ValueError('Repeated controller evidence differs')
        result['repeat_identical'] = True
    args.output.parent.mkdir(parents=True, exist_ok=True)
    from reporting import atomic_json
    atomic_json(args.output, result)
    print(f'Controller evidence: {args.output}')


if __name__ == '__main__':
    main()
