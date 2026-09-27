"""Independent oracle: C transmit generator supplies signals, not Python model."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import wave
import numpy as np
from scipy import signal
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from cancellation import cancel_slot, decode, fit_signal

EXE = Path(os.environ.get('FT8_PROTO', 'build/ft8_proto')).resolve()

class CancellationCoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
    def tearDown(self):
        self.temp.cleanup()
    def generated(self, message, hz, name):
        path = self.root / (name + '.wav')
        subprocess.run([str(EXE), 'generate', message, str(path), str(hz)], check=True, capture_output=True)
        with wave.open(str(path)) as f:
            return np.frombuffer(f.readframes(f.getnframes()), '<i2').astype(float) / 32768
    def test_overlap_recovers_weaker_and_preserves_original(self):
        first = self.generated('CQ K1ABC FN42', 1000, 'first')
        second = self.generated('CQ W9XYZ EN50', 1014, 'second')
        # Independent C waveforms; estimator receives no mixing parameters.
        mixed = .8 * first + .4 * second
        before = mixed.copy()
        result = cancel_slot(mixed, EXE, self.root / 'result')
        self.assertEqual(result['termination'], 'completed')
        self.assertEqual({r['message'] for r in result['baseline']}, {'CQ K1ABC FN42'})
        self.assertEqual({r['message'] for r in result['messages']}, {'CQ K1ABC FN42', 'CQ W9XYZ EN50'})
        self.assertEqual(result['passes_completed'], 2)
        self.assertIn('max_passes', result['limits_reached'])
        np.testing.assert_array_equal(mixed, before)
        self.assertLess(result['fits'][0]['energy_after'], result['fits'][0]['energy_before'] / 3)
    def test_fractional_offsets_phase_and_seeded_noise(self):
        source = self.generated('CQ K1ABC FN42', 1000, 'source')
        analytic = signal.hilbert(source)
        t = np.arange(len(source)) / 12000
        shift = .01337
        shifted = np.interp(t - shift, t, analytic.real, left=0, right=0) + 1j * np.interp(t - shift, t, analytic.imag, left=0, right=0)
        observed = .7 * np.real(shifted * np.exp(1j * (2 * np.pi * .73 * t + 1.12)))
        observed += np.random.default_rng(193).normal(0, .003, len(source))
        result = cancel_slot(observed, EXE, self.root / 'offsets')
        self.assertEqual(result['termination'], 'completed')
        self.assertEqual({r['message'] for r in result['messages']}, {'CQ K1ABC FN42'})
        fit = result['fits'][0]
        self.assertTrue(fit['accepted'])
        self.assertAlmostEqual(fit['frequency_hz'], 1000.73, delta=.005)
        self.assertAlmostEqual(fit['start_s'], .5 + shift, delta=.001)
        self.assertLess(fit['energy_after'], fit['energy_before'] * .01)
    def test_silence_and_wrong_candidate_rejected(self):
        result = cancel_slot(np.zeros(180000), EXE, self.root / 'silence')
        self.assertEqual(result['termination'], 'completed')
        self.assertEqual(result['messages'], [])
        first = self.generated('CQ K1ABC FN42', 1000, 'first')
        second = self.generated('CQ W9XYZ EN50', 1000, 'second')
        row = decode(second, EXE, self.root, 'wrong', time.monotonic() + 10)[0]
        prediction, report = fit_signal(first, row, time.monotonic() + 10)
        self.assertIsNone(prediction)
        self.assertFalse(report['accepted'])
    def test_signal_cap_reports_skips(self):
        first = self.generated('CQ K1ABC FN42', 1000, 'first')
        second = self.generated('CQ W9XYZ EN50', 1050, 'second')
        result = cancel_slot(.8 * first + .4 * second, EXE, self.root / 'cap', max_signals=1)
        self.assertEqual(result['termination'], 'completed')
        self.assertEqual(len(result['fits']), 1)
        self.assertIn('max_signals', result['limits_reached'])
        self.assertTrue(any(r['reason'] == 'signal_limit' for r in result['skipped_candidates']))
        self.assertEqual({r['message'] for r in result['messages']}, {'CQ K1ABC FN42', 'CQ W9XYZ EN50'})
    def test_limits_and_deadline_are_not_success(self):
        with self.assertRaises(ValueError):
            cancel_slot(np.zeros(10), EXE, self.root, max_signals=9)
        result = cancel_slot(np.zeros(180000), EXE, self.root / 'timeout', deadline_seconds=1e-9)
        self.assertEqual(result['termination'], 'deadline')
        self.assertEqual(result['messages'], [])

    def test_residual_energy_and_clipping_preserve_direct_calculation(self):
        source = self.generated('CQ K1ABC FN42', 1000, 'residual-source')
        samples = .8 * source
        row = decode(samples, EXE, self.root, 'residual-baseline', time.monotonic() + 10)[0]
        before = samples.copy()
        prediction, report = fit_signal(samples, row, time.monotonic() + 10)
        self.assertIsNotNone(prediction)
        self.assertTrue(report['accepted'])
        self.assertEqual(report['energy_before'], float(np.dot(samples, samples)))
        self.assertEqual(report['energy_after'], float(np.dot(samples - prediction, samples - prediction)))
        self.assertLessEqual(float(np.max(np.abs(samples - prediction))), 32767 / 32768)
        np.testing.assert_array_equal(samples, before)
        # An isolated opposite-polarity impulse leaves the fit coherent but makes
        # subtraction exceed full-scale, which must still reject cancellation.
        for polarity in (-1, 1):
            clipped = samples.copy()
            index = np.argmin(prediction) if polarity == 1 else np.argmax(prediction)
            clipped[index] = polarity * (32767 / 32768)
            result, rejected = fit_signal(clipped, row, time.monotonic() + 10)
            self.assertIsNone(result)
            self.assertEqual(rejected['reason'], 'residual_would_clip')

    def test_nonfinite_input_is_rejected(self):
        for value in (float('nan'), float('inf'), -float('inf')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                cancel_slot(np.array([value]), EXE, self.root / 'nonfinite')
