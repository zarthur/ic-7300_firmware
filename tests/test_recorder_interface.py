"""Guardrail tests and opt-in original stored-audio format trials."""
import importlib.util
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import recorder_interface as probe


class SyntheticRecorderTests(unittest.TestCase):
    def test_unknown_image_never_reaches_original_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / 'image.dat'
            image.write_bytes(b'not a supported image')
            with patch.object(probe, 'format_probe') as execute:
                with self.assertRaises(ValueError):
                    probe.report(image)
                execute.assert_not_called()

    def test_unknown_app_or_malformed_stimulus_refused_before_engine(self):
        blob = probe.format_cases()['pcm_mono_8k16']
        with patch.object(probe, 'engine') as engine:
            with self.assertRaisesRegex(ValueError, 'exact pinned'):
                probe.format_probe(b'unknown', blob)
            for invalid in (b'', blob[:-1], blob + b'A', bytearray(blob), None):
                with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, '20 synthetic'):
                    probe.format_probe(b'unknown', invalid)
            engine.assert_not_called()

    def test_mutation_prevents_successful_evidence(self):
        for change in ('image', 'restored_image', 'tool', 'revision', None):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                image = Path(directory) / 'image'
                image.write_bytes(b'initial')
                initial = probe.digest(image.read_bytes())
                def evaluate(path):
                    if change in ('image', 'restored_image'):
                        path.write_bytes(b'changed')
                        if change == 'restored_image':
                            path.write_bytes(b'initial')
                    return dict(image_sha256=initial)
                with patch.object(probe, '_report', side_effect=evaluate), \
                        patch.object(probe, 'tool_hashes', side_effect=[{'tool': 'before'},
                            {'tool': 'after' if change == 'tool' else 'before'}]), \
                        patch.object(probe, 'revision', side_effect=['before',
                            'after' if change == 'revision' else 'before']):
                    if change:
                        with self.assertRaisesRegex(ValueError, 'changed'):
                            probe.report(image)
                    else:
                        self.assertTrue(probe.report(image)['source_unchanged'])

    @unittest.skipUnless(importlib.util.find_spec('unicorn'), 'Pinned Unicorn required')
    def test_instruction_and_data_bounds_reject_synthetic_escape(self):
        # Original synthetic ARM snippets exercise the harness, not vendor code.
        # r0=one-byte output; r1=20-byte source; r2 begins zero in the engine.
        cases = [
            ((0xe5c02001, 0xe12fff1e), 'outside exact bounds'),  # strb r2,[r0,#1]
            ((0xe5912014, 0xe12fff1e), 'outside exact bounds'),  # ldr r2,[r1,#20]
            ((0xeafffffe,), 'did not return'),                 # b .
            ((0xe280f004,), 'Unreviewed'),                     # add pc,r0,#4
        ]
        blob = probe.format_cases()['pcm_mono_8k16']
        for words, message in cases:
            app = bytes(probe.FORMAT_ENTRY - probe.APP_BASE) + struct.pack('<' + 'I' * len(words), *words)
            with self.subTest(message=message), patch.object(probe, 'APPLICATION_SHA256', probe.digest(app)):
                # The indirect jump targets non-executable private output, so it
                # may fail at the memory protection boundary before the code hook.
                pattern = 'Unreviewed|emulation stopped' if message == 'Unreviewed' else message
                with self.assertRaisesRegex(ValueError, pattern):
                    probe.format_probe(app, blob)


IMAGE = os.environ.get('IC7300_TEST_IMAGE')
@unittest.skipUnless(IMAGE and importlib.util.find_spec('unicorn'), 'Opt-in pinned image and Unicorn required')
class FirmwareRecorderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = probe.report(Path(IMAGE))

    def test_format_matrix_and_early_output_side_effect(self):
        cases = self.result['format_cases']
        accepted = {name for name, result in cases.items() if result['return_code'] == 1}
        self.assertEqual(accepted, {'pcm_mono_8k16', 'size_18'})
        for name, row in cases.items():
            self.assertLess(row['instruction_count'], 500)
            self.assertTrue(row['original_helpers_executed'])
            self.assertTrue(all(r['offset'] + r['size'] <= 20 for r in row['source_reads']))
            self.assertTrue(all(w['offset'] == 0 and w['size'] == 1 for w in row['output_writes']))
        # Later validation failure does not undo the earlier mode-byte store.
        for name in ('byte_rate_wrong', 'block_wrong', 'bits_8'):
            self.assertEqual(cases[name]['return_code'], 0)
            self.assertEqual(cases[name]['output_byte'], 0)
        self.assertEqual(cases['rate_12k']['output_byte'], 0xa5)
        self.assertFalse(self.result['native_capture_interface_established'])

    def test_static_wrappers_share_file_scratch_not_proven_live_pcm(self):
        flows = self.result['bounded_static_flows']
        expected = {'metadata_file_wrapper': '0x20068788', 'format_file_wrapper': '0x20068d04'}
        for name, target in expected.items():
            row = flows[name]
            calls = {edge['target'] for edge in row['edges'] if edge['kind'] == 'call'}
            self.assertIn(target, calls)
            self.assertIn('0x20068920', calls)
            self.assertIn('0x203fcbc6', {item['value'] for item in row['literal_loads']})
            self.assertEqual(row['unresolved_exits'], [])


if __name__ == '__main__':
    unittest.main()
