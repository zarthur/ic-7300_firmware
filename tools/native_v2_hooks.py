"""Exact-image offline v2 handler integration, with explicit cache/ACK boundary."""
import struct

from emulate_platform import APP_BASE, STACK, RETURN
from firmware import digest
from native_capture import ROOT, build_core
from native_capture_v2 import MAGIC, VERSION, STORAGE_SIZE
from native_receive import Isolated, COPY, DMA, SPLIT, QUEUE
from native_wrappers import arm_call, TICK, COUNTER, PENDING
from recorder_interface import APPLICATION_SHA256

CODE, CAPTURE, LIVE, EPOCH = 0x20362000, 0x20364000, 0x2038f000, 0x2038f080
GATE, SSI, CHSTAT = 0xfcfe0440, 0xe820b000, 0xe82000e4
SSI_REGISTERS = (SSI, SSI+0x10, SSI+4, SSI+0x14, SSI+0x20)
SITES = {'entry': (0x20060614, struct.pack('<I', 0xe92d4070)),
         'idle': (0x200606e8, struct.pack('<I', 0xe8bd8070)),
         'restart': (0x20060644, struct.pack('<I', struct.unpack('<I', arm_call(0x20060644, 0x200605e4))[0] & ~0x01000000)),
         'ready': (0x200606d8, arm_call(0x200606d8, 0x2005fb28))}


def build_bundle():
    code = build_core(ROOT/'prototype/native_receive/capture_v2_hooks.S')
    magic, version, *offsets = struct.unpack_from('<9I', code)
    if (magic, version) != (0x32483733, 2) or offsets[0] != 36 or offsets[-1] != len(code) or offsets != sorted(set(offsets)) or any(o % 4 for o in offsets):
        raise ValueError('Invalid v2 hook header')
    for name, offset in (('capture_v2', offsets[4]), ('ssif_observe', offsets[5])):
        core = build_core(ROOT/f'prototype/native_receive/{name}.S')
        if code[offset:offset+len(core)] != core:
            raise ValueError('Bundled v2 component differs from standalone core')
    if CODE+len(code) > CAPTURE or CAPTURE+STORAGE_SIZE > LIVE or LIVE+32 > EPOCH or EPOCH+16 > 0x20390000:
        raise ValueError('V2 hook footprint overlaps storage')
    return code, dict(zip(SITES, (CODE+o for o in offsets[:4])))


def offline_edits(app):
    """Only consumed by the emulator here; no firmware/container/card writer."""
    if digest(app) != APPLICATION_SHA256: raise ValueError('Requires exact pinned v1.42 application')
    code, entries = build_bundle()
    edits = []
    for name, (site, expected) in SITES.items():
        if app[site-APP_BASE:site-APP_BASE+4] != expected:
            raise ValueError('Original v2 hook site mismatch')
        word = struct.unpack('<I', arm_call(site, entries[name]))[0]
        if name != 'ready': word &= ~0x01000000
        edits.append((site, struct.pack('<I', word)))
    storage = struct.pack('<4I', 0, 0, MAGIC, VERSION)+bytes(STORAGE_SIZE-16)
    for address, data in ((CODE, code), (CAPTURE, storage), (LIVE, bytes(32)), (EPOCH, bytes(16))):
        before = app[address-APP_BASE:address-APP_BASE+len(data)]
        if len(before) != len(data) or any(b != 255 for b in before):
            raise ValueError('V2 diagnostic padding is not all FF')
        edits.append((address, data))
    return edits


class HookTrial:
    """Original decision and post-cache extraction/queues are separate stages.

    Ready decisions stop before ACK/cache instructions. `ready` supplies their
    documented post-state, rather than pretending to execute hardware effects.
    """
    def __init__(self, app, patched=True):
        code, self.entries = build_bundle()
        ranges = [(CODE+36, CODE+len(code)), (0x20060614, 0x20060650),
                  (0x20060690, 0x200606ec), (0x200605e4, 0x200605e8),
                  (0x2005fb28, 0x2005fb64), (0x2005fc24, 0x2005fc60), COPY]
        regions = [(CAPTURE, STORAGE_SIZE), (LIVE, 32), (EPOCH, 16), (CHSTAT, 4),
                   (DMA, 1152), (SPLIT, 144), (QUEUE, 0x242), (0x203fc002, 0x243),
                   (TICK, 4), (COUNTER, 4), (PENDING, 4), (GATE, 1), (SSI, 0x24)]
        self.h = Isolated(app, ranges, regions)
        self.uc, self.u, self.a = self.h.uc, self.h.u, self.h.a
        for address, data in offline_edits(app):
            if patched or address >= CODE: self.uc.mem_write(address, data)
        self.snapshots, self.timer_reads, self.ssif_reads = [], [], []
        self.next_snapshot = 0
        self.minimum_sp = STACK+0xf000
        self.ready_bank = None
        self.uc.hook_add(self.u.UC_HOOK_CODE, self._code)
        self.uc.hook_add(self.u.UC_HOOK_MEM_READ | self.u.UC_HOOK_MEM_WRITE, self._observe)

    def _code(self, uc, address, size, unused):
        self.minimum_sp = min(self.minimum_sp, uc.reg_read(self.a.UC_ARM_REG_SP))
        if address in (0x2006064c, 0x200605e4): uc.emu_stop()

    def _observe(self, uc, access, address, size, value, unused):
        write = access == self.u.UC_MEM_WRITE
        if CAPTURE <= address < CAPTURE+STORAGE_SIZE and write and struct.unpack('<I', uc.mem_read(CAPTURE, 4))[0] in (2, 5, 6):
            raise ValueError('V2 hook wrote frozen storage')
        if LIVE <= address < LIVE+32 or EPOCH <= address < EPOCH+16:
            if uc.reg_read(self.a.UC_ARM_REG_CPSR) & 0xc0 != 0xc0:
                raise ValueError('Unmasked v2 live/epoch access')
        if address in (TICK, COUNTER, PENDING):
            sequence = (TICK, COUNTER, PENDING)*2
            if write or size != 4 or self.next_snapshot >= len(self.snapshots) or address != sequence[self.next_snapshot]:
                raise ValueError('Unexpected v2 timer observation')
            supplied = self.snapshots[self.next_snapshot]
            uc.mem_write(address, struct.pack('<I', supplied))
            self.next_snapshot += 1
            self.timer_reads.append((address, supplied))
        if address == GATE or SSI <= address < SSI+0x24:
            if write or uc.reg_read(self.a.UC_ARM_REG_CPSR) & 0xc0 != 0xc0:
                raise ValueError('Unsafe SSIF observation access')
            if address == GATE:
                if size != 1: raise ValueError('Unexpected gate access width')
            elif address not in SSI_REGISTERS or size != 4 or uc.mem_read(GATE, 1)[0] & 0x20:
                raise ValueError('Gated or unapproved SSI register read')
            self.ssif_reads.append(address)

    def configure(self, status=1, count=0, epoch=(7, 4, 0), gate=0,
                  ssif=(0x3c2b0033, 0xcc, 2, 0x10301, 0)):
        if len(epoch) != 3 or len(ssif) != 5 or type(gate) is not int or not 0 <= gate <= 255 or any(
                type(v) is not int or not 0 <= v <= 0xffffffff for v in (status, count, *epoch, *ssif)):
            raise ValueError('Require bounded v2 configuration fixtures')
        self.uc.mem_write(CAPTURE, struct.pack('<4I', status, count, MAGIC, VERSION))
        self.uc.mem_write(LIVE, bytes(32))
        self.uc.mem_write(EPOCH, struct.pack('<4I', *epoch, 0))
        self.uc.mem_write(GATE, bytes([gate]))
        for address, value in zip(SSI_REGISTERS, ssif): self.uc.mem_write(address, struct.pack('<I', value))

    def _registers(self):
        return [self.uc.reg_read(getattr(self.a, 'UC_ARM_REG_R'+str(i))) for i in range(13)]

    def decision(self, status, masks=0, flags=0xf80f0000):
        if type(status) is not int or not 0 <= status <= 0xffffffff or masks not in (0, 0x40, 0x80, 0xc0) or flags & ~0xf80f0000:
            raise ValueError('Invalid decision fixture')
        self.uc.mem_write(CHSTAT, struct.pack('<I', status))
        self.uc.reg_write(self.a.UC_ARM_REG_CPSR, 0x13 | masks | flags)
        for i in range(13): self.uc.reg_write(getattr(self.a, 'UC_ARM_REG_R'+str(i)), 0x12340000+i)
        self.uc.reg_write(self.a.UC_ARM_REG_SP, STACK+0xf000)
        self.uc.reg_write(self.a.UC_ARM_REG_LR, RETURN)
        self.minimum_sp = STACK+0xf000
        self.timer_reads, self.ssif_reads = [], []
        self.next_snapshot = 0
        self.uc.emu_start(0x20060614, RETURN, count=1000, timeout=1000000)
        pc = self.uc.reg_read(self.a.UC_ARM_REG_PC)
        if pc not in (RETURN, 0x2006064c, 0x200605e4): raise ValueError('Unexpected handler decision boundary')
        self.ready_bank = self.uc.reg_read(self.a.UC_ARM_REG_R0) if pc == 0x2006064c else None
        sp = self.uc.reg_read(self.a.UC_ARM_REG_SP)
        return dict(boundary=pc, registers=self._registers(), sp=sp,
                    lr=self.uc.reg_read(self.a.UC_ARM_REG_LR), cpsr=self.uc.reg_read(self.a.UC_ARM_REG_CPSR),
                    frame=bytes(self.uc.mem_read(sp, 16)) if self.ready_bank is not None else None)

    def ready(self, words, snapshots=(1, 32000, 0, 1, 31990, 0), epoch_after_selection=None):
        if self.ready_bank not in (0, 1) or not isinstance(words, bytes) or len(words) != 576 or len(snapshots) != 6 or any(
                type(v) is not int or not 0 <= v <= 0xffffffff for v in snapshots):
            raise ValueError('Require a ready decision, DMA bank, and timer fixtures')
        if epoch_after_selection is not None:
            if len(epoch_after_selection) != 3 or any(type(v) is not int or not 0 <= v <= 0xffffffff for v in epoch_after_selection):
                raise ValueError('Invalid injected epoch fixture')
            self.uc.mem_write(EPOCH, struct.pack('<4I', *epoch_after_selection, 0))
        bank = self.ready_bank
        self.ready_bank = None
        self.snapshots = list(snapshots)
        self.uc.mem_write(DMA+bank*576, words)
        self.uc.reg_write(self.a.UC_ARM_REG_R2, DMA+bank*576)
        self.uc.reg_write(self.a.UC_ARM_REG_R1, DMA+(bank+1)*576)
        self.uc.reg_write(self.a.UC_ARM_REG_R0, DMA+(bank+1)*576)
        cpsr = self.uc.reg_read(self.a.UC_ARM_REG_CPSR)
        self.uc.reg_write(self.a.UC_ARM_REG_CPSR, (cpsr & ~0xf0000000) | 0x60000000)
        # Continue with supplied post-cache state; preserve the actual original
        # entry frame. ACK/cache instructions are excluded from executable ranges.
        self.uc.emu_start(0x20060690, RETURN, count=10000, timeout=1000000)
        if self.uc.reg_read(self.a.UC_ARM_REG_PC) != RETURN: raise ValueError('V2 ready hook did not return')
        return dict(queue_a=bytes(self.uc.mem_read(QUEUE, 0x242)),
                    queue_b=bytes(self.uc.mem_read(0x203fc002, 0x243)),
                    split=bytes(self.uc.mem_read(SPLIT, 144)), registers=self._registers(),
                    sp=self.uc.reg_read(self.a.UC_ARM_REG_SP), lr=self.uc.reg_read(self.a.UC_ARM_REG_LR),
                    cpsr=self.uc.reg_read(self.a.UC_ARM_REG_CPSR),
                    timer_reads=list(self.timer_reads), ssif_reads=list(self.ssif_reads),
                    stack_below_caller=STACK+0xf000-self.minimum_sp)

    def storage(self): return bytes(self.uc.mem_read(CAPTURE, STORAGE_SIZE))
    def live(self): return struct.unpack('<8I', self.uc.mem_read(LIVE, 32))
