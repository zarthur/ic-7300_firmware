# Issue 17: host-reference offset and drift intervals

`tools/clock_reference.py` is a pure offline estimator for relating a CI-V
radio-clock observation to a host UTC reference. It performs no clock reads,
serial I/O, radio setting, or QSO-gate qualification. The CI-V protocol and
operator preflight are documented in
[`issue17-civ-measurement.md`](issue17-civ-measurement.md).

## Meaning of the intervals

The radio reports a calendar date, a time to the minute, and its configured
UTC offset. The estimator converts that report to a closed UTC minute bucket;
it does not invent seconds or select the middle of the minute. The offset
interval is **radio-reported UTC minus host UTC** over the possible radio sample
time. It includes host-reference uncertainty and pairing spans, the CI-V
transaction bracket, the minute quantization, and a finite upper bound on the
age of the firmware's cached clock value.

Drift propagation takes two bounded offset intervals and a positive elapsed
monotonic interval from the same counter domain. It returns exact rational ppm
bounds. Wide minute buckets, host uncertainty, or cache age may make the result
too broad to be useful; the estimator preserves that width.

## Required evidence

`HostReferenceEvidence` reuses two `ClockObservation` records from
`clock_sample_logger.py`. A usable interval requires:

- observed, valid host UTC source identity and source-valid state at both ends;
- explicit host synchronization-age and uncertainty limits, with a finite
  uncertainty value and last host UTC synchronization time;
- a declared `unix_epoch_utc` scale, one monotonic domain shared with the CI-V
  endpoints, and pairing spans for both observations;
- an uncertainty declaration covering the full reference span, not just two
  point readings;
- reference samples bracketing the transaction and its possible cache-age
  window; and
- a finite nonnegative firmware cache-age upper bound with stated provenance.

`last_sync_monotonic_ms` describes synchronization of the **host reference**.
It is not a radio RTC set/synchronization event. The CI-V read transaction is an
observation window only; a radio setting operation is separate and is not
represented as having occurred by this estimator.

The radio's reported UTC offset is applied when converting its local
date/minute into the UTC bucket. A CI-V round-trip duration bounds transport
time only. It does not establish when the firmware refreshed or sampled the
cached RTC value, so it cannot substitute for a cache-age bound.

## Output states and current limits

The estimator returns `invalid` for inconsistent or out-of-range evidence,
`unqualified` when required bounds are missing, `synthetic_only` for fixtures,
and `conditional_on_declared_bounds` when supplied provider/static-analysis
bounds are present. It never returns a real-world “measured” or “qualified”
state; serialized results explicitly set `real_world_quality_claim` to false.

The current standard-library `SystemClockProvider` cannot provide host sync
validity, last-sync time, or conservative UTC uncertainty. The firmware cache
age is also not bounded. Therefore present real-world offset and drift remain
unqualified. Synthetic fixtures exercise interval arithmetic and failure
states only. No time-quality policy limit is recommended here, and the existing
250 ms host discontinuity threshold remains a prototype heuristic rather than
a radio acceptance criterion.

## Minimum evidence to revisit qualification

Before an on-device FT8 timing claim can use these intervals, collect
source-backed host UTC validity, last-sync age, a conservative uncertainty
bound over the full observation span, and paired UTC/monotonic endpoints. Also
establish a finite firmware-cache age bound from firmware behavior or a
separately justified measurement. Then associate the radio observation with a
coherent receive/capture epoch and apply an owner-approved timing budget. Keep
reference-observation timestamps distinct from any actual radio RTC
synchronization/set event throughout the logs.

Until those inputs exist, the model can validate calculations and reject
insufficient evidence; it cannot enable native or on-device timing.
