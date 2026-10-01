"""Provenance and non-overclaim tests for the DSP-to-SSIF evidence crosswalk."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import native_receive_lane_bridge as bridge


def reports():
    dsp = {
        'image_sha256': bridge.PINNED_CONTAINER,
        'program_sha256': bridge.PINNED_DSP_PROGRAM,
        'source_revision': {'commit': bridge.PINNED_COMMIT, 'dirty': False},
        'source_unchanged': True,
    }
    controls = {
        'image_sha256': bridge.PINNED_CONTAINER,
        'application_sha256': bridge.PINNED_APPLICATION,
        'source_revision': {'commit': bridge.PINNED_COMMIT, 'dirty': False},
        'source_unchanged': True,
    }
    capture = {
        'schema_version': 3,
        'recording_sha256': bridge.PINNED_RECORDING,
        'capture_sha256': bridge.PINNED_CAPTURE,
        'input_unchanged': True,
        'capture_full': True,
        'capture_status': 2,
        'raw_observation_summary': {'records': 512,
            'ssi_raw_register_counts': {'ssisr': {'0x20000002': 1}}},
        'raw_streams': {
            'stream_a': {'samples': 18432, 'rms': 4217.12},
            'stream_b': {'samples': 18432, 'zero_samples': 18432, 'min': 0, 'max': 0},
        },
        'recorder_matches': [{
            'stream': 'stream_a', 'stride': 6, 'phase': 0, 'gain': 'unity',
            'matching_samples': 3024, 'matching_records': 504,
            'first_capture_sequence': 0, 'last_capture_sequence': 503,
            'segment_last_capture_sequence': 511,
        }],
    }
    return dsp, controls, capture


class LaneBridgeTests(unittest.TestCase):
    def test_crosswalk_binds_hashes_and_observed_queue_match(self):
        result = bridge.crosscheck(*reports(), {'capture_report': {'sha256': 'abc'}})
        self.assertEqual(result['firmware_identity']['dsp_program_sha256'], bridge.PINNED_DSP_PROGRAM)
        self.assertEqual(result['capture_observation']['records'], 512)
        self.assertEqual(result['capture_observation']['recorder_match']['last_capture_sequence'], 503)
        self.assertIn('not identified as CPU stream A or B', result['crosswalk'][1]['context_416_447'])
        self.assertIn('0x1180c610', result['crosswalk'][2]['original_image_addresses'])
        self.assertIn('all-zero stream B has no established purpose', result['unknowns'][1])
        self.assertIn('Raw non-atomic snapshots only', result['capture_observation']['ssi_interpretation'])

    def test_rejects_mixed_firmware_provenance(self):
        dsp, controls, capture = reports()
        controls['application_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'pinned original image/application'):
            bridge.crosscheck(dsp, controls, capture, {})

    def test_rejects_capture_that_changes_zero_b_or_match_boundary(self):
        dsp, controls, capture = reports()
        capture['raw_streams']['stream_b']['zero_samples'] = 18431
        with self.assertRaisesRegex(ValueError, 'stream summaries'):
            bridge.crosscheck(dsp, controls, capture, {})
        dsp, controls, capture = reports()
        capture['recorder_matches'][0]['last_capture_sequence'] = 511
        with self.assertRaisesRegex(ValueError, 'Recorder match'):
            bridge.crosscheck(dsp, controls, capture, {})


if __name__ == '__main__':
    unittest.main()
