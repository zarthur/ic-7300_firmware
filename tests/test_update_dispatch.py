"""Synthetic provenance contracts and opt-in original update dispatch evidence."""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import update_dispatch as probe


class SyntheticDispatchTests(unittest.TestCase):
    def test_unknown_image_never_reaches_original_dispatch(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / '7300_142.dat'
            image.write_bytes(b'unknown image')
            with patch.object(probe, 'dispatch') as execute:
                with self.assertRaises(ValueError):
                    probe.report(image)
                execute.assert_not_called()

    def test_unreviewed_command_refused_before_engine(self):
        with patch.object(probe, 'engine') as engine:
            with self.assertRaisesRegex(ValueError, 'Unreviewed'):
                probe.dispatch(b'', 40)
            engine.assert_not_called()

    def test_ui_probe_refuses_unknown_application_and_unreviewed_state(self):
        with patch.object(probe, 'engine') as engine:
            with self.assertRaisesRegex(ValueError, 'exact v1.42'):
                probe.ui_transition(b'unknown application', 0x35, 0, 0)
            with self.assertRaisesRegex(ValueError, 'Unreviewed UI stimulus'):
                probe.ui_transition(b'unknown application', 0x3b, 2, 0)
            engine.assert_not_called()

    def test_mutation_prevents_successful_evidence(self):
        for change in ('image', 'restored_image', 'source', 'revision', None):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                image = Path(directory) / 'image'
                image.write_bytes(b'initial')
                initial_hash = probe.digest(image.read_bytes())
                def evaluate(path):
                    if change in ('image', 'restored_image'):
                        image.write_bytes(b'changed')
                        if change == 'restored_image':
                            image.write_bytes(b'initial')
                    return dict(image_sha256=initial_hash)
                with patch.object(probe, '_report', side_effect=evaluate), \
                        patch.object(probe, 'tool_hashes', side_effect=[{'tool': 'before'},
                            {'tool': 'after' if change == 'source' else 'before'}]), \
                        patch.object(probe, 'revision', side_effect=['before',
                            'after' if change == 'revision' else 'before']):
                    if change:
                        with self.assertRaisesRegex(ValueError, 'changed'):
                            probe.report(image)
                    else:
                        self.assertTrue(probe.report(image)['source_unchanged'])


IMAGE = os.environ.get('IC7300_TEST_IMAGE')
@unittest.skipUnless(IMAGE and importlib.util.find_spec('unicorn'), 'Opt-in pinned source and Unicorn required')
class FirmwareDispatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = probe.report(Path(IMAGE))

    def test_matching_identifiers_pass_but_do_not_establish_reinstallation(self):
        rows = self.evidence['header_cases']
        self.assertTrue(rows['equal']['accepted'])
        self.assertEqual(rows['equal']['component_change_flags'], [0, 0, 0])
        for index in range(3):
            row = rows[f'only_component_{index}_different']
            self.assertTrue(row['accepted'])
            self.assertEqual(row['component_change_flags'], [int(i == index) for i in range(3)])
        payload = self.evidence['equal_component_payload']
        self.assertTrue(payload['accepted'])
        self.assertEqual(len(payload['finalized_md5']), 1)
        self.assertFalse(self.evidence['same_version_reinstall_proven'])

    def test_checks_and_update_have_separate_dispatch_commands(self):
        cases = self.evidence['dispatch_cases']
        self.assertEqual({key: value['callee'] for key, value in cases.items()},
                         {'38': '0x200253f4', '39': '0x20025650', '11': '0x20025ae4'})
        self.assertTrue(all(value['reached'] and not value['callee_executed'] for value in cases.values()))

    def test_local_ui_completion_and_handshake_gates_do_not_claim_normal_entry(self):
        cases = {(row['initial_ui_state'], row['initial_handshake'], row['initial_command']): row
                 for row in self.evidence['ui_transition_cases']}
        self.assertEqual(len(cases), 6)
        self.assertEqual(cases[('0x35', 0, 0)]['stop']['pc'], '0x20022f78')
        self.assertEqual(cases[('0x39', 0, 0)]['stop']['pc'], '0x20059090')
        self.assertEqual(cases[('0x3a', 0, 0)]['final_ui_state'], '0x3b')
        self.assertEqual(cases[('0x3a', 0, 39)]['final_ui_state'], '0x3a')
        self.assertEqual(cases[('0x3b', 0, 0)]['stop']['reason'], 'returned')
        self.assertEqual(cases[('0x3b', 1, 0)]['stop']['pc'], '0x20022fc0')
        for row in cases.values():
            self.assertEqual(row['final_command'], row['initial_command'])
            self.assertFalse(row['actual_ui_reachability_proven'])
            self.assertFalse(row['producer_executed'])
            self.assertLess(row['executed_instructions'], row['limits']['instructions'])


if __name__ == '__main__':
    unittest.main()
