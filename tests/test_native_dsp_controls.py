"""Original CPU gate slices; physical radio state is not supplied by these tests."""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import native_dsp_controls as controls
from emulate_platform import inputs


class SyntheticDspControlTests(unittest.TestCase):
    def test_reject_unknown_image_and_invalid_fixtures(self):
        with self.assertRaisesRegex(ValueError, 'exact pinned'):
            controls.gate_probe(b'unknown', [(0, 0, 0, 0, 0)])
        with self.assertRaisesRegex(ValueError, 'exact pinned'):
            controls.publication_probe(b'unknown', [0])
        with self.assertRaisesRegex(ValueError, 'exact pinned'):
            controls.level_probe(b'unknown', [(0, 0, 0, 0, 0)])
        with self.assertRaisesRegex(ValueError, 'exact pinned'):
            controls.level_settings_probe(b'unknown')
        with self.assertRaisesRegex(ValueError, 'exact pinned'):
            controls.modulation_settings_probe(b'unknown')
        for cases in ([], [(0, 0)], [(0, 0, 0, False, 0)], [(0, 256, 0, 0, 0)], [(0, 0, -1, 0, 0)]):
            with self.assertRaises(ValueError): controls.gate_probe(b'unknown', cases)
            with self.assertRaises(ValueError): controls.level_probe(b'unknown', cases)
        for values in ([], [True], [-1], [256], ['0']):
            with self.assertRaises(ValueError): controls.publication_probe(b'unknown', values)

    def test_source_mutation_invalidates_report(self):
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder)/'image'; image.write_bytes(b'input')
            with patch.object(controls, '_report', return_value={'image_sha256': controls.digest(b'input')}), \
                 patch.object(controls, 'tool_hashes', side_effect=[{'t': 'before'}, {'t': 'after'}]):
                with self.assertRaisesRegex(ValueError, 'changed'): controls.report(image)


IMAGE = os.environ.get('IC7300_TEST_IMAGE')
@unittest.skipUnless(IMAGE and importlib.util.find_spec('unicorn'), 'Pinned image and Unicorn required')
class FirmwareDspControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): _, _, cls.app, _ = inputs(Path(IMAGE))

    def test_refresh_consumes_latch_and_prefix_uses_cached_flags(self):
        cases = [(p, s, o, a, b) for p in (0, 1, 255) for s in range(256)
                 for o in (0, 32, 255) for a, b in ((0, 255), (255, 0))]
        for row in controls.gate_probe(self.app, cases):
            s, o = row['state'], row['other']
            flags = [(s >> 4) & 1, (s >> 6) & 1, 1 & ~(o >> 5)] if row['pending'] else row['previous_flags']
            self.assertEqual(row['refreshed_flags'], flags, row)
            expected = (int(bool(flags[0])) << 23) | (int(bool(flags[1])) << 22) | ((s & 4) << 2)
            self.assertEqual(row['command_prefix'], expected, row)

    def test_nonzero_cached_flags_are_boolean_not_low_bit_only(self):
        cases = [(0, s, 0, a, b) for s in (0, 4) for a in range(256) for b in (0, 128)]
        for row in controls.gate_probe(self.app, cases):
            a, b, _ = row['previous_flags']
            self.assertEqual(row['command_prefix'], (bool(a) << 23) | (bool(b) << 22) | ((row['state'] & 4) << 2))

    def test_publication_preserves_all_byte_values(self):
        for row in controls.publication_probe(self.app, list(range(256))):
            self.assertEqual(row['input'], row['published'])

    def test_acc_usb_setting_labels(self):
        self.assertEqual(controls.level_settings_probe(self.app), [
            {'index': 76, 'label': 'ACC/USB Output Select', 'address': 0x203de518},
            {'index': 77, 'label': 'ACC/USB AF Output Level', 'address': 0x203de519},
            {'index': 80, 'label': 'ACC/USB IF Output Level', 'address': 0x203de51c}])

    def test_acc_usb_interpolation_selection_and_command_fields(self):
        cases = [(s, x if s == 0 else other, other if s == 0 else x, 0xa5, 0x5a)
                 for s in (0, 1, 128, 255) for x in range(256) for other in (0, 128, 255)]
        cases += [(s, 0, 255, s, 255-s) for s in range(256)]
        for row in controls.level_probe(self.app, cases):
            x = row['if_level'] if row['output_select'] else row['af_level']
            expected = x*100//128 if x < 128 else 100+(x-128)*50//127
            self.assertEqual(row['mapped_level'], expected, row)
            self.assertEqual(row['command'], 0x4a000000 | row['high_byte'] << 16 |
                             expected << 8 | row['low_byte'], row)

    def test_modulation_menu_options_and_original_source_predicate(self):
        rows = controls.modulation_settings_probe(self.app)
        self.assertEqual([(r['index'], r['label'], r['address']) for r in rows], [
            (83, 'DATA OFF MOD', 0x203de51f), (84, 'DATA MOD', 0x203de520)])
        for row in rows:
            self.assertEqual(row['options'], [
                {'value': 0, 'label': 'MIC', 'source_predicate': 1},
                {'value': 1, 'label': 'ACC', 'source_predicate': 0},
                {'value': 2, 'label': 'MIC,ACC', 'source_predicate': 1},
                {'value': 3, 'label': 'USB', 'source_predicate': 0},
                {'value': 4, 'label': 'MIC,USB', 'source_predicate': 1}])
