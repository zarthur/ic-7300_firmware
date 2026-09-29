"""Exercise nested callbacks and discontinuities across actual ARM copies."""
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import native_capture_v2 as capture


class CaptureV2Tests(unittest.TestCase):
    def test_complete_capture_and_frozen_storage(self):
        trial = capture.CaptureTrial()
        for i in range(512):
            trial.call('begin')
            self.assertEqual(trial.call('finish'), 1)
        data = trial.storage()
        decoded = capture.decode_storage(data)
        self.assertEqual((decoded['status'], decoded['count']), (2, 512))
        for row in decoded['records']:
            self.assertEqual(row['flags'], 0)
            self.assertEqual(row['epoch_before'], [1, 1, 0])
            self.assertEqual(row['epoch_after'], [1, 1, 0])
            self.assertEqual(row['observations'], list(range(12)))
            self.assertEqual(row['stream_a']+row['stream_b'], list(struct.unpack('<72h', bytes(range(144)))))
        for _ in range(2):
            trial.call('begin')
            self.assertEqual(trial.call('finish'), 0)
        self.assertEqual(trial.storage(), data)
        self.assertEqual(trial.live()[:2], (0, 0))

    def test_original_masks_restored_during_copy_and_on_return(self):
        for masks in (0, 0x40, 0x80, 0xc0):
            trial = capture.CaptureTrial(masks=masks)
            trial.call('begin'); trial.call('finish')
            self.assertEqual(trial.copy_masks, [masks]*72)

    def test_boundary_during_extraction_or_copy_is_retained_and_flagged(self):
        for during_copy in (False, True):
            trial = capture.CaptureTrial()
            trial.call('begin')
            if during_copy: self.assertIsNone(trial.call('finish', pause_at_sample=37))
            trial.epoch(2, 3)
            if during_copy: trial.resume()
            else: trial.call('finish')
            row = capture.decode_storage(trial.storage())['records'][0]
            self.assertEqual((row['flags'], row['epoch_before'], row['epoch_after']), (1, [1, 1, 0], [2, 3, 0]))
            trial.call('begin'); trial.call('finish')
            self.assertEqual(capture.decode_storage(trial.storage())['records'][1]['flags'], 0)

    def test_unknown_and_exhausted_epochs_are_never_silently_valid(self):
        for before, after, flags in [((0, 0, 0), (0, 0, 0), 2),
                                     ((1, 1, 1), (1, 1, 1), 4),
                                     ((1, 1, 0), (1, 1, 1), 4),
                                     ((0, 0, 0), (1, 1, 1), 7)]:
            trial = capture.CaptureTrial(); trial.epoch(*before)
            trial.call('begin'); trial.epoch(*after); trial.call('finish')
            self.assertEqual(capture.decode_storage(trial.storage())['records'][0]['flags'], flags)

    def test_nested_copy_cannot_freeze_while_outer_copy_can_resume(self):
        for pause in (1, 37, 72):
            trial = capture.CaptureTrial()
            trial.call('begin')
            self.assertIsNone(trial.call('finish', pause_at_sample=pause))
            trial.call('begin', sp=capture.STACK+0xe000)
            trial.uc.mem_write(capture.SAMPLES, b'\xff'*144)
            self.assertEqual(trial.call('finish', sp=capture.STACK+0xe000), 0)
            self.assertEqual(struct.unpack_from('<2I', trial.storage()), (4, 0))
            self.assertEqual(trial.live()[:2], (1, 1))
            self.assertEqual(trial.resume(), 1)
            data = trial.storage()
            row = capture.decode_storage(data)
            self.assertEqual((row['status'], row['count'], row['records'][0]['flags']), (5, 1, 8))
            trial.call('begin'); trial.call('finish')
            self.assertEqual(trial.storage(), data)

    def test_nested_extraction_and_late_arming_have_balanced_depth(self):
        trial = capture.CaptureTrial()
        trial.call('begin'); trial.call('begin'); trial.call('finish'); trial.call('finish')
        self.assertEqual(capture.decode_storage(trial.storage())['status'], 5)
        trial = capture.CaptureTrial(status=0)
        trial.call('begin')
        trial.uc.mem_write(capture.STORAGE, struct.pack('<I', 1))
        trial.call('begin'); trial.call('finish'); trial.call('finish')
        self.assertEqual(capture.decode_storage(trial.storage())['count'], 0)
        self.assertEqual(trial.live()[:2], (0, 0))
        trial.call('begin'); trial.call('finish')
        self.assertEqual(capture.decode_storage(trial.storage())['count'], 1)

    def test_idle_or_restart_cancel_does_not_invent_a_sample_record(self):
        for masks in (0, 0x40, 0x80, 0xc0):
            trial = capture.CaptureTrial(masks=masks)
            for _ in range(3):
                before = trial.storage()
                trial.call('begin'); trial.call('cancel')
                self.assertEqual(trial.storage(), before)
                self.assertEqual(trial.live()[:2], (0, 0))
            trial.call('begin'); trial.call('finish')
            self.assertEqual(capture.decode_storage(trial.storage())['count'], 1)

    def test_cancel_reports_nested_gap_even_without_a_record(self):
        for previous in (0, 1):
            for nested_exit in ('cancel', 'finish'):
                trial = capture.CaptureTrial()
                if previous:
                    trial.call('begin'); trial.call('finish')
                before_records = trial.storage()[16:]
                trial.call('begin'); trial.call('begin')
                trial.call(nested_exit); trial.call('cancel')
                data = trial.storage()
                decoded = capture.decode_storage(data)
                self.assertEqual((decoded['status'], decoded['count']), (6, previous))
                self.assertEqual(data[16:], before_records)
                trial.call('begin'); trial.call('cancel')
                self.assertEqual(trial.storage(), data)

    def test_nested_cancel_during_copy_cannot_publish_early(self):
        trial = capture.CaptureTrial(); trial.call('begin')
        trial.call('finish', pause_at_sample=37)
        trial.call('begin', sp=capture.STACK+0xe000)
        trial.call('cancel', sp=capture.STACK+0xe000)
        self.assertEqual(struct.unpack_from('<2I', trial.storage()), (4, 0))
        trial.resume()
        decoded = capture.decode_storage(trial.storage())
        self.assertEqual((decoded['status'], decoded['records'][0]['flags']), (5, 8))

    def test_unpaired_cancel_poison_and_inactive_cancel_preserve_storage(self):
        trial = capture.CaptureTrial(); before = trial.storage()
        trial.call('cancel')
        self.assertEqual(trial.storage(), before)
        self.assertEqual(trial.live()[3], 1)
        for status in (0, 2, 5, 6):
            trial = capture.CaptureTrial(status=status); before = trial.storage()
            trial.call('begin'); trial.call('cancel')
            self.assertEqual(trial.storage(), before)

    def test_invalid_controls_poison_without_touching_capture(self):
        for count in (512, 513, 0xffffffff):
            trial = capture.CaptureTrial(count=count); before = trial.storage()
            trial.call('begin'); trial.call('finish')
            self.assertEqual(trial.storage(), before)
            self.assertEqual(trial.live()[3], 1)
        for mutation in ((capture.STORAGE+8, 0), (capture.STORAGE+12, 1), (capture.LIVE, 0xffffffff)):
            trial = capture.CaptureTrial()
            trial.uc.mem_write(mutation[0], struct.pack('<I', mutation[1]))
            before = trial.storage()
            trial.call('begin'); trial.call('finish')
            self.assertEqual(trial.storage(), before)
            self.assertEqual(trial.live()[3], 1)
        trial = capture.CaptureTrial(); before = trial.storage()
        trial.call('finish')
        self.assertEqual(trial.storage(), before)
        self.assertEqual(trial.live()[3], 1)

    def test_poison_during_copy_never_publishes_frozen_storage(self):
        trial = capture.CaptureTrial(); trial.call('begin')
        trial.call('finish', pause_at_sample=37)
        trial.uc.mem_write(capture.LIVE+12, struct.pack('<I', 1))
        self.assertEqual(trial.resume(), 0)
        self.assertEqual(struct.unpack_from('<2I', trial.storage()), (4, 0))
        with self.assertRaises(ValueError): capture.decode_storage(trial.storage())

    def test_lost_pair_or_corrupt_owner_cannot_publish_after_copy(self):
        for address, value in ((capture.LIVE, 2), (capture.LIVE+4, 0),
                               (capture.LIVE+8, 16), (capture.STORAGE+4, 77)):
            trial = capture.CaptureTrial(); trial.call('begin')
            trial.call('finish', pause_at_sample=37)
            trial.uc.mem_write(address, struct.pack('<I', value))
            self.assertEqual(trial.resume(), 0)
            self.assertEqual(trial.live()[3], 1)
            self.assertEqual(struct.unpack_from('<I', trial.storage())[0], 4)
            with self.assertRaises(ValueError): capture.decode_storage(trial.storage())

    def test_decoder_rejects_bad_identity_flags_and_unstable_control(self):
        trial = capture.CaptureTrial(); trial.call('begin'); trial.call('finish')
        data = trial.storage()
        for offset, value in ((0, 4), (4, 512), (8, 0), (12, 1), (16, 99), (20, 1), (20, 8), (20, 16)):
            bad = bytearray(data); struct.pack_into('<I', bad, offset, value)
            with self.assertRaises(ValueError): capture.decode_storage(bytes(bad))
        with self.assertRaises(ValueError): capture.decode_storage(data[:-1])


if __name__ == '__main__': unittest.main()
