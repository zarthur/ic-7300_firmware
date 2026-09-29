"""Access guards and exact-image receive queue/layout experiments."""
import importlib.util
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import native_receive as probe


class SyntheticReceiveTests(unittest.TestCase):
    def test_unknown_image_cannot_execute(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / 'unknown.dat'
            image.write_bytes(b'unknown')
            with patch.object(probe, 'engine') as engine:
                with self.assertRaises(ValueError):
                    probe.report(image)
                with self.assertRaisesRegex(ValueError, 'exact pinned'):
                    probe.queue_probe(b'unknown', 0, 0, 'pop')
                engine.assert_not_called()

    def test_mutation_invalidates_evidence(self):
        for change in ('image', 'restored_image', 'tool', 'revision', None):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                image = Path(directory) / 'image'
                image.write_bytes(b'initial')
                original = probe.digest(image.read_bytes())
                def evaluate(path):
                    if change in ('image', 'restored_image'):
                        path.write_bytes(b'changed')
                        if change == 'restored_image':
                            path.write_bytes(b'initial')
                    return {'image_sha256': original}
                with patch.object(probe, '_report', side_effect=evaluate), \
                        patch.object(probe, 'tool_hashes', side_effect=[{'t':'before'}, {'t':'after' if change=='tool' else 'before'}]), \
                        patch.object(probe, 'revision', side_effect=['before', 'after' if change=='revision' else 'before']):
                    if change:
                        with self.assertRaisesRegex(ValueError, 'changed'):
                            probe.report(image)
                    else:
                        self.assertTrue(probe.report(image)['source_unchanged'])

    def test_invalid_inputs_cannot_execute(self):
        with patch.object(probe, 'engine') as engine:
            for w, r, op in [(-1, 0, 'pop'), (0, 8, 'pop'), (True, 0, 'push'), (0, 0, 'clear')]:
                with self.assertRaises(ValueError):
                    probe.queue_probe(b'unknown', w, r, op)
            for mode, samples in [(5, b'12'), (0, b'1'), (0, b''), (0, bytes(4098))]:
                with self.assertRaises(ValueError):
                    probe.select_probe(b'unknown', mode, samples)
            with self.assertRaises(ValueError):
                probe.split_probe(b'unknown', 2, bytes(576))
            with self.assertRaises(ValueError):
                probe.publish_probe(b'unknown', 1914, 1, 0, bytes(216))
            engine.assert_not_called()

    @unittest.skipUnless(importlib.util.find_spec('unicorn'), 'Pinned Unicorn required')
    def test_bounds_and_execution_budget(self):
        # Original test instructions, not extracted firmware.
        cases = [
            ((0xe5c01001, 0xe12fff1e), 'outside exact bounds'), # strb r1,[r0,#1]
            ((0xe5901004, 0xe12fff1e), 'outside exact bounds'), # ldr r1,[r0,#4]
            ((0xeafffffe,), 'within limits'),                  # b .
            ((0xea000000, 0xe12fff1e, 0xe12fff1e), 'Unreviewed'),
        ]
        for words, message in cases:
            app = struct.pack('<'+'I'*len(words), *words)
            with self.subTest(message=message), patch.object(probe, 'APPLICATION_SHA256', probe.digest(app)):
                harness = probe.Isolated(app, [(probe.APP_BASE, probe.APP_BASE+4)], [(probe.OUTPUT, 1)])
                with self.assertRaisesRegex(ValueError, message):
                    harness.run(probe.APP_BASE, (probe.OUTPUT,), budget=100)


IMAGE = os.environ.get('IC7300_TEST_IMAGE')
@unittest.skipUnless(IMAGE and importlib.util.find_spec('unicorn'), 'Opt-in pinned image and Unicorn required')
class FirmwareReceiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = probe.report(Path(IMAGE))
        _, _, cls.app, _ = probe.inputs(Path(IMAGE))

    def test_original_recording_header_writer(self):
        row = self.result['record_format_writer']
        self.assertEqual(row['r0'], 24)
        self.assertEqual(bytes.fromhex(row['chunk_hex'])[:4], b'fmt ')
        self.assertEqual([row[k] for k in ('size','encoding','channels','rate','byte_rate','block_align','bits')],
                         [16,1,1,8000,16000,2,16])

    def test_every_queue_state_and_wrap(self):
        initial = bytes((i*17+3)&255 for i in range(576))
        cases = self.result['queue_cases']
        for w in range(8):
            for r in range(8):
                with self.subTest(write=w, read=r):
                    count = cases[f'count_{w}_{r}']
                    self.assertEqual(count['r0'], (w-r)%8)
                    self.assertEqual(count['changed_queue_offsets'], [])
                    pop = cases[f'pop_{w}_{r}']
                    self.assertEqual(pop['write_index'], w)
                    self.assertEqual(pop['read_index'], (r+1)%8 if w!=r else r)
                    self.assertEqual(bytes.fromhex(pop['output_hex']), initial[r*72:(r+1)*72] if w!=r else bytes(72))
                    self.assertEqual(pop['changed_queue_offsets'], [577] if w!=r else [])
                    push = cases[f'push_{w}_{r}']
                    self.assertEqual(push['write_index'], (w+1)%8)
                    self.assertEqual(push['read_index'], r)
                    self.assertEqual(bytes.fromhex(push['slot_hex']), bytes(range(72)))
                    self.assertTrue(set(push['changed_queue_offsets']) <= set(range(w*72,(w+1)*72)) | {576})
                    # There is no full-queue guard: writing the eighth block
                    # makes write==read, indistinguishable from empty.
                    if (w-r)%8 == 7:
                        self.assertEqual(push['write_index'], push['read_index'])

    def test_selection_preserves_signed_bit_patterns(self):
        samples = [-32768+i*1800 for i in range(36)]
        for mode, stride in enumerate((6,4,3,2,1)):
            selected = samples[::stride]
            result = self.result['sample_selection'][str(mode)]
            self.assertEqual(bytes.fromhex(result['output_hex']), struct.pack('<'+'h'*len(selected), *selected))
        # Nonmultiple count tests whether this is ceil or floor selection.
        result = probe.select_probe(self.app, 0, struct.pack('<7h', -32768,-1,0,1,2,3,32767))
        self.assertEqual(bytes.fromhex(result['output_hex']), struct.pack('<2h',-32768,32767))

    def test_dma_banks_extract_only_upper_halfwords_of_first_two_words(self):
        expected_a = struct.pack('<36H', *[(i*1700)&65535 for i in range(36)])
        expected_b = struct.pack('<36H', *[(65535-i*1300)&65535 for i in range(36)])
        for result in self.result['dma_split'].values():
            self.assertEqual(bytes.fromhex(result['stream_a_hex']), expected_a)
            self.assertEqual(bytes.fromhex(result['stream_b_hex']), expected_b)

    def test_publication_wrap_disable_and_next_slot_invalidation(self):
        for index in (0, 1913):
            for enabled in (0, 1):
                result = self.result['record_publication'][f'{index}_{enabled}']
                self.assertEqual(result['fill_after'], 0)
                self.assertEqual(result['index_after'], (index+1)%1914 if enabled else index)
                self.assertEqual(result['changed_slots'], sorted([index,(index+1)%1914]) if enabled else [])
                expected = b'\xa5\x5a\x01\xa5'+bytes(range(216)) if enabled else b'\xa5'*220
                self.assertEqual(bytes.fromhex(result['published_hex']), expected)
                self.assertEqual(bytes.fromhex(result['next_slot_hex']), bytes(220) if enabled else b'\xa5'*220)


if __name__ == '__main__':
    unittest.main()
