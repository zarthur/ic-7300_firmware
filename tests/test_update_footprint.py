"""Footprint summaries must not equate small payloads with small erase ranges."""
from pathlib import Path
import sys
import os
import importlib.util
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from update_footprint import report, summarize_transfer


class SyntheticFootprintTests(unittest.TestCase):
    def result(self, events, size=1):
        return dict(events=events, file_bytes_read=size, changed_flag=1,
                    return_code=0, interrupted=None, flash_payload_equal=True)

    def test_one_byte_payload_retains_whole_erase_unit_exposure(self):
        summary = summarize_transfer(self.result([
            dict(operation='compare', offset=0x10000, length=0x10000, different=True),
            dict(operation='erase', offset=0x10000, length=0x10000),
            dict(operation='program', offset=0x10000, length=0x10000)]))
        self.assertEqual(summary['input_bytes'], 1)
        self.assertEqual(summary['erase_bytes'], 65536)
        self.assertEqual(summary['program_ranges'], [dict(offset=65536, length=65536)])

    def test_equal_adjacent_unit_is_compared_but_not_reported_as_written(self):
        summary = summarize_transfer(self.result([
            dict(operation='compare', offset=65536, length=65536, different=True),
            dict(operation='erase', offset=65536, length=65536),
            dict(operation='program', offset=65536, length=65536),
            dict(operation='compare', offset=131072, length=65536, different=False)], size=131072))
        self.assertEqual(len(summary['compared_units']), 2)
        self.assertEqual(summary['erase_ranges'], [dict(offset=65536, length=65536)])
        self.assertEqual(summary['program_bytes'], 65536)

    def test_interrupted_erase_does_not_invent_program_or_success(self):
        result = self.result([dict(operation='erase', offset=0, length=65536)])
        result.update(return_code=None, interrupted='after_erase', flash_payload_equal=False)
        summary = summarize_transfer(result)
        self.assertIsNone(summary['return_code'])
        self.assertEqual(summary['interrupted'], 'after_erase')
        self.assertEqual(summary['erase_bytes'], 65536)
        self.assertEqual(summary['program_bytes'], 0)
        self.assertFalse(summary['modeled_payload_equal'])

    def test_unknown_image_is_refused_before_emulation(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / '7300_142.dat'
            image.write_bytes(b'not an authorized image')
            with self.assertRaises(ValueError):
                report(image)

    def test_source_change_cannot_produce_a_provenance_report(self):
        with patch('update_footprint.tool_hashes', side_effect=[{'helper': 'before'}, {'helper': 'after'}]), \
             patch('update_footprint.revision', return_value={'commit': 'fixed', 'dirty': False}), \
             patch('update_footprint._report', return_value={'candidate_exists': False}):
            with self.assertRaisesRegex(ValueError, 'Source changed'):
                report(Path('unused-fixture'))


IMAGE = os.environ.get('IC7300_TEST_IMAGE')
@unittest.skipUnless(IMAGE and importlib.util.find_spec('unicorn'), 'Opt-in pinned source and Unicorn required')
class FirmwareFootprintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = report(Path(IMAGE))

    def test_original_transfer_skips_equal_boot_but_writes_full_differing_unit(self):
        scenarios = self.evidence['transfer_scenarios']
        equal = scenarios['official_boot:equal=True']['footprint']
        self.assertEqual((equal['changed_flag'], equal['erase_bytes'], equal['program_bytes']), (0, 0, 0))
        different = scenarios['official_boot:equal=False']['footprint']
        self.assertEqual((different['changed_flag'], different['erase_bytes'], different['program_bytes']), (1, 65536, 65536))
        for case in ('one_byte_change_two_units', 'one_byte_partial_unit'):
            footprint = scenarios[case]['footprint']
            self.assertEqual(footprint['erase_bytes'], 65536)
            self.assertEqual(footprint['program_bytes'], 65536)
            self.assertEqual(footprint['return_code'], 0)
        self.assertFalse(self.evidence['candidate_exists'])

    def test_original_activation_order_depends_on_boot_change(self):
        for selector in (0, 1):
            for changed in (False, True):
                events = self.evidence['main_caller_scenarios'][f'selector={selector}:boot_changed={changed}']['events']
                operations = [event['operation'] for event in events]
                self.assertEqual(operations.index('activation_call') < operations.index('modeled_md5_finalize'), changed)
            events = self.evidence['selector_scenarios'][str(selector)]['events']
            erase = next(event for event in events if event['operation'] == 'modeled_block_erase')
            program = next(event for event in events if event['operation'] == 'modeled_record_program')
            self.assertEqual((erase['offset'], erase['length']), (0x7f0000, 65536))
            self.assertEqual((program['offset'], program['requested']), (0x7f0000, 16))


if __name__ == '__main__':
    unittest.main()
