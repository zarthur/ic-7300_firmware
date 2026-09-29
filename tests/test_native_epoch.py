"""Execute boundary counting with strict writes and no simulated hardware."""
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from native_capture import build_core, ROOT, CODE, STATE
from emulate_platform import engine, RETURN, STACK


class EpochTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.code = build_core(ROOT/'prototype/native_receive/epoch.S')

    def execute(self, state, reason):
        uc, u, a = engine()
        uc.mem_map(CODE, 4096, u.UC_PROT_READ | u.UC_PROT_EXEC)
        uc.mem_write(CODE, self.code)
        uc.mem_map(STATE & ~4095, 4096)
        # Frozen capture/export stand-in shares this page. Any access outside
        # the exact live state fails, even though the emulator maps the page.
        before = b'\xa5'*4096
        uc.mem_write(STATE & ~4095, before)
        uc.mem_write(STATE, struct.pack('<4I', *state))
        accesses = []
        def memory(uc, access, address, size, value, unused):
            if not STATE <= address or address+size > STATE+16:
                raise AssertionError('Epoch accessed outside private live state')
            accesses.append((access, address-STATE, size))
        def code(uc, address, size, unused):
            if not CODE <= address or address+size > CODE+len(self.code):
                raise AssertionError('Epoch escaped core')
        uc.hook_add(u.UC_HOOK_MEM_READ | u.UC_HOOK_MEM_WRITE, memory)
        uc.hook_add(u.UC_HOOK_CODE, code)
        regs = [getattr(a, 'UC_ARM_REG_R'+str(i)) for i in range(4, 12)]
        for i, reg in enumerate(regs): uc.reg_write(reg, 0x12340000+i)
        uc.reg_write(a.UC_ARM_REG_R0, STATE)
        uc.reg_write(a.UC_ARM_REG_R1, reason)
        uc.reg_write(a.UC_ARM_REG_SP, STACK+0xf000)
        uc.reg_write(a.UC_ARM_REG_LR, RETURN)
        uc.emu_start(CODE, RETURN, count=40, timeout=1000000)
        self.assertEqual(uc.reg_read(a.UC_ARM_REG_PC), RETURN)
        self.assertEqual(uc.reg_read(a.UC_ARM_REG_SP), STACK+0xf000)
        self.assertEqual([uc.reg_read(r) for r in regs], [0x12340000+i for i in range(8)])
        page = bytes(uc.mem_read(STATE & ~4095, 4096))
        self.assertEqual(page[:16], before[:16])
        self.assertEqual(page[32:], before[32:])
        result = struct.unpack('<4I', uc.mem_read(STATE, 16))
        writes = [(offset, size) for access, offset, size in accesses if access == u.UC_MEM_WRITE]
        return uc.reg_read(a.UC_ARM_REG_R0), result, writes

    def test_cold_and_shared_restart_never_reuse_an_epoch(self):
        state = (0, 0, 0, 0xdeadbeef)
        for epoch, reason in enumerate((1, 4, 2, 3, 4, 3, 1), 1):
            result, state, writes = self.execute(state, reason)
            self.assertEqual(result, 1)
            self.assertEqual(state, (epoch, reason, 0, 0xdeadbeef))
            self.assertEqual(writes, [(4, 4), (0, 4)])

    def test_wrap_is_terminal_and_does_not_change_last_boundary(self):
        result, state, _ = self.execute((0xfffffffe, 1, 0, 7), 2)
        self.assertEqual((result, state), (1, (0xffffffff, 2, 0, 7)))
        result, state, writes = self.execute(state, 1)
        self.assertEqual((result, state, writes), (0, (0xffffffff, 2, 1, 7), [(8, 4)]))
        for reason in (1, 2, 0, 0xffffffff):
            self.assertEqual(self.execute(state, reason), (0, state, []))

    def test_invalid_reason_and_nonzero_exhaustion_fail_closed(self):
        for reason in (0, 5, 0xffffffff):
            self.assertEqual(self.execute((45, 2, 0, 9), reason),
                             (0, (45, 2, 1, 9), [(8, 4)]))
        for exhausted in (1, 2, 0xffffffff):
            state = (45, 2, exhausted, 9)
            self.assertEqual(self.execute(state, 1), (0, state, []))


if __name__ == '__main__': unittest.main()
