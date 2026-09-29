"""Original-instruction recorder control boundaries, not a DSP model."""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import native_recorder_controls as controls
from emulate_platform import inputs


class SyntheticRecorderControlTests(unittest.TestCase):
    def test_reject_unknown_image_and_invalid_fixtures(self):
        with self.assertRaisesRegex(ValueError, 'exact pinned'):
            controls.setting_probe(b'unknown', 287)
        with self.assertRaisesRegex(ValueError, 'exact pinned'):
            controls.route_probe(b'unknown', [(0, 0, 0)], [0]*6)
        for index in (True, 0, 65536):
            with self.assertRaises(ValueError): controls.setting_probe(b'unknown', index)
        for cases in ([], [(2, 0, 0)], [(0, -1, 0)], [(0, 0, 256)], [(False, 0, 0)], [(0, 0)]):
            with self.assertRaises(ValueError): controls.route_probe(b'unknown', cases, [0]*6)
        for samples in ([0]*5, [32768]*6, [-32769]*6, [True]*6):
            with self.assertRaises(ValueError): controls.route_probe(b'unknown', [(0, 0, 0)], samples)

    def test_source_mutation_invalidates_report(self):
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder)/'image'; image.write_bytes(b'input')
            with patch.object(controls, '_report', return_value={'image_sha256': controls.digest(b'input')}), \
                 patch.object(controls, 'tool_hashes', side_effect=[{'t': 'before'}, {'t': 'after'}]):
                with self.assertRaisesRegex(ValueError, 'changed'): controls.report(image)


IMAGE = os.environ.get('IC7300_TEST_IMAGE')
@unittest.skipUnless(IMAGE and importlib.util.find_spec('unicorn'), 'Pinned image and Unicorn required')
class FirmwareRecorderControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): _, _, cls.app, _ = inputs(Path(IMAGE))

    def test_original_selector_resolves_setting_records(self):
        expected = {35: '0x203de4ef', 287: '0x203de70a', 288: '0x203de70b',
                    289: '0x203de70c', 290: '0x203de70d'}
        for index, pointer in expected.items():
            row = controls.setting_probe(self.app, index)
            self.assertEqual(row['label'], controls.SETTINGS[index])
            self.assertEqual(row['value_pointer'], pointer)
            self.assertNotEqual(*row['label_pointers'])

    def test_all_tags_with_mute_copy_and_signed_gain_boundaries(self):
        samples = [-32768, -257, -1, 0, 1, 32767]
        cases = [(t, g, tag) for t in (0, 1) for g in (0, 1, 255) for tag in range(256)]
        for row in controls.route_probe(self.app, cases, samples):
            t, g, tag = row['tx_rec_audio'], row['gate_20390104'], row['tag']
            if tag == 2:
                expected = [0]*6
            elif tag in (6, 7):
                expected = [-23168, -181, 0, 0, 0, 23167]
            elif g or (t and tag in (3, 4, 5)):
                expected = samples
            else:
                expected = [0]*6
            self.assertEqual(row['output'], expected, (t, g, tag))
            self.assertEqual(row['copy_mode'], 3 if expected == [0]*6 else 5)
