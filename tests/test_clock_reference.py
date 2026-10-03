from datetime import date, datetime, time as datetime_time, timedelta, timezone
from fractions import Fraction
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import clock_reference as reference
from civ_clock_measurement import HostEndpoint
from clock_sample_logger import ClockObservation, FieldValue, TimeQualityPolicy


POLICY = TimeQualityPolicy(max_sync_age_ms=10_000, max_uncertainty_ms=20)
MONO_DOMAIN = "synthetic:monotonic-domain-a"
BASE_UTC_MS = 1_767_225_600_000  # 2026-01-01T00:00:00Z


def observation(*, utc_ms=BASE_UTC_MS, monotonic_ms=1_000,
                last_sync_monotonic_ms=None, uncertainty_ms=10,
                source_valid=True, pairing_span_ns=1_000,
                source_identity="synthetic:host-reference"):
    if last_sync_monotonic_ms is None:
        last_sync_monotonic_ms = monotonic_ms
    fields = {
        "utc_ms": FieldValue.observed(utc_ms),
        "monotonic_ms": FieldValue.observed(monotonic_ms),
        "last_sync_monotonic_ms": FieldValue.observed(last_sync_monotonic_ms),
        "uncertainty_ms": FieldValue.observed(uncertainty_ms),
        "source_valid": FieldValue.observed(source_valid),
        "pairing_span_ns": FieldValue.observed(pairing_span_ns),
    }
    return ClockObservation(
        FieldValue.observed(source_identity), fields,
        {"provider": "synthetic-fixture", "clock_domain": MONO_DOMAIN},
    )


def evidence(before=None, after=None, *, domain=MONO_DOMAIN,
             utc_scale="unix_epoch_utc", scope="full_span", cache_age_ns=100_000_000,
             cache_state="observed", host_basis="synthetic_fixture",
             cache_basis="synthetic_fixture"):
    before = before or observation()
    after = after or observation(utc_ms=BASE_UTC_MS + 2_000, monotonic_ms=3_000)
    cache = (FieldValue.observed(cache_age_ns) if cache_state == "observed"
             else FieldValue.unknown("fixture did not bound firmware cache age"))
    return reference.HostReferenceEvidence(
        before=before,
        after=after,
        monotonic_domain_id=(FieldValue.observed(domain) if domain is not None
                             else FieldValue.unknown("fixture omitted monotonic domain")),
        utc_scale_id=(FieldValue.observed(utc_scale) if utc_scale is not None
                      else FieldValue.unknown("fixture omitted UTC scale")),
        uncertainty_scope=(FieldValue.observed(scope) if scope is not None
                           else FieldValue.unknown("fixture omitted span scope")),
        firmware_cache_age_upper_bound_ns=cache,
        host_evidence_basis=host_basis,
        cache_evidence_basis=cache_basis,
    )


def transaction(start_ns=2_000_000_000, end_ns=2_100_000_000):
    return (
        HostEndpoint(BASE_UTC_MS * 1_000_000 + 1_000_000_000, start_ns, 1_000),
        HostEndpoint(BASE_UTC_MS * 1_000_000 + 1_100_000_000, end_ns, 1_000),
    )


def estimate(evidence_span=None, *, tx=None, domain=MONO_DOMAIN,
             radio_date=date(2026, 1, 1), radio_time=datetime_time(0, 0),
             utc_offset=timedelta(0), policy=POLICY):
    tx_start, tx_end = tx or transaction()
    return reference.estimate_radio_minus_host_interval(
        radio_date, radio_time, utc_offset, tx_start, tx_end, domain,
        evidence_span or evidence(), policy)


class HostReferenceEvidenceTests(unittest.TestCase):
    def test_minute_bucket_and_provider_bounds_remain_conditional(self):
        result = estimate(evidence(host_basis="provider_reported",
                                   cache_basis="static_analysis"))
        self.assertEqual(result.state, "conditional_on_declared_bounds")
        self.assertIsNotNone(result.radio_minus_host)
        self.assertEqual(result.radio_utc_minute_bucket.upper_ns
                         - result.radio_utc_minute_bucket.lower_ns + 1,
                         reference.NS_PER_MINUTE)
        self.assertGreaterEqual(result.radio_minus_host.upper_ns
                                - result.radio_minus_host.lower_ns + 1,
                                reference.NS_PER_MINUTE)
        self.assertFalse(result.as_json()["real_world_quality_claim"])
        self.assertNotIn("measured", result.state)

    def test_fixture_values_are_never_promoted_to_real_world_quality(self):
        result = estimate()
        self.assertEqual(result.state, "synthetic_only")
        self.assertIsNotNone(result.radio_minus_host)
        self.assertFalse(result.as_json()["real_world_quality_claim"])

    def test_missing_uncertainty_or_sync_metadata_is_unqualified(self):
        missing_uncertainty = observation()
        missing_uncertainty.fields["uncertainty_ms"] = FieldValue.unavailable(
            "no conservative bound")
        result = estimate(evidence(before=missing_uncertainty))
        self.assertEqual(result.state, "unqualified")
        self.assertIsNone(result.radio_minus_host)

        missing_sync = observation()
        missing_sync.fields["last_sync_monotonic_ms"] = FieldValue.unknown(
            "sync event not reported")
        result = estimate(evidence(before=missing_sync))
        self.assertEqual(result.state, "unqualified")
        self.assertIsNone(result.radio_minus_host)

    def test_missing_cache_bound_is_unqualified_even_with_host_quality(self):
        result = estimate(evidence(cache_state="unknown"))
        self.assertEqual(result.state, "unqualified")
        self.assertIn("cache age", result.reasons[0])
        self.assertIsNone(result.radio_minus_host)

    def test_point_only_uncertainty_does_not_bound_the_capture_span(self):
        result = estimate(evidence(scope="point_samples_only"))
        self.assertEqual(result.state, "unqualified")
        self.assertIsNone(result.radio_minus_host)

        missing_pair = observation()
        missing_pair.fields["pairing_span_ns"] = FieldValue.unavailable(
            "provider did not report endpoint pairing")
        result = estimate(evidence(before=missing_pair))
        self.assertEqual(result.state, "unqualified")

    def test_invalid_source_and_stale_sync_are_rejected(self):
        invalid_source = observation(source_valid=False)
        result = estimate(evidence(before=invalid_source))
        self.assertEqual(result.state, "invalid")

        stale_source = observation(monotonic_ms=20_000, last_sync_monotonic_ms=0)
        result = estimate(evidence(before=stale_source))
        self.assertEqual(result.state, "invalid")
        self.assertIn("sync_estimate_stale", result.reasons[0])

    def test_clock_step_in_reference_span_is_rejected(self):
        before = observation()
        after = observation(utc_ms=BASE_UTC_MS + 2_500, monotonic_ms=3_000)
        result = estimate(evidence(before=before, after=after))
        self.assertEqual(result.state, "invalid")
        self.assertIn("prototype_discontinuity_heuristic_exceeded", result.reasons[0])

    def test_source_change_and_domain_mismatch_are_not_joined(self):
        before = observation()
        after = observation(utc_ms=BASE_UTC_MS + 2_000, monotonic_ms=3_000,
                            source_identity="synthetic:other-source")
        result = estimate(evidence(before=before, after=after))
        self.assertEqual(result.state, "unqualified")

        result = estimate(evidence(), domain="synthetic:other-domain")
        self.assertEqual(result.state, "invalid")
        self.assertIn("domains differ", result.reasons[0])

    def test_reference_samples_must_cover_cache_and_transaction_window(self):
        late_before = observation(utc_ms=BASE_UTC_MS + 900, monotonic_ms=1_900)
        result = estimate(evidence(before=late_before))
        self.assertEqual(result.state, "unqualified")
        self.assertIn("cache-age window", result.reasons[0])

        tx_start, tx_end = transaction()
        early_after = observation(utc_ms=BASE_UTC_MS + 500, monotonic_ms=1_500)
        result = estimate(evidence(after=early_after), tx=(tx_start, tx_end))
        self.assertEqual(result.state, "unqualified")

    def test_utc_scale_and_wrong_evidence_basis_fail_closed(self):
        result = estimate(evidence(utc_scale="TAI"))
        self.assertEqual(result.state, "invalid")
        result = estimate(evidence(), policy=TimeQualityPolicy())
        self.assertEqual(result.state, "unqualified")
        with self.assertRaisesRegex(ValueError, "evidence basis"):
            evidence(host_basis="measured")

    def test_utc_offset_conversion_crosses_calendar_boundary(self):
        result = estimate(
            evidence(), radio_date=date(2026, 1, 1),
            radio_time=datetime_time(0, 30), utc_offset=timedelta(hours=1))
        expected = datetime(2025, 12, 31, 23, 30, tzinfo=timezone.utc)
        delta = expected - datetime(1970, 1, 1, tzinfo=timezone.utc)
        expected_ns = (delta.days * 86_400 + delta.seconds) * reference.NS_PER_SECOND
        self.assertEqual(result.radio_utc_minute_bucket.lower_ns, expected_ns)

        negative = estimate(
            evidence(), radio_date=date(2026, 1, 1),
            radio_time=datetime_time(0, 30), utc_offset=timedelta(hours=-1))
        expected = datetime(2026, 1, 1, 1, 30, tzinfo=timezone.utc)
        delta = expected - datetime(1970, 1, 1, tzinfo=timezone.utc)
        expected_ns = (delta.days * 86_400 + delta.seconds) * reference.NS_PER_SECOND
        self.assertEqual(negative.radio_utc_minute_bucket.lower_ns, expected_ns)

    def test_nonminute_offset_time_and_int64_overflow_are_rejected(self):
        result = estimate(radio_time=datetime_time(0, 0, 1))
        self.assertEqual(result.state, "invalid")
        result = estimate(radio_date=date(9999, 12, 31),
                          radio_time=datetime_time(23, 59))
        self.assertEqual(result.state, "invalid")

    def test_offset_limits_and_negative_host_bounds(self):
        ok = estimate(radio_time=datetime_time(12, 0),
                      utc_offset=timedelta(hours=14))
        self.assertEqual(ok.state, "synthetic_only")
        bad = estimate(radio_time=datetime_time(12, 0),
                       utc_offset=timedelta(hours=14, minutes=1))
        self.assertEqual(bad.state, "invalid")

        huge_uncertainty = observation(uncertainty_ms=reference.INT64_MAX)
        wide_policy = TimeQualityPolicy(max_sync_age_ms=10_000,
                                        max_uncertainty_ms=reference.INT64_MAX)
        overflow = estimate(evidence(before=huge_uncertainty), policy=wide_policy)
        self.assertEqual(overflow.state, "invalid")
        self.assertIn("overflows", overflow.reasons[0])


class DriftIntervalTests(unittest.TestCase):
    def offset(self, lower, upper, state="synthetic_only", domain=MONO_DOMAIN):
        return reference.ClockOffsetEstimate(
            state=state,
            radio_utc_minute_bucket=None,
            radio_minus_host=reference.NsInterval(lower, upper),
            monotonic_domain_id=domain,
            evidence_basis={"host_reference": "synthetic_fixture",
                            "firmware_cache_age": "synthetic_fixture"},
            reasons=(),
        )

    def test_drift_interval_uses_minute_bin_ranges_and_exact_ppm(self):
        result = reference.estimate_drift_interval_ppm(
            self.offset(0, 60_000_000_000),
            self.offset(60_000_000_000, 120_000_000_000),
            reference.NsInterval(60_000_000_000_000,
                                 60_000_000_000_000),
            MONO_DOMAIN)
        self.assertEqual(result.state, "synthetic_only")
        self.assertLess(result.lower_ppm, result.upper_ppm)
        self.assertFalse(result.as_json()["real_world_quality_claim"])
        self.assertEqual(result.lower_ppm, Fraction(0))
        self.assertEqual(result.upper_ppm, Fraction(2_000))

    def test_unbounded_intervals_elapsed_boundary_and_domain_mismatch(self):
        unbounded = reference.ClockOffsetEstimate(
            "unqualified", None, None, MONO_DOMAIN, {}, ("unknown",))
        valid = self.offset(0, 1)
        result = reference.estimate_drift_interval_ppm(
            unbounded, valid, reference.NsInterval(1, 1), MONO_DOMAIN)
        self.assertEqual(result.state, "unqualified")

        result = reference.estimate_drift_interval_ppm(
            valid, valid, reference.NsInterval(0, 1), MONO_DOMAIN)
        self.assertEqual(result.state, "invalid")

        result = reference.estimate_drift_interval_ppm(
            valid, valid, reference.NsInterval(1, 1), "other-domain")
        self.assertEqual(result.state, "invalid")


if __name__ == "__main__":
    unittest.main()
