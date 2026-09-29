"""Timer probes reject unknown inputs and retain original rollover semantics."""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import native_timing as probe


class SyntheticTimingTests(unittest.TestCase):
    def test_unknown_image_and_invalid_stimuli_never_execute(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(probe, 'Isolated') as engine:
            image = Path(directory) / 'image'
            image.write_bytes(b'unknown')
            with self.assertRaises(ValueError):
                probe.report(image)
            for value in (-1, 2**32, True, 1.5):
                with self.assertRaises(ValueError):
                    probe.delay_probe(b'unknown', value, 0)
            with self.assertRaises(ValueError):
                probe.increment_probe(b'unknown', 'audio_compare_advance', 65536)
            with self.assertRaises(ValueError):
                probe.register_probe(b'unknown', 'unreviewed')
            engine.assert_not_called()

    def test_changed_source_invalidates_report(self):
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
                    return {'image_sha256': initial}
                with patch.object(probe, '_report', side_effect=evaluate), \
                        patch.object(probe, 'tool_hashes', side_effect=[{'t':'before'}, {'t':'after' if change=='tool' else 'before'}]), \
                        patch.object(probe, 'revision', side_effect=['before', 'after' if change=='revision' else 'before']):
                    if change:
                        with self.assertRaisesRegex(ValueError, 'changed'):
                            probe.report(image)
                    else:
                        self.assertTrue(probe.report(image)['source_unchanged'])


IMAGE = os.environ.get('IC7300_TEST_IMAGE')
@unittest.skipUnless(IMAGE and importlib.util.find_spec('unicorn'), 'Opt-in pinned image and Unicorn required')
class FirmwareTimingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = probe.report(Path(IMAGE))

    def test_delay_predicate_uses_32_ticks_per_microsecond_without_writes(self):
        for row in self.result['delay_cases']:
            self.assertEqual(row['threshold'], 32*row['microseconds'])
            self.assertEqual(row['r0'], int(row['counter'] >= 32*row['microseconds']))
            self.assertEqual(row['writes'], 0)

    def test_timers_have_different_modes_and_delay_is_stopped(self):
        sequences = self.result['register_sequences']
        def writes(name):
            return [(int(w['address'],16), w['size'], w['value']) for w in sequences[name]['writes']]
        self.assertEqual(writes('scheduler_timer_setup'), [
            (probe.CLOCK_GATE,1,0xfd), (probe.OSTM0+0x18,1,1),
            (probe.OSTM0+0x20,1,1), (probe.OSTM0,4,32000), (probe.OSTM0+0x14,1,1)])
        self.assertEqual(sequences['scheduler_timer_setup']['r0'],134)
        self.assertEqual(writes('delay_timer_setup'), [
            (probe.CLOCK_GATE,1,0xfe), (probe.OSTM1+0x18,1,1), (probe.OSTM1+0x20,1,2)])
        self.assertEqual(writes('delay_timer_start'), [(probe.OSTM1+0x14,1,1)])
        self.assertEqual(writes('delay_timer_stop'), [(probe.OSTM1+0x18,1,1)])

    def test_counter_rollovers_are_not_saturating_or_epoch_extended(self):
        for row in self.result['scheduler_increments']:
            self.assertEqual(row['after'], (row['before']+1) % 2**32)
        for row in self.result['compare_increments']:
            self.assertEqual(row['after'], (row['before']+8000) % 2**16)


if __name__ == '__main__':
    unittest.main()
