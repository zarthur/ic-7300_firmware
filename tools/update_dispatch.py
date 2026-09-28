#!/usr/bin/env python3
"""Read-only v1.42 component equality and bounded update-command dispatch probe."""
import argparse
from pathlib import Path
import struct

from emulate_platform import APP_BASE, RETURN, engine, inputs
from firmware import digest, revision
from reporting import atomic_json
from updater_stages import header_precheck, payload_precheck

COMMANDS = {38: 0x200253f4, 39: 0x20025650, 11: 0x20025ae4}
APP_SHA256 = '4686728c9d1f7249b6278a29686a40b8fa5e527bd2428a76a33cd9395178c9a4'
UI_CASES = ((0x35, 0, 0), (0x39, 0, 0), (0x3a, 0, 0),
            (0x3a, 0, 39), (0x3b, 0, 0), (0x3b, 1, 0))
TOOL_FILES = ('update_dispatch.py', 'emulate_platform.py', 'updater_stages.py',
              'firmware.py', 'reporting.py')


def dispatch(app, command):
    if command not in COMMANDS:
        raise ValueError('Unreviewed dispatch command')
    target = COMMANDS[command]
    machine, u, a = engine()
    machine.mem_map(0x20000000, 0x600000)
    machine.mem_write(APP_BASE, app)
    context = 0x20500000
    machine.mem_write(context + 0x44, struct.pack('<I', command))
    machine.reg_write(a.UC_ARM_REG_R4, context)
    machine.reg_write(a.UC_ARM_REG_R5, 0)
    visited = []

    def code(uc, address, width, user):
        visited.append(address)
        if address == target:
            uc.emu_stop()
        elif not 0x2002754c <= address < 0x20027714:
            raise ValueError('Unreviewed dispatch execution')

    machine.hook_add(u.UC_HOOK_CODE, code)
    machine.emu_start(0x2002754c, target + 4, count=30, timeout=1000000)
    if not visited or visited[-1] != target:
        raise ValueError('Dispatch did not reach expected callee within limits')
    return dict(command=command, callee=hex(target), reached=True,
                executed_instructions=len(visited) - 1, callee_executed=False,
                limits=dict(instructions=30, wall_seconds=1),
                modeled=['command field at synthetic context +0x44', 'private RAM/register state'])


def ui_transition(app, state, handshake, command):
    """Execute one reviewed UI turn with seeded state, stopping before producers."""
    if (state, handshake, command) not in UI_CASES:
        raise ValueError('Unreviewed UI stimulus')
    if digest(app) != APP_SHA256:
        raise ValueError('UI probe requires the exact v1.42 application')
    machine, u, a = engine()
    machine.mem_map(0x20000000, 0x600000)
    machine.mem_write(APP_BASE, app)
    ui, context, signal = 0x20390368, 0x2039011c, 0x20390308
    machine.mem_write(ui, bytes([state]))
    machine.mem_write(signal, bytes([handshake]))
    machine.mem_write(context + 0x44, struct.pack('<I', command))
    stop = {}
    instructions = 0
    boundaries = {0x20022f78: 'header-command producer',
                  0x20059090: 'unresolved payload eligibility predicate',
                  0x20022fc0: 'main-update command producer'}

    def code(uc, address, width, user):
        nonlocal instructions
        if address in boundaries:
            stop.update(reason='unexecuted helper boundary', pc=hex(address),
                        boundary=boundaries[address])
            uc.emu_stop()
        elif not (0x2005b2a0 <= address < 0x2005b4d0 or 0x20023414 <= address < 0x2002344c):
            raise ValueError('Unreviewed UI execution')
        else:
            instructions += 1

    machine.hook_add(u.UC_HOOK_CODE, code)
    machine.emu_start(0x2005b2a0, RETURN, count=300, timeout=1000000)
    pc = machine.reg_read(a.UC_ARM_REG_PC)
    if not stop:
        if pc != RETURN:
            raise ValueError('UI turn did not finish within limits')
        stop.update(reason='returned', pc=hex(pc))
    final_command = struct.unpack('<I', machine.mem_read(context + 0x44, 4))[0]
    if final_command != command:
        raise ValueError('Bounded UI probe unexpectedly wrote a command')
    return dict(initial_ui_state=hex(state), initial_handshake=handshake,
                initial_command=command, final_ui_state=hex(machine.mem_read(ui, 1)[0]),
                final_command=final_command, stop=stop, executed_instructions=instructions,
                limits=dict(instructions=300, wall_seconds=1),
                actual_ui_reachability_proven=False, producer_executed=False,
                modeled=['seeded UI state, command status and handshake', 'private RAM/register state'],
                limitations=['Normal UI entry, confirmations and handshake origin are unestablished.',
                             'No unknown helper is modeled as success; stops do not constitute command submission.'])


ELIGIBILITY_UNSIGNED = (0x203902a2, 0x2039027f, 0x20390285, 0x203da3d0, 0x20396ac8)
ELIGIBILITY_SIGNED = (0x20390448, 0x20390449)


def eligibility_predicate(app, overrides):
    """Execute original local eligibility helpers with explicitly modeled RAM."""
    allowed = ELIGIBILITY_UNSIGNED + ELIGIBILITY_SIGNED
    if not isinstance(overrides, dict) or any(address not in allowed or type(value) is not int
            or not 0 <= value <= 255 for address, value in overrides.items()):
        raise ValueError('Unreviewed eligibility stimulus')
    if digest(app) != APP_SHA256:
        raise ValueError('Eligibility probe requires the exact v1.42 application')
    machine, u, a = engine()
    machine.mem_map(0x20000000, 0x600000)
    machine.mem_write(APP_BASE, app)
    for address in allowed:
        machine.mem_write(address, bytes([overrides.get(address, 0)]))
    bounds = ((0x20059060, 0x2005908c), (0x20047f08, 0x20047f68),
              (0x2006a3f4, 0x2006a400), (0x2006be8c, 0x2006be98),
              (0x2000a23c, 0x2000a248))
    instructions = 0
    helpers = []

    def code(uc, address, width, user):
        nonlocal instructions
        if not any(lo <= address < hi for lo, hi in bounds):
            raise ValueError('Unreviewed eligibility execution')
        instructions += 1
        if address in tuple(lo for lo, _ in bounds):
            helpers.append(hex(address))

    machine.hook_add(u.UC_HOOK_CODE, code)
    machine.emu_start(0x20059060, RETURN, count=300, timeout=1000000)
    if machine.reg_read(a.UC_ARM_REG_PC) != RETURN:
        raise ValueError('Eligibility predicate did not return within limits')
    return dict(result=machine.reg_read(a.UC_ARM_REG_R0),
                modeled_ram={hex(address): overrides.get(address, 0) for address in allowed},
                original_entries_executed=helpers, executed_instructions=instructions,
                limits=dict(instructions=300, wall_seconds=1), modeled_helper_returns=[],
                actual_ui_reachability_proven=False,
                limitations=['Seven RAM bytes are seeded; their live values and producers are not established.',
                             'No command, confirmation or handshake progression is executed.'])


def eligibility_cases(app):
    cases = [('all_zero', {})]
    cases.extend((f'positive_{address:x}', {address: 1})
                 for address in ELIGIBILITY_UNSIGNED + ELIGIBILITY_SIGNED)
    cases.extend((f'negative_{address:x}', {address: 255}) for address in ELIGIBILITY_SIGNED)
    return {name: eligibility_predicate(app, values) for name, values in cases}


def _report(image):
    data, _, app, _ = inputs(image)  # Exact hash/version trace gate before execution.
    import capstone
    import unicorn
    installed = [data[4 + i * 4:8 + i * 4] for i in range(3)]
    cases = [('equal', installed), ('synthetic_lower_numeric', [b'0.00'] * 3),
             ('synthetic_higher_numeric', [b'9.99'] * 3)]
    cases.extend((f'only_component_{i}_different',
                  [b'9.99' if i == j else value for j, value in enumerate(installed)])
                 for i in range(3))
    headers = {name: header_precheck(app, data, installed_ids=ids) for name, ids in cases}
    return dict(schema_version=1, image_sha256=digest(data),
                dependencies=dict(capstone=capstone.__version__, unicorn=unicorn.__version__),
                header_cases=headers,
                equal_component_payload=payload_precheck(app, data, flags=tuple(headers['equal']['component_change_flags'])),
                dispatch_cases={str(command): dispatch(app, command) for command in COMMANDS},
                ui_transition_cases=[ui_transition(app, *case) for case in UI_CASES],
                eligibility_predicate_cases=eligibility_cases(app),
                same_version_reinstall_proven=False,
                limitations=[
                    'Installed component identifiers are synthetic RAM stimuli, not public Main CPU version state.',
                    'Numeric-difference cases test identifier equality behavior, not authorized downgrade acceptance.',
                    'Header/payload checks execute separately with file/hash/comparison helpers modeled.',
                    'Dispatch command and local UI states are seeded; normal UI entry and producer eligibility remain unproven.',
                    'Dispatch stops before the callee; no coherent end-to-end installation path is simulated.',
                    'Executed eligibility predicates read seven modeled RAM bytes, not public-version/component identifiers; upstream eligibility remains unproven.',
                    'No same-version installation, custom-to-stock restoration, component writes or recovery is established.'])


def tool_hashes():
    hashes = {name: digest(Path(__file__).with_name(name).read_bytes()) for name in TOOL_FILES}
    hashes['research/targets.json'] = digest((Path(__file__).resolve().parents[1] / 'research/targets.json').read_bytes())
    return hashes


def identity(path):
    before = path.stat()
    value = digest(path.read_bytes())
    after = path.stat()
    def stamp(stat):
        return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
    if stamp(before) != stamp(after):
        raise ValueError('Image changed while hashing')
    return value, stamp(after)


def report(image):
    image = Path(image)
    initial = identity(image)
    hashes, source = tool_hashes(), revision()
    result = _report(image)
    if identity(image) != initial or result['image_sha256'] != initial[0]:
        raise ValueError('Image changed during dispatch analysis')
    if hashes != tool_hashes() or source != revision():
        raise ValueError('Source changed during dispatch analysis')
    return dict(result, source_revision=source, tool_sha256=hashes, source_unchanged=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output exists; choose a new evidence file')
    result = report(args.image)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(args.output, result)
    print(f'Bounded dispatch evidence: {args.output}')


if __name__ == '__main__':
    main()
