"""Firmware-free execution/decoding of the two-phase receive capture prototype."""
import struct

from emulate_platform import engine, RETURN, STACK
from native_capture import ROOT, build_core

CODE, STORAGE, SAMPLES, OBS, LIVE, EPOCH = (0x01000000, 0x02000010, 0x03000002,
                                          0x04000000, 0x05000000, 0x06000000)
CAPACITY, RECORD_SIZE, HEADER_SIZE = 512, 224, 16
STORAGE_SIZE = HEADER_SIZE+CAPACITY*RECORD_SIZE
MAGIC, VERSION = 0x3252434e, 2


def build_bundle():
    code = build_core(ROOT/'prototype/native_receive/capture_v2.S')
    magic, version, begin, finish, cancel, samples, end = struct.unpack_from('<7I', code)
    if (magic, version) != (0x3256434e, 2) or begin != 28 or end != len(code) or not begin < finish < samples < cancel < end or any(
            offset % 4 for offset in (begin, finish, cancel, samples, end)):
        raise ValueError('Invalid two-phase capture bundle')
    return code, {'begin': CODE+begin, 'finish': CODE+finish, 'cancel': CODE+cancel, 'samples': CODE+samples}


class CaptureTrial:
    """Synthetic private RAM; explicit context switches are not hardware IRQs."""
    def __init__(self, status=1, count=0, masks=0):
        self.code, self.entries = build_bundle()
        self.uc, self.u, self.a = engine()
        self.uc.mem_map(CODE, 4096, self.u.UC_PROT_READ | self.u.UC_PROT_EXEC)
        self.uc.mem_write(CODE, self.code)
        self.uc.mem_map(STORAGE & ~4095, 0x1d000)
        for address in (SAMPLES & ~4095, OBS, LIVE, EPOCH): self.uc.mem_map(address, 4096)
        self.uc.mem_write(STORAGE-4, b'\xa5'*(STORAGE_SIZE+8))
        self.uc.mem_write(STORAGE, struct.pack('<4I', status, count, MAGIC, VERSION))
        self.uc.mem_write(LIVE, bytes(32))
        self.uc.mem_write(EPOCH, struct.pack('<4I', 1, 1, 0, 0))
        self.uc.mem_write(SAMPLES, bytes(range(144)))
        self.uc.mem_write(OBS, struct.pack('<12I', *range(12)))
        self.masks = masks
        self.paused = None
        self.pause_target = None
        self.sample_visits = 0
        self.writes = []
        self.copy_masks = []
        self.uc.hook_add(self.u.UC_HOOK_CODE, self._code)
        self.uc.hook_add(self.u.UC_HOOK_MEM_READ | self.u.UC_HOOK_MEM_WRITE, self._memory)

    def _code(self, uc, address, size, unused):
        if not CODE+28 <= address or address+size > CODE+len(self.code):
            raise ValueError('Capture escaped reviewed code')
        if address == self.entries['samples']:
            self.sample_visits += 1
            self.copy_masks.append(uc.reg_read(self.a.UC_ARM_REG_CPSR) & 0xc0)
            if self.pause_target == self.sample_visits:
                self.pause_target = None
                uc.emu_stop()

    def _memory(self, uc, access, address, size, value, unused):
        write = access == self.u.UC_MEM_WRITE
        if STACK <= address and address+size <= STACK+0x10000: return
        if STORAGE <= address and address+size <= STORAGE+STORAGE_SIZE:
            if write:
                status = struct.unpack('<I', uc.mem_read(STORAGE, 4))[0]
                if status in (2, 5, 6): raise ValueError('Capture wrote frozen storage')
                self.writes.append((address-STORAGE, size))
            return
        if LIVE <= address and address+size <= LIVE+32:
            if uc.reg_read(self.a.UC_ARM_REG_CPSR) & 0xc0 != 0xc0:
                raise ValueError('Unmasked live-state access')
            return
        if EPOCH <= address and address+size <= EPOCH+16 and not write:
            if uc.reg_read(self.a.UC_ARM_REG_CPSR) & 0xc0 != 0xc0:
                raise ValueError('Unmasked epoch access')
            return
        if not write and ((SAMPLES <= address and address+size <= SAMPLES+144) or
                          (OBS <= address and address+size <= OBS+48)): return
        raise ValueError(f'Capture access outside contract: {address:#x}+{size}, write={write}')

    def _check_return(self, frame):
        regs, expected, sp, masks = frame
        if self.uc.reg_read(self.a.UC_ARM_REG_PC) != RETURN:
            raise ValueError('Capture failed to return within budget')
        if [self.uc.reg_read(r) for r in regs] != expected or self.uc.reg_read(self.a.UC_ARM_REG_SP) != sp:
            raise ValueError('Capture violated preserved register/stack contract')
        if self.uc.reg_read(self.a.UC_ARM_REG_CPSR) & 0xdf != 0x13 | masks:
            raise ValueError('Capture changed mode or IRQ/FIQ masks')
        if bytes(self.uc.mem_read(STORAGE-4, 4))+bytes(self.uc.mem_read(STORAGE+STORAGE_SIZE, 4)) != b'\xa5'*8:
            raise ValueError('Capture damaged storage guards')
        return self.uc.reg_read(self.a.UC_ARM_REG_R0)

    def call(self, kind, pause_at_sample=None, sp=STACK+0xf000):
        if kind not in ('begin', 'finish', 'cancel'): raise ValueError('Unknown capture entry')
        if pause_at_sample is not None and (kind != 'finish' or not 1 <= pause_at_sample <= 72):
            raise ValueError('Pause requires a sample iteration 1..72')
        a = self.a
        regs = [getattr(a, 'UC_ARM_REG_R'+str(i)) for i in range(4, 12)]
        expected = [0x12340000+i for i in range(8)]
        self.uc.reg_write(a.UC_ARM_REG_CPSR, 0x13 | self.masks)
        for reg, value in zip(regs, expected): self.uc.reg_write(reg, value)
        for reg, value in ((a.UC_ARM_REG_R0, STORAGE), (a.UC_ARM_REG_R1, LIVE),
                           (a.UC_ARM_REG_R2, EPOCH), (a.UC_ARM_REG_R3, SAMPLES),
                           (a.UC_ARM_REG_SP, sp), (a.UC_ARM_REG_LR, RETURN)):
            self.uc.reg_write(reg, value)
        self.uc.mem_write(sp, struct.pack('<I', OBS))
        self.pause_target, self.sample_visits = pause_at_sample, 0
        self.uc.emu_start(self.entries[kind], RETURN, count=1000, timeout=1000000)
        frame = regs, expected, sp, self.masks
        if self.uc.reg_read(a.UC_ARM_REG_PC) != RETURN and pause_at_sample is not None:
            if self.uc.reg_read(a.UC_ARM_REG_PC) != self.entries['samples']:
                raise ValueError('Unexpected paused instruction')
            self.paused = self.uc.context_save(), frame
            return None
        return self._check_return(frame)

    def resume(self):
        if self.paused is None: raise ValueError('No paused capture')
        context, frame = self.paused
        self.paused = None
        self.uc.context_restore(context)
        self.pause_target = None
        self.uc.emu_start(self.uc.reg_read(self.a.UC_ARM_REG_PC), RETURN, count=1000, timeout=1000000)
        return self._check_return(frame)

    def storage(self): return bytes(self.uc.mem_read(STORAGE, STORAGE_SIZE))
    def live(self): return struct.unpack('<8I', self.uc.mem_read(LIVE, 32))
    def epoch(self, number, reason=1, exhausted=0):
        self.uc.mem_write(EPOCH, struct.pack('<4I', number, reason, exhausted, 0))


def decode_storage(data):
    if not isinstance(data, bytes) or len(data) != STORAGE_SIZE:
        raise ValueError('Require exact v2 storage size')
    status, count, magic, version = struct.unpack_from('<4I', data)
    if (magic, version) != (MAGIC, VERSION) or status not in (0, 1, 2, 5, 6) or count > CAPACITY:
        raise ValueError('Invalid or unstable v2 control')
    if (status == 2 and count != CAPACITY) or (status in (0, 1, 6) and count == CAPACITY) or (status == 0 and count) or (status == 5 and not count):
        raise ValueError('Inconsistent v2 status/count')
    records = []
    for i in range(count):
        words = struct.unpack_from('<20I72h', data, HEADER_SIZE+i*RECORD_SIZE)
        sequence, flags = words[:2]
        before, after = words[2:5], words[5:8]
        expected = (int(before[0] != after[0]) | (2 if not before[0] or not after[0] else 0) |
                    (4 if before[2] or after[2] else 0))
        nested = bool(flags & 8)
        if sequence != i or flags & ~31 or flags & 7 != expected or nested != (status == 5 and i == count-1):
            raise ValueError('Inconsistent v2 record flags or sequence')
        if flags & 16 and words[15:20] != (0xffffffff,)*5:
            raise ValueError('Unavailable SSI observations require explicit sentinel words')
        records.append(dict(sequence=sequence, flags=flags, epoch_before=list(before),
                            epoch_after=list(after), observations=list(words[8:20]),
                            stream_a=list(words[20:56]), stream_b=list(words[56:92])))
    return dict(status=status, count=count, records=records)
