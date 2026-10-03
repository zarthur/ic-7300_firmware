#!/usr/bin/env python3
"""Conditional host/radio clock bounds built from existing clock evidence.

This module performs no host clock reads, service configuration, serial I/O, or
radio setting. Provider bounds remain declarations; fixture inputs remain
synthetic. Neither is promoted to a measured real-world accuracy claim.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time as datetime_time, timedelta
from fractions import Fraction
from typing import Any

from civ_clock_measurement import HostEndpoint
from clock_sample_logger import (
    INT64_MAX,
    ClockObservation,
    FieldValue,
    TimeQualityPolicy,
    assess_observation,
)


NS_PER_MS = 1_000_000
NS_PER_SECOND = 1_000_000_000
NS_PER_MINUTE = 60 * NS_PER_SECOND
INT64_MIN = -INT64_MAX - 1
HOST_EVIDENCE_BASES = {"provider_reported", "synthetic_fixture"}
CACHE_EVIDENCE_BASES = {
    "provider_reported", "static_analysis", "synthetic_fixture",
}


@dataclass(frozen=True)
class HostReferenceEvidence:
    """A pair of existing logger observations surrounding one CI-V window.

    `uncertainty_scope` must say that the reported uncertainty bounds the whole
    span, not just the two point samples. `monotonic_domain_id` must identify
    the same counter used by the CI-V transaction endpoints. Evidence bases
    describe provenance only; provider-reported limits are conditional claims.
    """

    before: ClockObservation
    after: ClockObservation
    monotonic_domain_id: FieldValue
    utc_scale_id: FieldValue
    uncertainty_scope: FieldValue
    firmware_cache_age_upper_bound_ns: FieldValue
    host_evidence_basis: str
    cache_evidence_basis: str

    def __post_init__(self) -> None:
        if not isinstance(self.before, ClockObservation) \
                or not isinstance(self.after, ClockObservation):
            raise TypeError("host evidence must reuse ClockObservation samples")
        for name in ("monotonic_domain_id", "utc_scale_id", "uncertainty_scope",
                     "firmware_cache_age_upper_bound_ns"):
            if not isinstance(getattr(self, name), FieldValue):
                raise TypeError(f"{name} must be a FieldValue")
        if self.host_evidence_basis not in HOST_EVIDENCE_BASES:
            raise ValueError("host evidence basis must be provider_reported or synthetic_fixture")
        if self.cache_evidence_basis not in CACHE_EVIDENCE_BASES:
            raise ValueError("cache evidence basis must be provider_reported, static_analysis, or synthetic_fixture")


@dataclass(frozen=True)
class NsInterval:
    """Closed interval of integer nanosecond values."""

    lower_ns: int
    upper_ns: int

    def __post_init__(self) -> None:
        for name, value in (("lower_ns", self.lower_ns), ("upper_ns", self.upper_ns)):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an integer")
            if not INT64_MIN <= value <= INT64_MAX:
                raise ValueError(f"{name} is outside signed int64 nanoseconds")
        if self.lower_ns > self.upper_ns:
            raise ValueError("interval lower bound exceeds upper bound")

    def as_json(self) -> dict[str, int]:
        return {"lower_inclusive_ns": self.lower_ns, "upper_inclusive_ns": self.upper_ns}


@dataclass(frozen=True)
class ClockOffsetEstimate:
    """A reported bucket and optional conditional radio-minus-host interval."""

    state: str
    radio_utc_minute_bucket: NsInterval | None
    radio_minus_host: NsInterval | None
    monotonic_domain_id: str | None
    evidence_basis: dict[str, str]
    reasons: tuple[str, ...]

    def as_json(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "radio_utc_minute_bucket": (
                self.radio_utc_minute_bucket.as_json()
                if self.radio_utc_minute_bucket else None
            ),
            "radio_minus_host_interval": (
                self.radio_minus_host.as_json() if self.radio_minus_host else None
            ),
            "evidence_basis": dict(self.evidence_basis),
            "real_world_quality_claim": False,
            "reasons": list(self.reasons),
            "monotonic_domain_id": self.monotonic_domain_id,
        }


@dataclass(frozen=True)
class DriftEstimate:
    """Exact ppm interval; never a real-world quality attestation."""

    state: str
    lower_ppm: Fraction | None
    upper_ppm: Fraction | None
    reasons: tuple[str, ...] = ()

    def as_json(self) -> dict[str, Any]:
        def rational(value: Fraction | None) -> dict[str, str] | None:
            if value is None:
                return None
            return {"numerator": str(value.numerator),
                    "denominator": str(value.denominator)}

        return {
            "state": self.state,
            "lower_ppm": rational(self.lower_ppm),
            "upper_ppm": rational(self.upper_ppm),
            "real_world_quality_claim": False,
            "reasons": list(self.reasons),
        }


def _field_int(observation: ClockObservation, name: str) -> int | None:
    field = observation.fields[name]
    if field.state != "observed" or isinstance(field.value, bool) \
            or not isinstance(field.value, int):
        return None
    return field.value


def _reference_sample_mono_bounds(observation: ClockObservation) -> tuple[int, int] | None:
    mono_ms = _field_int(observation, "monotonic_ms")
    pairing_ns = _field_int(observation, "pairing_span_ns")
    if mono_ms is None or pairing_ns is None or mono_ms < 0 or pairing_ns < 0:
        return None
    if mono_ms > INT64_MAX // NS_PER_MS or pairing_ns > INT64_MAX:
        return None
    base = mono_ms * NS_PER_MS
    half_pair = (pairing_ns + 1) // 2
    # monotonic_ms is the truncated millisecond midpoint of the logger's pair.
    low = max(0, base - half_pair)
    high = base + NS_PER_MS + half_pair
    if high > INT64_MAX:
        return None
    return low, high


def _endpoint_bounds(endpoint: HostEndpoint) -> tuple[int, int] | None:
    mono = endpoint.host_monotonic_ns
    span = endpoint.monotonic_bracket_span_ns
    if isinstance(mono, bool) or not isinstance(mono, int) \
            or isinstance(span, bool) or not isinstance(span, int):
        return None
    if mono < 0 or span < 0 or mono > INT64_MAX or span > INT64_MAX:
        return None
    half = (span + 1) // 2
    low = max(0, mono - half)
    high = mono + half
    if high > INT64_MAX:
        return None
    return low, high


def _radio_bucket_start_ns(radio_date: date, radio_time: datetime_time,
                           utc_offset: timedelta) -> int:
    if not isinstance(radio_date, date) or isinstance(radio_date, datetime):
        raise ValueError("radio date must be a calendar date")
    if not isinstance(radio_time, datetime_time):
        raise ValueError("radio time must be a time of day")
    if radio_time.second != 0 or radio_time.microsecond != 0:
        raise ValueError("CI-V radio time must remain minute-resolution")
    if not isinstance(utc_offset, timedelta):
        raise ValueError("UTC offset must be a timedelta")
    offset_seconds = utc_offset.days * 86_400 + utc_offset.seconds
    if utc_offset.microseconds or offset_seconds % 60 \
            or abs(offset_seconds) > 14 * 3600:
        raise ValueError("UTC offset must be whole minutes within ±14:00")
    try:
        utc_minute = datetime.combine(radio_date, radio_time) - utc_offset
        delta = utc_minute - datetime(1970, 1, 1)
    except OverflowError as exc:
        raise ValueError("UTC minute conversion crosses the datetime boundary") from exc
    start_ns = (delta.days * 86_400 + delta.seconds) * NS_PER_SECOND \
        + delta.microseconds * 1_000
    if start_ns < 0 or start_ns + NS_PER_MINUTE - 1 > INT64_MAX:
        raise ValueError("radio UTC minute bucket is outside signed int64 nanoseconds")
    return start_ns


def _empty_estimate(state: str, reason: str, *,
                    bucket: NsInterval | None = None,
                    evidence: HostReferenceEvidence | None = None) -> ClockOffsetEstimate:
    basis = ({
        "host_reference": evidence.host_evidence_basis,
        "firmware_cache_age": evidence.cache_evidence_basis,
    } if evidence else {"host_reference": "unknown", "firmware_cache_age": "unknown"})
    return ClockOffsetEstimate(state, bucket, None, None, basis, (reason,))


def estimate_radio_minus_host_interval(
        radio_date: date, radio_time: datetime_time, utc_offset: timedelta,
        transaction_start: HostEndpoint, transaction_end: HostEndpoint,
        transaction_monotonic_domain_id: str,
        evidence: HostReferenceEvidence,
        policy: TimeQualityPolicy) -> ClockOffsetEstimate:
    """Compute an outer offset interval only when all declared bounds cover it.

    The value is radio-reported UTC minus host UTC at the possible RTC sample
    time. It includes the full minute bucket, host uncertainty, sample pairing,
    transaction span, and a bounded cache age. Provider/analysis claims remain
    conditional; fixtures are labelled synthetic. No state is called measured
    or qualified.
    """
    if not isinstance(evidence, HostReferenceEvidence):
        return _empty_estimate("invalid", "host reference evidence has the wrong type")
    if not isinstance(policy, TimeQualityPolicy):
        return _empty_estimate("invalid", "an explicit TimeQualityPolicy is required",
                               evidence=evidence)
    if not isinstance(transaction_start, HostEndpoint) \
            or not isinstance(transaction_end, HostEndpoint):
        return _empty_estimate("invalid", "transaction endpoints have the wrong type",
                               evidence=evidence)
    try:
        bucket_start = _radio_bucket_start_ns(radio_date, radio_time, utc_offset)
        bucket = NsInterval(bucket_start, bucket_start + NS_PER_MINUTE - 1)
    except (TypeError, ValueError, OverflowError) as exc:
        return _empty_estimate("invalid", f"invalid radio UTC bucket: {exc}", evidence=evidence)

    # Reuse the logger's source/freshness/uncertainty and discontinuity rules.
    before_assessment = assess_observation(evidence.before, None, policy)
    after_assessment = assess_observation(evidence.after, evidence.before, policy)
    if before_assessment["verdict"] == "invalid" or after_assessment["verdict"] == "invalid":
        events = before_assessment["events"] + after_assessment["events"]
        reason = "host reference failed validation: " + ", ".join(events or ["invalid sample"])
        return _empty_estimate("invalid", reason, bucket=bucket, evidence=evidence)
    if before_assessment["verdict"] != "within_explicit_test_policy" \
            or after_assessment["verdict"] != "within_explicit_test_policy":
        reasons = before_assessment["reasons"] + after_assessment["reasons"]
        return _empty_estimate("unqualified", "host reference evidence is incomplete: "
                               + ", ".join(dict.fromkeys(reasons)),
                               bucket=bucket, evidence=evidence)

    before_source = evidence.before.source_identity
    after_source = evidence.after.source_identity
    if before_source.state != "observed" or after_source.state != "observed" \
            or before_source.value != after_source.value:
        return _empty_estimate("unqualified", "host reference source identity is missing or changed",
                               bucket=bucket, evidence=evidence)
    if evidence.utc_scale_id.state != "observed":
        return _empty_estimate("unqualified", "host UTC scale is unknown",
                               bucket=bucket, evidence=evidence)
    if evidence.utc_scale_id.value != "unix_epoch_utc":
        return _empty_estimate("invalid", "host UTC scale is inconsistent with unix_epoch_utc",
                               bucket=bucket, evidence=evidence)
    domain = evidence.monotonic_domain_id
    if domain.state != "observed" or not isinstance(domain.value, str) or not domain.value:
        return _empty_estimate("unqualified", "host monotonic domain is unknown",
                               bucket=bucket, evidence=evidence)
    if not isinstance(transaction_monotonic_domain_id, str) \
            or transaction_monotonic_domain_id != domain.value:
        return _empty_estimate("invalid", "host reference and transaction monotonic domains differ",
                               bucket=bucket, evidence=evidence)
    if evidence.uncertainty_scope.state != "observed":
        return _empty_estimate("unqualified", "host uncertainty does not cover the full span",
                               bucket=bucket, evidence=evidence)
    if evidence.uncertainty_scope.value != "full_span":
        return _empty_estimate("unqualified", "host uncertainty is point-only, not a full-span bound",
                               bucket=bucket, evidence=evidence)

    cache = evidence.firmware_cache_age_upper_bound_ns
    if cache.state != "observed":
        return _empty_estimate("unqualified", "firmware cache age has no finite upper bound",
                               bucket=bucket, evidence=evidence)
    cache_ns = cache.value
    if isinstance(cache_ns, bool) or not isinstance(cache_ns, int) or cache_ns < 0 \
            or cache_ns > INT64_MAX:
        return _empty_estimate("invalid", "firmware cache age bound is outside int64 nanoseconds",
                               bucket=bucket, evidence=evidence)

    tx_start = _endpoint_bounds(transaction_start)
    tx_end = _endpoint_bounds(transaction_end)
    if evidence.before.fields["pairing_span_ns"].state != "observed" \
            or evidence.after.fields["pairing_span_ns"].state != "observed":
        return _empty_estimate("unqualified", "host monotonic pairing span is unknown",
                               bucket=bucket, evidence=evidence)
    ref_before = _reference_sample_mono_bounds(evidence.before)
    ref_after = _reference_sample_mono_bounds(evidence.after)
    if tx_start is None or tx_end is None or ref_before is None or ref_after is None:
        return _empty_estimate("invalid", "monotonic endpoint or pairing span is invalid/overflowed",
                               bucket=bucket, evidence=evidence)
    if tx_end[0] < tx_start[0]:
        return _empty_estimate("invalid", "transaction monotonic time moved backward",
                               bucket=bucket, evidence=evidence)
    earliest_possible_sample = tx_start[0] - cache_ns
    if earliest_possible_sample < 0 or ref_before[1] > earliest_possible_sample:
        return _empty_estimate("unqualified", "pre-sample does not cover the cache-age window",
                               bucket=bucket, evidence=evidence)
    if ref_after[0] < tx_end[1]:
        return _empty_estimate("unqualified", "post-sample does not cover the transaction end",
                               bucket=bucket, evidence=evidence)

    try:
        before_values = evidence.before.to_qso_clock_sample_fields(policy)
        after_values = evidence.after.to_qso_clock_sample_fields(policy)
    except ValueError as exc:
        return _empty_estimate("invalid", f"host reference value is outside the logger contract: {exc}",
                               bucket=bucket, evidence=evidence)
    before_pairing = _field_int(evidence.before, "pairing_span_ns")
    after_pairing = _field_int(evidence.after, "pairing_span_ns")
    if isinstance(before_pairing, bool) or not isinstance(before_pairing, int) \
            or isinstance(after_pairing, bool) or not isinstance(after_pairing, int) \
            or before_pairing < 0 or after_pairing < 0:
        return _empty_estimate("invalid", "host pairing span is invalid",
                               bucket=bucket, evidence=evidence)
    max_uncertainty_ms = max(before_values["uncertainty_ms"], after_values["uncertainty_ms"])
    max_pairing_ns = max(before_pairing, after_pairing)
    if max_uncertainty_ms > INT64_MAX // NS_PER_MS:
        return _empty_estimate("invalid", "host uncertainty conversion overflows int64 nanoseconds",
                               bucket=bucket, evidence=evidence)
    guard_ns = (max_uncertainty_ms + 1) * NS_PER_MS + max_pairing_ns
    before_utc_ms, after_utc_ms = before_values["utc_ms"], after_values["utc_ms"]
    if before_utc_ms > INT64_MAX // NS_PER_MS or after_utc_ms > INT64_MAX // NS_PER_MS:
        return _empty_estimate("invalid", "host UTC conversion overflows int64 nanoseconds",
                               bucket=bucket, evidence=evidence)
    host_lower = before_utc_ms * NS_PER_MS - guard_ns
    host_upper = after_utc_ms * NS_PER_MS + guard_ns
    if host_lower < INT64_MIN or host_upper > INT64_MAX or host_lower > host_upper:
        return _empty_estimate("invalid", "host UTC span overflows or is inconsistent",
                               bucket=bucket, evidence=evidence)

    offset_lower = bucket.lower_ns - host_upper
    offset_upper = bucket.upper_ns - host_lower
    if offset_lower < INT64_MIN or offset_upper > INT64_MAX:
        return _empty_estimate("invalid", "radio-minus-host interval overflows int64 nanoseconds",
                               bucket=bucket, evidence=evidence)
    interval = NsInterval(offset_lower, offset_upper)
    state = ("synthetic_only" if "synthetic_fixture" in (
        evidence.host_evidence_basis, evidence.cache_evidence_basis)
        else "conditional_on_declared_bounds")
    return ClockOffsetEstimate(
        state=state,
        radio_utc_minute_bucket=bucket,
        radio_minus_host=interval,
        monotonic_domain_id=domain.value,
        evidence_basis={
            "host_reference": evidence.host_evidence_basis,
            "firmware_cache_age": evidence.cache_evidence_basis,
        },
        reasons=("interval is conditional on supplied provider/analysis bounds; not independent real-world validation",),
    )


def estimate_drift_interval_ppm(
        start: ClockOffsetEstimate, end: ClockOffsetEstimate,
        elapsed_ns: NsInterval,
        elapsed_monotonic_domain_id: str) -> DriftEstimate:
    """Propagate two offset intervals into exact ppm bounds.

    `elapsed_ns` is a closed interval from the same monotonic domain. The
    result is synthetic or conditional whenever its input bounds are; it never
    converts fixture/provider claims into a real-world measured drift.
    """
    if not isinstance(start, ClockOffsetEstimate) or not isinstance(end, ClockOffsetEstimate):
        return DriftEstimate("invalid", None, None, ("offset estimate has the wrong type",))
    if not isinstance(elapsed_ns, NsInterval) or elapsed_ns.lower_ns <= 0:
        return DriftEstimate("invalid", None, None, ("elapsed monotonic interval must be positive",))
    if not isinstance(elapsed_monotonic_domain_id, str) \
            or not elapsed_monotonic_domain_id \
            or start.monotonic_domain_id != elapsed_monotonic_domain_id \
            or end.monotonic_domain_id != elapsed_monotonic_domain_id:
        return DriftEstimate("invalid", None, None,
                             ("offset and elapsed monotonic domains differ",))
    if start.radio_minus_host is None or end.radio_minus_host is None:
        return DriftEstimate("unqualified", None, None,
                             ("both offset intervals must have finite bounds",))
    accepted = {"synthetic_only", "conditional_on_declared_bounds"}
    if start.state not in accepted or end.state not in accepted:
        return DriftEstimate("unqualified", None, None,
                             ("input offset evidence is not bounded",))

    delta_lower = end.radio_minus_host.lower_ns - start.radio_minus_host.upper_ns
    delta_upper = end.radio_minus_host.upper_ns - start.radio_minus_host.lower_ns
    rates = [Fraction(delta * 1_000_000, elapsed)
             for delta in (delta_lower, delta_upper)
             for elapsed in (elapsed_ns.lower_ns, elapsed_ns.upper_ns)]
    state = ("synthetic_only" if "synthetic_only" in (start.state, end.state)
             else "conditional_on_declared_bounds")
    return DriftEstimate(state, min(rates), max(rates),
                         ("rate interval inherits input quantization, provider, and cache bounds",))
