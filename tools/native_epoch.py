"""Offline entry-wrapper execution; no installer, peripheral or OS model."""
import struct

from emulate_platform import APP_BASE, RETURN, STACK
from native_capture import ROOT, build_core
from native_receive import Isolated
from native_wrappers import arm_call

CODE = 0x20363000
STATE = 0x2037e080
SITES = {
    'cold': (0x200605fc, (4, 14)),
    'restart': (0x200605e4, (4, 14)),
    'stop': (0x200604c4, (*range(4, 11), 14)),
    'start': (0x2006003c, (4, 5, 6, 14)),
}


def build_bundle():
    code = build_core(ROOT/'prototype/native_receive/epoch_wrappers.S')
    magic, version, *offsets = struct.unpack_from('<8I', code)
    if (magic, version) != (0x45503733, 1) or offsets[0] != 32 or offsets[-1] != len(code):
        raise ValueError('Invalid epoch wrapper header')
    if offsets != sorted(set(offsets)) or any(offset % 4 for offset in offsets):
        raise ValueError('Invalid epoch wrapper offsets')
    core = build_core(ROOT/'prototype/native_receive/epoch.S')
    if code[offsets[-2]:offsets[-2]+len(core)] != core:
        raise ValueError('Bundled epoch core differs from standalone core')
    return code, dict(zip(SITES, (CODE+o for o in offsets[:4])))


def entry_probe(app, kind, fixtures):
    """Fixtures are (CPSR flags/masks, four-word live state), all uint32.

    Stops before the first original callee/instruction after the prologue. Both
    asynchronous masks must be set during every live-state access. This checks
    mask instructions, not actual interrupt delivery or cross-core coherence.
    """
    allowed = 0xf80f00c0  # NZCVQ, GE, IRQ/FIQ masks; privileged ARM SVC mode.
    if kind not in SITES or not isinstance(fixtures, (list, tuple)) or not fixtures:
        raise ValueError('Require a known entry and nonempty fixtures')
    for fixture in fixtures:
        if not isinstance(fixture, (list, tuple)) or len(fixture) != 2:
            raise ValueError('Require flags and state')
        flags, state = fixture
        if type(flags) is not int or flags < 0 or flags & ~allowed or not isinstance(state, (list, tuple)) or len(state) != 4 or any(
                type(word) is not int or not 0 <= word <= 0xffffffff for word in state):
            raise ValueError('Invalid flags or epoch state')
    code, entries = build_bundle()
    entry, saved = SITES[kind]
    h = Isolated(app, [(entry, entry+4), (CODE+32, CODE+len(code))], [(STATE, 16)])
    original = struct.pack('<I', 0xe92d0000 | sum(1 << r for r in saved))
    if app[entry-APP_BASE:entry-APP_BASE+4] != original:
        raise ValueError('Original epoch entry prologue mismatch')
    h.uc.mem_write(CODE, code)
    branch = struct.unpack('<I', arm_call(entry, entries[kind]))[0] & ~0x01000000
    h.uc.mem_write(entry, struct.pack('<I', branch))
    minimum = [STACK+0xf000]
    def observe(uc, access, address, size, value, unused):
        if STATE <= address < STATE+16 and uc.reg_read(h.a.UC_ARM_REG_CPSR) & 0xc0 != 0xc0:
            raise ValueError('Epoch state accessed with asynchronous interrupts unmasked')
    def stack(uc, address, size, unused):
        minimum[0] = min(minimum[0], uc.reg_read(h.a.UC_ARM_REG_SP))
    h.uc.hook_add(h.u.UC_HOOK_MEM_READ | h.u.UC_HOOK_MEM_WRITE, observe)
    h.uc.hook_add(h.u.UC_HOOK_CODE, stack)
    registers = [getattr(h.a, 'UC_ARM_REG_R'+str(i)) for i in range(13)]
    values = [0x12345600+i for i in range(13)]
    rows = []
    for flags, state in fixtures:
        h.uc.reg_write(h.a.UC_ARM_REG_CPSR, 0x13 | flags)
        h.uc.mem_write(STATE, struct.pack('<4I', *state))
        h.uc.mem_write(STACK+0xef80, b'\xa5'*128)
        for reg, value in zip(registers, values): h.uc.reg_write(reg, value)
        h.accesses.clear()
        minimum[0] = STACK+0xf000
        result = h.run(entry, stop=entry+4, budget=80)
        expected_stack = struct.pack('<'+'I'*len(saved), *(RETURN if r == 14 else values[r] for r in saved))
        sp = STACK+0xf000-len(expected_stack)
        if ([h.uc.reg_read(r) for r in registers] != values or
                h.uc.reg_read(h.a.UC_ARM_REG_LR) != RETURN or
                h.uc.reg_read(h.a.UC_ARM_REG_SP) != sp or
                h.uc.reg_read(h.a.UC_ARM_REG_CPSR) != 0x13 | flags or
                bytes(h.uc.mem_read(sp, len(expected_stack))) != expected_stack):
            raise ValueError('Epoch wrapper changed original caller/prologue state')
        if minimum[0] != STACK+0xefe0 or bytes(h.uc.mem_read(STACK+0xef80, 96)) != b'\xa5'*96:
            raise ValueError('Epoch wrapper exceeded 32-byte stack footprint')
        rows.append(dict(result, flags=flags, before=list(state),
                         after=list(struct.unpack('<4I', h.uc.mem_read(STATE, 16))),
                         writes=[(address-STATE, size) for access, address, size in h.accesses if access == h.u.UC_MEM_WRITE]))
    return rows
