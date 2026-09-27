from pathlib import Path
import struct
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import platform_evidence as pe
try:
    import capstone
except ImportError:
    capstone = None


@unittest.skipIf(capstone is None, 'Optional pinned Capstone required')
class EvidenceTests(unittest.TestCase):
    def test_arm_literal_interworking_and_unknown_register(self):
        # ldr r0,[pc,#4]; blx r0; bx r1; literal Thumb target
        data = struct.pack('<4I', 0xe59f0004, 0xe12fff30, 0xe12fff11, 0x1021)
        result = pe.observe(data, 0x1000, 0x1000, 0x100c)
        first, second = result['edges']
        self.assertEqual((first['target'],first['target_mode']), ('0x1020','Thumb'))
        self.assertIsNone(second['target'])
        self.assertIsNone(second['target_mode'])

    def test_arm_direct_blx_and_thumb_branch(self):
        result = pe.observe(struct.pack('<I', 0xfa000000), 0x1000, 0x1000, 0x1004)
        self.assertEqual(result['edges'][0]['target_mode'], 'Thumb')
        result = pe.observe(bytes.fromhex('00e0'), 0x1000, 0x1000, 0x1002, 'Thumb')
        self.assertEqual(result['edges'][0]['target_mode'], 'Thumb')
        self.assertEqual(result['edges'][0]['target'], '0x1004')

    def test_thumb_cbz_uses_last_operand(self):
        result = pe.observe(bytes.fromhex('08b1'), 0x1000, 0x1000, 0x1002, 'Thumb')
        self.assertEqual(result['edges'][0]['target'], '0x1006')

    def test_bounds(self):
        with self.assertRaises(ValueError): pe.observe(bytes(4), 0, 0, 8)


if __name__ == '__main__': unittest.main()
