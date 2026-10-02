import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from clock_sample_logger import (
    InjectedClockProvider,
    SampleRecorder,
    SystemClockProvider,
    TimeQualityPolicy,
    assess_observation,
    load_fixture,
    verify_log,
    write_log,
)


POLICY = TimeQualityPolicy(max_sync_age_ms=1000, max_uncertainty_ms=20)


def fixture_observation(utc=500, monotonic=500, last_sync=500,
                        uncertainty=5, source_valid=True):
    provider = InjectedClockProvider('fixture:test', [{
        'utc_ms': utc,
        'monotonic_ms': monotonic,
        'last_sync_monotonic_ms': last_sync,
        'uncertainty_ms': uncertainty,
        'source_valid': source_valid,
        'pairing_span_ns': 0,
    }])
    return provider.sample()


class ClockProviderTests(unittest.TestCase):
    def test_system_provider_marks_sync_validity_and_uncertainty_unavailable(self):
        observation = SystemClockProvider().sample()
        self.assertEqual(observation.fields['utc_ms'].state, 'observed')
        self.assertEqual(observation.fields['monotonic_ms'].state, 'observed')
        self.assertEqual(observation.fields['pairing_span_ns'].state, 'observed')
        self.assertEqual(observation.fields['last_sync_monotonic_ms'].state, 'unavailable')
        self.assertEqual(observation.fields['uncertainty_ms'].state, 'unavailable')
        self.assertEqual(observation.fields['source_valid'].state, 'unknown')
        self.assertEqual(assess_observation(observation, None, POLICY)['verdict'], 'unqualified')
        with self.assertRaisesRegex(ValueError, 'unqualified'):
            observation.to_qso_clock_sample_fields(POLICY)

    def test_explicit_fixture_is_deterministic_and_policy_scoped(self):
        observation = fixture_observation()
        self.assertEqual(observation.source_identity.value, 'fixture:test')
        self.assertEqual(observation.to_qso_clock_sample_fields(POLICY), {
            'utc_ms': 500, 'monotonic_ms': 500, 'last_sync_monotonic_ms': 500,
            'uncertainty_ms': 5, 'source_valid': True,
        })
        assessment = assess_observation(observation, None, POLICY)
        self.assertEqual(assessment['verdict'], 'within_explicit_test_policy')
        self.assertIn('observation only', assessment['scope'])

    def test_qso_conversion_requires_explicit_policy_and_in_bounds_values(self):
        observation = fixture_observation()
        with self.assertRaisesRegex(ValueError, 'without explicit age and uncertainty'):
            observation.to_qso_clock_sample_fields(TimeQualityPolicy())
        stale = fixture_observation(monotonic=1501, last_sync=500)
        with self.assertRaisesRegex(ValueError, 'maximum sync age'):
            stale.to_qso_clock_sample_fields(POLICY)
        uncertain = fixture_observation(uncertainty=21)
        with self.assertRaisesRegex(ValueError, 'maximum uncertainty'):
            uncertain.to_qso_clock_sample_fields(POLICY)

    def test_fixture_preserves_unknown_and_unavailable_states(self):
        observation = InjectedClockProvider('fixture:missing', [{
            'utc_ms': 500, 'monotonic_ms': 500,
            'last_sync_monotonic_ms': None,
            'uncertainty_ms': {'value': None, 'state': 'unavailable',
                               'reason': 'fixture source has no error estimate'},
            'source_valid': None, 'pairing_span_ns': 0,
        }]).sample()
        self.assertEqual(observation.fields['last_sync_monotonic_ms'].state, 'unknown')
        self.assertEqual(observation.fields['uncertainty_ms'].state, 'unavailable')
        self.assertEqual(assess_observation(observation, None, POLICY)['verdict'], 'unqualified')

    def test_source_loss_stops_being_within_policy(self):
        provider = InjectedClockProvider('fixture:loss', [
            {'utc_ms': 500, 'monotonic_ms': 500, 'last_sync_monotonic_ms': 500,
             'uncertainty_ms': 5, 'source_valid': True, 'pairing_span_ns': 0},
            {'utc_ms': 501, 'monotonic_ms': 501, 'last_sync_monotonic_ms': 500,
             'uncertainty_ms': 5, 'source_valid': False, 'pairing_span_ns': 0},
        ])
        previous = provider.sample()
        current = provider.sample()
        assessment = assess_observation(current, previous, POLICY)
        self.assertEqual(assessment['verdict'], 'invalid')
        self.assertIn('source_invalid', assessment['events'])
        self.assertIn('source_validity_lost', assessment['events'])

    def test_stale_sync_and_excess_uncertainty_are_invalid(self):
        stale = fixture_observation(utc=1501, monotonic=1501, last_sync=500)
        stale_result = assess_observation(stale, None, POLICY)
        self.assertEqual(stale_result['sync_age_ms'], 1001)
        self.assertIn('sync_estimate_stale', stale_result['events'])
        self.assertEqual(stale_result['verdict'], 'invalid')

        uncertain = fixture_observation(uncertainty=21)
        uncertain_result = assess_observation(uncertain, None, POLICY)
        self.assertIn('uncertainty_exceeds_explicit_policy', uncertain_result['events'])
        self.assertEqual(uncertain_result['verdict'], 'invalid')

    def test_backward_time_and_forward_jump_are_reported(self):
        prior = fixture_observation()
        backward_utc = fixture_observation(utc=499, monotonic=501)
        utc_result = assess_observation(backward_utc, prior, POLICY)
        self.assertIn('utc_moved_backward', utc_result['events'])
        self.assertEqual(utc_result['verdict'], 'invalid')

        backward_mono = fixture_observation(utc=501, monotonic=499)
        mono_result = assess_observation(backward_mono, prior, POLICY)
        self.assertIn('monotonic_moved_backward', mono_result['events'])
        self.assertEqual(mono_result['verdict'], 'invalid')

        forward_jump = fixture_observation(utc=1001, monotonic=750, last_sync=500)
        jump_result = assess_observation(forward_jump, prior, POLICY)
        self.assertEqual(jump_result['utc_minus_monotonic_delta_ms'], 251)
        self.assertIn('prototype_discontinuity_heuristic_exceeded', jump_result['events'])
        self.assertEqual(jump_result['verdict'], 'invalid')
        self.assertEqual(jump_result['discontinuity_heuristic_ms'], 250)

    def test_repeated_sample_is_recorded_with_a_new_sequence(self):
        observation = fixture_observation()
        recorder = SampleRecorder(POLICY)
        first = recorder.record(observation)
        second = recorder.record(observation)
        self.assertEqual(first['sequence'], 1)
        self.assertEqual(second['sequence'], 2)
        self.assertIn('repeated_sample', second['assessment']['events'])
        self.assertEqual(second['assessment']['verdict'], 'within_explicit_test_policy')
        self.assertEqual(second['previous_hash'], first['record_hash'])

    def test_json_fixture_loader_and_hash_chain_integrity(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture = root / 'fixture.json'
            fixture.write_text(json.dumps({
                'schema_version': 1,
                'source_identity': 'fixture:integrity',
                'samples': [
                    {'utc_ms': 500, 'monotonic_ms': 500, 'last_sync_monotonic_ms': 500,
                     'uncertainty_ms': 5, 'source_valid': True, 'pairing_span_ns': 0},
                    {'utc_ms': 501, 'monotonic_ms': 501, 'last_sync_monotonic_ms': 500,
                     'uncertainty_ms': 5, 'source_valid': True, 'pairing_span_ns': 0},
                ],
            }))
            provider = load_fixture(fixture)
            output = root / 'samples.jsonl'
            write_log(output, provider, count=2, policy=POLICY)
            self.assertTrue(verify_log(output)['valid'])

            records = [json.loads(line) for line in output.read_text().splitlines()]
            records[0]['fields']['utc_ms']['value'] = 501
            output.write_text('\n'.join(json.dumps(row, sort_keys=True, separators=(',', ':'))
                                          for row in records) + '\n')
            verification = verify_log(output)
            self.assertFalse(verification['valid'])
            self.assertIn('record hash mismatch', verification['errors'][0])

    def test_sequence_gap_and_partial_final_line_fail_integrity(self):
        recorder = SampleRecorder(POLICY)
        first = recorder.record(fixture_observation())
        second = recorder.record(fixture_observation(utc=501, monotonic=501, last_sync=500))
        second['sequence'] = 3
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'bad.jsonl'
            path.write_text(json.dumps(first) + '\n' + json.dumps(second) + '\n')
            result = verify_log(path)
            self.assertFalse(result['valid'])
            self.assertIn('sequence discontinuity', result['errors'][0])
            path.write_bytes(json.dumps(first).encode())
            self.assertFalse(verify_log(path)['valid'])
            self.assertIn('incomplete final line', verify_log(path)['errors'])


if __name__ == '__main__':
    unittest.main()
