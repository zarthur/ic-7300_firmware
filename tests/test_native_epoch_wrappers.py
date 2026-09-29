"""Preserve exact original prologues and masks at all observed boundaries."""
import importlib.util
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from emulate_platform import inputs
import native_epoch as epoch


class SyntheticEpochWrapperTests(unittest.TestCase):
    def test_rejects_unknown_image_and_invalid_state_before_execution(self):
        with self.assertRaisesRegex(ValueError, 'exact pinned'):
            epoch.entry_probe(b'unknown', 'stop', [(0, [0]*4)])
        for kind, fixtures in [('other', [(0, [0]*4)]), ('cold', []),
                               ('cold', [(1, [0]*4)]), ('cold', [(True, [0]*4)]),
                               ('cold', [(0, [0]*3)]), ('cold', [(0, [0, 0, 0, -1])])]:
            with self.assertRaises(ValueError): epoch.entry_probe(b'unknown', kind, fixtures)


IMAGE = os.environ.get('IC7300_TEST_IMAGE')
@unittest.skipUnless(IMAGE and importlib.util.find_spec('unicorn'), 'Pinned image and Unicorn required')
class FirmwareEpochWrapperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): _, _, cls.app, _ = inputs(Path(IMAGE))

    def test_all_boundary_prologues_preserve_masks_flags_and_registers(self):
        fixtures = [(flags | mask, state)
                    for flags in (0, 0x80000000, 0x40000000, 0x20000000, 0x10000000, 0xf80f0000)
                    for mask in (0, 0x40, 0x80, 0xc0)
                    for state in ((0, 0, 0, 0), (37, 2, 0, 7), (0xffffffff, 1, 0, 7), (37, 2, 1, 7))]
        for reason, kind in enumerate(epoch.SITES, 1):
            for row in epoch.entry_probe(self.app, kind, fixtures):
                count, previous_reason, exhausted, reserved = row['before']
                if exhausted:
                    self.assertEqual(row['after'], row['before'])
                    self.assertEqual(row['writes'], [])
                elif count == 0xffffffff:
                    self.assertEqual(row['after'], [count, previous_reason, 1, reserved])
                    self.assertEqual(row['writes'], [(8, 4)])
                else:
                    self.assertEqual(row['after'], [count+1, reason, 0, reserved])
                    self.assertEqual(row['writes'], [(4, 4), (0, 4)])


if __name__ == '__main__': unittest.main()
