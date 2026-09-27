import importlib.util
from pathlib import Path
import sys
import json
import subprocess
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from capture_receive import convert, main, select_input, slot_ranges, timing_report


class ReceiveCaptureTests(unittest.TestCase):
    def test_stalled_audio_initialization_has_bounded_failure_record(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'capture'
            with patch.object(sys, 'argv', ['capture_receive.py', '--device-name', 'USB Audio CODEC',
                                           '--seconds', '1', '--output', str(output)]), \
                 patch('capture_receive.subprocess.run', side_effect=subprocess.TimeoutExpired('worker', 21)) as run:
                with self.assertRaises(SystemExit):
                    main()
            self.assertEqual(run.call_args.kwargs['timeout'], 21)
            self.assertEqual(json.loads((output / 'failure.json').read_text())['outcome'], 'TIMEOUT')
            self.assertFalse((output / 'capture.json').exists())

    def test_device_selection_never_falls_back(self):
        devices = [dict(name='Display Audio', max_input_channels=1),
                   dict(name='USB Audio CODEC', max_input_channels=0),
                   dict(name='USB Audio CODEC', max_input_channels=2)]
        self.assertEqual(select_input(devices, 'USB Audio CODEC')[0], 2)
        with self.assertRaises(ValueError):
            select_input(devices, 'missing')
        with self.assertRaises(ValueError):
            select_input(devices + devices[2:], 'USB Audio CODEC')

    def test_slots_are_complete_and_utc_aligned(self):
        self.assertEqual(list(slot_ranges(1.25, 60 * 12000)),
                         [(15, 165000, 345000), (30, 345000, 525000), (45, 525000, 705000)])
        self.assertEqual(list(slot_ranges(0, 180000)), [(0, 0, 180000)])
        self.assertEqual(list(slot_ranges(0.1, 180000)), [])

    def test_gap_status_and_bad_clock_reject_alignment(self):
        good = [[0, 100, 100.1, 0], [4800, 100.1, 100.2, 0]]
        self.assertTrue(timing_report(good)['continuity_ok'])
        for bad in ([[0, 100, 100.1, 1], good[1]],
                    [good[0], [4800, 100.2, 100.3, 0]],
                    [[0, 0, 0.1, 0]], []):
            self.assertFalse(timing_report(bad)['continuity_ok'])

    @unittest.skipUnless(importlib.util.find_spec('numpy') and importlib.util.find_spec('scipy'),
                         'optional audio dependencies')
    def test_resampler_preserves_passband_rejects_alias_and_selects_channel(self):
        import numpy as np
        t = np.arange(48000) / 48000
        data = np.column_stack((12000 * np.sin(2 * np.pi * 1000 * t),
                                12000 * np.sin(2 * np.pi * 10000 * t))).astype(np.int16)
        low, clips = convert(data, 0)
        high, _ = convert(data, 1)
        self.assertEqual(len(low), 12000)
        self.assertEqual(clips, 0)
        self.assertGreater(np.sqrt(np.mean(low[120:-120].astype(float) ** 2)), 8000)
        self.assertLess(np.sqrt(np.mean(high[120:-120].astype(float) ** 2)), 30)
        impulse = np.zeros((48000, 2), dtype=np.int16)
        impulse[24000, 0] = 30000
        converted, _ = convert(impulse, 0)
        self.assertEqual(int(np.argmax(converted)), 6000)


if __name__ == '__main__':
    unittest.main()
