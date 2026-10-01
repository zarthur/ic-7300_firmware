from pathlib import Path
import os
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import native_playback_map as playback
from emulate_platform import inputs


IMAGE = os.environ.get('IC7300_TEST_IMAGE')
ROOT = Path(__file__).resolve().parents[1]


class PlaybackMapInputTests(unittest.TestCase):
    def test_rejects_unknown_application(self):
        with self.assertRaisesRegex(ValueError, 'exact pinned'):
            playback.verify_image_words(b'unknown')

    def test_rejects_bad_ring_indices(self):
        with self.assertRaisesRegex(ValueError, 'indices'):
            playback.ring_sequence_probe(b'unknown', 'A', 13, 0, [('pop', None)])


@unittest.skipUnless(IMAGE and Path(IMAGE).is_file(), 'Pinned original IC-7300 image required')
class PinnedPlaybackMapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = inputs(Path(IMAGE))[2]

    def test_static_worker_and_queue_words(self):
        report = playback.static_summary(self.app)
        self.assertEqual(report['application_sha256'], playback.APPLICATION_SHA256)
        self.assertGreaterEqual(len(report['verified_words']), 20)
        self.assertEqual(report['rings']['A']['base'], '0x203fbcc0')
        self.assertEqual(report['rings']['B']['base'], '0x203fbd5e')
        self.assertIn('not proven to belong', report['bounded_findings'][2])
        self.assertIn('does not prove DMA drain', report['bounded_findings'][5])

    def test_push_pop_wraps_for_both_rings(self):
        payload = bytes.fromhex('00ff7f800102fe0304050607')
        for name, ring in playback.RINGS.items():
            last = ring['slots'] - 1
            report = playback.ring_sequence_probe(
                self.app, name, last, last, [('push', payload), ('pop', None)])
            self.assertEqual((report['write_index'], report['read_index']), (0, 0))
            self.assertEqual(report['actions'][1]['output_hex'], payload.hex())

    def test_empty_pop_zeroes_output_without_moving_read_cursor(self):
        for name in playback.RINGS:
            report = playback.ring_sequence_probe(self.app, name, 3, 3, [('pop', None)])
            self.assertEqual(report['actions'][0]['output_hex'], '00' * 12)
            self.assertEqual(report['read_index'], 3)

    def test_flush_resets_only_cursors(self):
        payload = bytes(range(12))
        for name, ring in playback.RINGS.items():
            report = playback.ring_sequence_probe(
                self.app, name, 1, 0, [('push', payload), ('reset', None)])
            self.assertEqual((report['write_index'], report['read_index']), (0, 0))
            self.assertNotEqual(report['slot_region_after_hex'], '00' * (ring['slots'] * 12))
            self.assertEqual(report['actions'][0]['slot_region_hex'],
                             report['actions'][1]['slot_region_hex'])

    def test_cursor_lap_is_indistinguishable_from_empty(self):
        payload = bytes.fromhex('0102030405060708090a0b0c')
        for name, ring in playback.RINGS.items():
            actions = [('push', payload)] * ring['slots'] + [('pop', None)]
            report = playback.ring_sequence_probe(self.app, name, 0, 0, actions)
            self.assertEqual((report['write_index'], report['read_index']), (0, 0))
            self.assertEqual(report['actions'][-1]['output_hex'], '00' * 12)


if __name__ == '__main__':
    unittest.main()
