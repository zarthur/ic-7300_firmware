"""Bounded mapping-helper execution; all cache/MMU effects remain explicit models."""
from collections import Counter
import struct

from control_flow import walk
from emulate_platform import APP_BASE, RETURN, STACK, engine
from firmware import digest

BOUNDS = {
    'enter_mapping_helper': (0x200b9008, 0x200b9098),
    'restore_mapping_helper': (0x200b9098, 0x200b9120),
    'descriptor_attributes': (0x200b8a0c, 0x200b8b38),
    'descriptor_memory_type': (0x200b8804, 0x200b8900),
    'section_table': (0x200b91e0, 0x200b9214),
    'cache_by_set_way': (0x200052dc, 0x20005388),
    'external_cache_wait': (0x200b92d0, 0x200b9318),
    'external_cache_sync': (0x200b9260, 0x200b9270),
}
# Reviewed coprocessor/barrier sites only: never let Unicorn silently stand in
# for cache effects. Read stimuli describe synthetic geometry, not this CPU.
CP_READS = {0x200052e0: ('CLIDR', 'r6'), 0x20005310: ('CCSIDR', 'r1')}
CP_WRITES = {0x20005308, 0x20005344, 0x20005354, 0x2000535c,
             0x200b907c, 0x200b9088, 0x200b9104, 0x200b9110}
BARRIERS = {0x2000530c, 0x2000537c, 0x200b9080, 0x200b9084,
            0x200b908c, 0x200b9090, 0x200b9108, 0x200b910c,
            0x200b9114, 0x200b9118}


def run_helper(app, name, *, cache_geometry=None, peripheral=None, ways16=False, budget=10000):
    if name not in ('enter_mapping_helper', 'restore_mapping_helper'):
        raise ValueError('Unknown mapping helper')
    if cache_geometry not in (None, 'no_data_cache', 'one_set_one_way'):
        raise ValueError('Unknown cache stimulus')
    if peripheral not in (None, 'immediate', 'delayed', 'stuck'):
        raise ValueError('Unknown peripheral stimulus')
    if not 0 < budget <= 100000:
        raise ValueError('Invalid instruction budget')
    uc, u, a = engine()
    uc.mem_map(0x20000000, 0x600000)
    uc.mem_write(APP_BASE, app)
    uc.mem_map(0x3ffff000, 0x1000)
    stopped, events, executed = {}, [], Counter()
    instructions = reads = 0
    def stop(outcome, **details):
        stopped.update(outcome=outcome, pc=hex(uc.reg_read(a.UC_ARM_REG_PC)), **details)
        uc.emu_stop()
    def code(machine, address, size, user):
        nonlocal instructions
        instructions += 1
        routine = next((n for n, (lo, hi) in BOUNDS.items() if lo <= address < hi), None)
        if routine is None:
            stop('UNRESOLVED', reason='Outside reviewed instruction bounds', target=hex(address)); return
        executed[routine] += 1
        if address in CP_READS or address in CP_WRITES or address in BARRIERS:
            if cache_geometry is None:
                stop('UNRESOLVED_COPROCESSOR', reason='Requires physical cache geometry or maintenance effects'); return
            event = dict(operation='modeled_maintenance', pc=hex(address), effects='not simulated')
            if address in CP_READS:
                register, destination = CP_READS[address]
                value = 0x01000002 if register == 'CLIDR' and cache_geometry == 'one_set_one_way' else 0
                uc.reg_write(getattr(a, 'UC_ARM_REG_' + destination.upper()), value)
                event = dict(operation='modeled_coprocessor_read', pc=hex(address), register=register, value=value)
            elif address in CP_WRITES:
                # Operand values from the reviewed fixed instruction encodings.
                register = 'R10' if address == 0x20005308 else ('R11' if address in (0x20005344, 0x20005354, 0x2000535c) else 'R4')
                event['value'] = uc.reg_read(getattr(a, 'UC_ARM_REG_' + register))
            events.append(event)
            uc.reg_write(a.UC_ARM_REG_PC, address + 4)
    def memory(machine, access, address, size, value, user):
        nonlocal reads
        if STACK <= address < STACK + 0x10000: return
        if 0x3ffff000 <= address < 0x40000000:
            allowed = size == 4 and ((access == u.UC_MEM_READ and address in (0x3ffff104, 0x3ffff7fc)) or
                                   (access == u.UC_MEM_WRITE and address in (0x3ffff7fc, 0x3ffff730)))
            if not allowed:
                stop('UNKNOWN_MMIO', address=hex(address), size=size); return
            if peripheral is None:
                stop('UNRESOLVED_MMIO', address=hex(address), reason='External cache controller response unmodeled'); return
            if access == u.UC_MEM_READ:
                if address == 0x3ffff104: value = 0x10000 if ways16 else 0
                else:
                    reads += 1
                    value = (0xffff if ways16 else 0xff) if peripheral == 'stuck' or (peripheral == 'delayed' and reads <= 2) else 0
                uc.mem_write(address, struct.pack('<I', value))
            if len(events) < 2048:
                events.append(dict(operation='modeled_mmio_read' if access == u.UC_MEM_READ else 'mmio_write', address=hex(address), value=value))
        elif access == u.UC_MEM_WRITE:
            if size != 4 or not (0x20000600 <= address < 0x20000700 or address in (0x20390794, 0x203907a8)):
                stop('UNRESOLVED_MEMORY_WRITE', address=hex(address), size=size); return
            events.append(dict(operation='memory_write', address=hex(address), value=value))
        elif not APP_BASE <= address < APP_BASE + len(app):
            stop('UNRESOLVED_MEMORY_READ', address=hex(address), size=size)
    def invalid(machine, access, address, size, value, user):
        stop('UNMAPPED_MEMORY', address=hex(address), size=size); return False
    uc.hook_add(u.UC_HOOK_CODE, code)
    uc.hook_add(u.UC_HOOK_MEM_READ | u.UC_HOOK_MEM_WRITE, memory)
    uc.hook_add(u.UC_HOOK_MEM_INVALID, invalid)
    try: uc.emu_start(BOUNDS[name][0], RETURN, timeout=3000000, count=budget)
    except u.UcError as exc:
        if not stopped: stop('EMULATION_ERROR', reason=str(exc))
    if not stopped:
        pc = uc.reg_read(a.UC_ARM_REG_PC)
        stopped.update(outcome='RETURNED' if pc == RETURN else 'LIMIT', pc=hex(pc))
    table = bytes(uc.mem_read(0x20000600, 0x100))
    return dict(routine=name, mode='ARM', **stopped, instructions=instructions,
                cache_geometry=cache_geometry, peripheral=peripheral, ways16=ways16,
                executed_routines=dict(executed), events=events, polling_reads=reads,
                events_truncated=len(events) >= 2048,
                table_words=list(struct.unpack('<64I', table)), table_sha256=digest(table),
                limits=dict(instructions=budget, wall_seconds=3),
                modeled_helpers=[],
                limitations=['RAM starts with official image bytes and zero scratch/table storage; no startup execution',
                             'Explicitly modeled coprocessor operations and barriers have no physical effects',
                             'Synthetic cache geometry and external controller responses do not identify hardware',
                             'Instruction return is not proof of coherent caches, TLBs, mapping or persistent writes'])


def helper_report(app):
    scenarios = {}
    for name in ('enter_mapping_helper', 'restore_mapping_helper'):
        scenarios[name + ':strict'] = run_helper(app, name)
        scenarios[name + ':cache_only'] = run_helper(app, name, cache_geometry='one_set_one_way')
        for geometry in ('no_data_cache', 'one_set_one_way'):
            for peripheral in ('immediate', 'delayed', 'stuck'):
                for ways16 in (False, True):
                    key = f'{name}:{geometry}:{peripheral}:ways{16 if ways16 else 8}'
                    scenarios[key] = run_helper(app, name, cache_geometry=geometry, peripheral=peripheral, ways16=ways16)
    return dict(routine_flow={n: walk(app, APP_BASE, lo, hi) for n, (lo, hi) in BOUNDS.items()}, scenarios=scenarios,
                integration='Separate diagnostic evidence only; controller caller helper substitutions are retained')
