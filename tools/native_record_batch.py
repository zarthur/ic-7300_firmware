#!/usr/bin/env python3
"""Pinned-image recorder selection/copy probes; stops before write submission."""
import struct

from emulate_platform import STACK
from native_receive import Isolated, COPY, RING, INDICES

META = 0x203da6c0
FLAGS = 0x2039027c
TAGS = 0x203902a2
BATCH = 0x205072e0
START = 0x2004943c  # Original pending-command check has already passed.
SUBMIT = 0x200497f0
NO_SUBMIT = 0x20049840


class BatchTrial:
    """Original selection and copy, with an explicit stable recorder prestate.

    No task, filesystem, UI-setting translation or concurrent producer is modeled.
    Each call supplies the original saved producer snapshot. A successful submit
    is NOT invented: advance() executes only the original post-submit bookkeeping.
    """
    def __init__(self, app, payloads, index=0, tags=None, current_tag=0x5a,
                 remaining=0, first_header=False, paused=False):
        if (type(index) is not int or not 0 <= index < 1914 or
                not isinstance(payloads, (list, tuple)) or not 1 <= len(payloads) < 1914 or
                any(not isinstance(p, bytes) or len(p) != 216 for p in payloads) or
                type(remaining) is not int or not 0 <= remaining <= 216 or
                type(current_tag) is not int or not 0 <= current_tag <= 255):
            raise ValueError('Invalid recorder fixture')
        if tags is None:
            tags = [current_tag] * len(payloads)
        if len(tags) != len(payloads) or any(type(t) is not int or not 0 <= t <= 255 for t in tags):
            raise ValueError('Invalid recorder tags')
        self.h = h = Isolated(app, [(START, SUBMIT), (0x200497f4, 0x20049838),
                                  (0x20048a24, 0x20048a74), (0x20047b6c, 0x20047bbc), COPY],
                             [(RING, 1914*220), (INDICES, 0xdc), (META, 0x2ed),
                              (FLAGS, 0x14), (TAGS, 3), (0x203902a5, 3), (0x20390317, 1), (BATCH-4, 4104)])
        h.uc.mem_write(META, bytes(0x2ed))
        h.uc.mem_write(META+0x2d4, b'\x00'+b'\xff'*24)
        h.uc.mem_write(META+0x18, bytes([current_tag]))
        h.uc.mem_write(META+0x32, b'\xff\xff')
        h.uc.mem_write(META+0x10, struct.pack('<IB', remaining, int(first_header)))
        h.uc.mem_write(FLAGS, bytes(0x14))
        h.uc.mem_write(FLAGS+0x11, bytes([int(paused)]))
        h.uc.mem_write(TAGS, bytes([0, 0, current_tag]))
        h.uc.mem_write(0x203902a5, bytes(3))
        h.uc.mem_write(0x20390317, b'\x00')
        h.uc.mem_write(INDICES+0xd8, struct.pack('<H', index))
        for i, (payload, tag) in enumerate(zip(payloads, tags)):
            h.uc.mem_write(RING+((index+i) % 1914)*220, bytes([0, tag, 1, 0])+payload)
        self.producer = (index+len(payloads)) % 1914
        self.pending = False
        # Stop before the epilogue when selection produces no write request.
        def no_submit(uc, address, size, unused):
            if address == NO_SUBMIT:
                uc.emu_stop()
        h.uc.hook_add(h.u.UC_HOOK_CODE, no_submit, begin=NO_SUBMIT, end=NO_SUBMIT)
        # Include the stop instruction in the guard, but never execute it.
        h.ranges.append((NO_SUBMIT, NO_SUBMIT+4))

    def select(self):
        if self.pending:
            raise ValueError('Post-submit boundary must be acknowledged first')
        h = self.h
        h.uc.mem_write(BATCH-4, b'\xa5'*4104)
        h.uc.mem_write(STACK+0xf000+0x18, struct.pack('<I', self.producer))
        h.uc.mem_write(STACK+0xf000+0x10, bytes(4))
        # Isolated.run expects one end address. NO_SUBMIT is an intentional second
        # boundary, so use the same instruction/time budget and check both PCs.
        h.uc.reg_write(h.a.UC_ARM_REG_SP, STACK+0xf000)
        before = h.count
        h.uc.emu_start(START, SUBMIT, timeout=1000000, count=50000)
        pc = h.uc.reg_read(h.a.UC_ARM_REG_PC)
        if pc not in (SUBMIT, NO_SUBMIT):
            raise ValueError('Recorder failed to reach a reviewed boundary')
        length = h.uc.reg_read(h.a.UC_ARM_REG_R1) if pc == SUBMIT else 0
        if not 0 <= length <= 4096:
            raise ValueError('Recorder batch exceeded output bounds')
        if pc == SUBMIT and h.uc.reg_read(h.a.UC_ARM_REG_R0) != BATCH:
            raise ValueError('Unexpected write buffer')
        if (bytes(h.uc.mem_read(BATCH-4, 4)) != b'\xa5'*4 or
                bytes(h.uc.mem_read(BATCH+length, 4100-length)) != b'\xa5'*(4100-length)):
            raise ValueError('Recorder changed bytes outside output')
        self.pending = pc == SUBMIT
        return {'payload': bytes(h.uc.mem_read(BATCH, length)),
                'instructions': h.count-before, 'submitted': self.pending,
                'consumer': struct.unpack('<H', h.uc.mem_read(INDICES+0xd8, 2))[0],
                'remaining': h.uc.reg_read(h.a.UC_ARM_REG_R9),
                'file_change': struct.unpack('<I', h.uc.mem_read(STACK+0xf000+0x10, 4))[0]}

    def advance(self):
        if not self.pending:
            raise ValueError('No write-submission boundary to advance')
        # Explicitly skip submission and asynchronous I/O; exercise only the
        # original tail that persists the partial-slot count for the next call.
        self.h.run(0x200497f4, stop=0x20049838)
        self.pending = False
