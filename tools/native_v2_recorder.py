"""Offline combined v2 hooks, lifecycle boundaries and recorder integration."""
import struct

from emulate_platform import APP_BASE, STACK, RETURN
from native_capture import ROOT, build_core
from native_capture_v2 import STORAGE_SIZE
from native_receive import Isolated, COPY, CLEAR, DMA, SPLIT, QUEUE, STATE, INDICES, SCRATCH, RING
from native_wrappers import arm_call, RECORD, WrapperTrial
import native_epoch as epoch
import native_v2_hooks as hooks

CODE, CAPTURE, LIVE, EPOCH = hooks.CODE, hooks.CAPTURE, hooks.LIVE, hooks.EPOCH
EPOCH_CODE, RECORDER_CODE, CONTROL = 0x20362800, 0x20363000, 0x2038f040
RECORDER_SITES = {'arm': (0x200497f0, arm_call(0x200497f0, 0x2006a354)),
                  'carrier': (0x20066f80, arm_call(0x20066f80, 0x2017c710, True))}


def build_bundle():
    """Keep separately tested byte-identical components in disjoint code spans."""
    capture, capture_entries = hooks.build_bundle()
    lifecycle = build_core(ROOT/'prototype/native_receive/epoch_v2_wrappers.S')
    original, _ = epoch.build_bundle()
    old_address = struct.pack('<I', epoch.STATE)
    if original.count(old_address) != 1 or lifecycle != original.replace(old_address, struct.pack('<I', EPOCH)):
        raise ValueError('Relocated lifecycle code differs beyond its state address')
    offsets = struct.unpack_from('<8I', lifecycle)[2:6]
    lifecycle_entries = dict(zip(epoch.SITES, (EPOCH_CODE+o for o in offsets)))
    recorder = build_core(ROOT/'prototype/native_receive/recorder_v2_hooks.S')
    magic, version, arm, carrier, core, end = struct.unpack_from('<6I', recorder)
    if (magic, version) != (0x32523733, 2) or arm != 24 or not arm < carrier < core < end or end != len(recorder) or any(o % 4 for o in (arm, carrier, core, end)):
        raise ValueError('Invalid recorder v2 bundle header')
    transport = build_core(ROOT/'prototype/native_receive/transport_v2.S')
    if recorder[core:] != transport:
        raise ValueError('Embedded carrier differs from standalone tested core')
    spans = [(CODE, len(capture)), (EPOCH_CODE, len(lifecycle)), (RECORDER_CODE, len(recorder)),
             (CAPTURE, STORAGE_SIZE), (LIVE, 32), (CONTROL, 8), (EPOCH, 16)]
    if any(a+n > b for (a,n),(b,m) in zip(spans,spans[1:])) or spans[-1][0]+16 > 0x20390000:
        raise ValueError('Combined diagnostic layout overlaps or exceeds padding')
    return ((CODE, capture), (EPOCH_CODE, lifecycle), (RECORDER_CODE, recorder)), dict(
        capture=capture_entries, lifecycle=lifecycle_entries,
        recorder={'arm': RECORDER_CODE+arm, 'carrier': RECORDER_CODE+carrier})


def offline_edits(app):
    """Exact image gate before substitutions; no image/container/card writer."""
    edits = hooks.offline_edits(app)
    blobs, entries = build_bundle()
    for kind, (site, saved) in epoch.SITES.items():
        expected = struct.pack('<I', 0xe92d0000 | sum(1 << r for r in saved))
        if app[site-APP_BASE:site-APP_BASE+4] != expected:
            raise ValueError('Original lifecycle prologue mismatch')
        word = struct.unpack('<I', arm_call(site, entries['lifecycle'][kind]))[0] & ~0x01000000
        edits.append((site, struct.pack('<I', word)))
    for kind, (site, expected) in RECORDER_SITES.items():
        if app[site-APP_BASE:site-APP_BASE+4] != expected:
            raise ValueError('Original recorder call mismatch')
        edits.append((site, arm_call(site, entries['recorder'][kind])))
    for address, data in (*blobs[1:], (CONTROL, bytes(8))):
        before = app[address-APP_BASE:address-APP_BASE+len(data)]
        if len(before) != len(data) or any(b != 255 for b in before):
            raise ValueError('Combined v2 padding is not all FF')
        edits.append((address, data))
    spans = sorted((a,a+len(data)) for a,data in edits)
    if any(a[1] > b[0] for a,b in zip(spans, spans[1:])):
        raise ValueError('Combined diagnostic substitutions overlap')
    return edits


class CombinedTrial(hooks.HookTrial):
    """Original bounded paths, with explicit ACK/cache and OS stop boundaries.

    Recorder calls are serialized fixtures; this does not simulate scheduling,
    hardware IRQ delivery, DMA, cache maintenance or actual file submission.
    """
    def __init__(self, app, patched=True):
        blobs, self.combined_entries = build_bundle()
        self.entries = self.combined_entries['capture']
        ranges = [(address+header, address+len(code)) for (address,code),header in zip(blobs,(36,32,24))]
        ranges += [(0x20060614,0x20060650), (0x20060690,0x200606ec),
                   (0x2005fb28,0x2005fb64), (0x2005fc24,0x2005fc60),
                   (0x20066f18,0x20066fc4), (0x200497f0,0x200497f4),
                   (0x2006a354,0x2006a370), COPY, CLEAR]
        ranges += [(site,site+4) for site,_ in epoch.SITES.values()]
        regions = [(CAPTURE,STORAGE_SIZE), (LIVE,32), (EPOCH,16), (CONTROL,8), (hooks.CHSTAT,4),
                   (DMA,1152), (SPLIT,144), (QUEUE,0x242), (0x203fc002,0x243),
                   (hooks.TICK,4), (hooks.COUNTER,4), (hooks.PENDING,4), (hooks.GATE,1), (hooks.SSI,0x24),
                   (STATE,16), (INDICES,0xdc), (SCRATCH,216), (RING,1914*220), (RECORD,0x58)]
        self.h = Isolated(app, ranges, regions)
        self.uc, self.u, self.a = self.h.uc, self.h.u, self.h.a
        for address,data in offline_edits(app):
            if patched or address >= CODE: self.uc.mem_write(address,data)
        self.snapshots, self.timer_reads, self.ssif_reads = [], [], []
        self.next_snapshot, self.ready_bank = 0, None
        self.minimum_sp = STACK+0xf000
        self.running_decision = False
        self.uc.hook_add(self.u.UC_HOOK_CODE, self._code)
        self.uc.hook_add(self.u.UC_HOOK_MEM_READ | self.u.UC_HOOK_MEM_WRITE, self._observe)

    def _code(self, uc, address, size, unused):
        self.minimum_sp = min(self.minimum_sp, uc.reg_read(self.a.UC_ARM_REG_SP))
        if self.running_decision and address in (0x2006064c,0x200605e4): uc.emu_stop()

    def decision(self, status, masks=0, flags=0xf80f0000):
        self.running_decision = True
        try: return super().decision(status,masks,flags)
        finally: self.running_decision = False

    # These execute the reviewed original publisher/submission boundaries.
    publish = WrapperTrial.publish
    arm = WrapperTrial.arm
    def control(self): return struct.unpack('<2I',self.uc.mem_read(CONTROL,8))

    def lifecycle(self, kind, flags=0):
        if kind not in epoch.SITES or type(flags) is not int or flags < 0 or flags & ~0xf80f00c0:
            raise ValueError('Invalid lifecycle fixture')
        site,saved = epoch.SITES[kind]
        self.uc.reg_write(self.a.UC_ARM_REG_CPSR,0x13|flags)
        values = [0x12345600+i for i in range(13)]
        for i,value in enumerate(values): self.uc.reg_write(getattr(self.a,'UC_ARM_REG_R'+str(i)),value)
        result = self.h.run(site,stop=site+4,budget=100)
        frame = struct.pack('<'+'I'*len(saved),*(RETURN if r == 14 else values[r] for r in saved))
        sp = STACK+0xf000-len(frame)
        if (self._registers() != values or self.uc.reg_read(self.a.UC_ARM_REG_LR) != RETURN or
                self.uc.reg_read(self.a.UC_ARM_REG_SP) != sp or self.uc.reg_read(self.a.UC_ARM_REG_CPSR) != 0x13|flags or
                bytes(self.uc.mem_read(sp,len(frame))) != frame):
            raise ValueError('Combined lifecycle hook changed original prologue state')
        result['epoch'] = struct.unpack('<4I',self.uc.mem_read(EPOCH,16))
        return result
