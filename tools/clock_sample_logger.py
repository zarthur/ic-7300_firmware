#!/usr/bin/env python3
"""Foreground clock-sample capture with explicit qualification and hash-chain states.

The system provider records a paired host wall-clock/monotonic observation, but
does not assert that the wall clock is synchronized or has a known error bound.
No function in this module changes clock configuration or feeds radio I/O.
"""
from __future__ import annotations

from dataclasses import dataclass
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Iterable


SCHEMA_VERSION = 1
ZERO_HASH = '0' * 64
INT64_MAX = (1 << 63) - 1
PROTOTYPE_DISCONTINUITY_HEURISTIC_MS = 250
FIELD_NAMES = (
    'utc_ms', 'monotonic_ms', 'last_sync_monotonic_ms',
    'uncertainty_ms', 'source_valid', 'pairing_span_ns',
)
FIELD_STATES = {'observed', 'unknown', 'unavailable'}


@dataclass(frozen=True)
class FieldValue:
    value: Any
    state: str
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.state not in FIELD_STATES:
            raise ValueError(f'Unsupported field state: {self.state}')
        if self.state == 'observed':
            if self.value is None or self.reason is not None:
                raise ValueError('Observed fields need a value and no reason')
        elif self.value is not None or not self.reason:
            raise ValueError('Unknown/unavailable fields need null value and a reason')

    @classmethod
    def observed(cls, value: Any) -> 'FieldValue':
        return cls(value=value, state='observed')

    @classmethod
    def unknown(cls, reason: str) -> 'FieldValue':
        return cls(value=None, state='unknown', reason=reason)

    @classmethod
    def unavailable(cls, reason: str) -> 'FieldValue':
        return cls(value=None, state='unavailable', reason=reason)

    def as_json(self) -> dict[str, Any]:
        result = {'value': self.value, 'state': self.state}
        if self.reason is not None:
            result['reason'] = self.reason
        return result


@dataclass(frozen=True)
class ClockObservation:
    source_identity: FieldValue
    fields: dict[str, FieldValue]
    source_metadata: dict[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.source_identity, FieldValue):
            raise TypeError('Source identity must be a FieldValue')
        if self.source_identity.state == 'observed' and not isinstance(self.source_identity.value, str):
            raise TypeError('Observed source identity must be a string')
        if not isinstance(self.source_metadata, dict):
            raise TypeError('Source metadata must be a JSON object')
        missing = set(FIELD_NAMES) - set(self.fields)
        extra = set(self.fields) - set(FIELD_NAMES)
        if missing or extra:
            raise ValueError(f'Clock fields mismatch: missing={sorted(missing)}, extra={sorted(extra)}')
        if any(not isinstance(value, FieldValue) for value in self.fields.values()):
            raise TypeError('Clock fields must be FieldValue objects')

    def field_values(self) -> dict[str, dict[str, Any]]:
        return {name: self.fields[name].as_json() for name in FIELD_NAMES}

    def to_qso_clock_sample_fields(self, policy: 'TimeQualityPolicy') -> dict[str, int | bool]:
        """Return C qso_clock_sample-shaped values only when fully attested.

        Unknown or unavailable values cannot be represented by the C struct.
        Refuse conversion rather than substituting zero, true or an implicit
        freshness/uncertainty budget.
        """
        if not isinstance(policy, TimeQualityPolicy):
            raise ValueError('An explicit TimeQualityPolicy is required')
        if policy.max_sync_age_ms is None or policy.max_uncertainty_ms is None:
            raise ValueError('Clock sample is unqualified without explicit age and uncertainty limits')
        required = ('utc_ms', 'monotonic_ms', 'last_sync_monotonic_ms',
                    'uncertainty_ms', 'source_valid')
        missing = [name for name in required if self.fields[name].state != 'observed']
        if self.source_identity.state != 'observed':
            missing.append('source_identity')
        if missing:
            raise ValueError('Clock sample is unqualified; unavailable fields: ' + ', '.join(missing))
        if self.fields['source_valid'].value is not True:
            raise ValueError('Clock source is not explicitly valid')
        values = {name: self.fields[name].value for name in required}
        for name in required[:-1]:
            if isinstance(values[name], bool) or not isinstance(values[name], int):
                raise ValueError(f'{name} must be an observed integer')
            if values[name] < 0:
                raise ValueError(f'{name} must be non-negative')
            if values[name] > INT64_MAX:
                raise ValueError(f'{name} exceeds the C qso_clock_sample int64 range')
        if values['last_sync_monotonic_ms'] > values['monotonic_ms']:
            raise ValueError('last sync cannot be later than the sample monotonic time')
        if values['monotonic_ms'] - values['last_sync_monotonic_ms'] > policy.max_sync_age_ms:
            raise ValueError('clock sample exceeds the explicit maximum sync age')
        if values['uncertainty_ms'] > policy.max_uncertainty_ms:
            raise ValueError('clock sample exceeds the explicit maximum uncertainty')
        return values


class ClockProvider:
    """Small injectable interface; implementations return observations, not authority."""

    def sample(self) -> ClockObservation:
        raise NotImplementedError


class SystemClockProvider(ClockProvider):
    """Read stdlib UTC/monotonic clocks; leave sync validity and error unknown."""

    source_name = 'python-time.time_ns+time.monotonic_ns-bracketed'

    def sample(self) -> ClockObservation:
        fields: dict[str, FieldValue]
        try:
            mono_before = time.monotonic_ns()
            utc_ns = time.time_ns()
            mono_after = time.monotonic_ns()
            if mono_after < mono_before:
                raise RuntimeError('monotonic clock moved backward during pairing')
            midpoint_ns = (mono_before + mono_after) // 2
            fields = {
                'utc_ms': FieldValue.observed(utc_ns // 1_000_000),
                'monotonic_ms': FieldValue.observed(midpoint_ns // 1_000_000),
                'last_sync_monotonic_ms': FieldValue.unavailable(
                    'Python time API does not expose last successful UTC synchronization'),
                'uncertainty_ms': FieldValue.unavailable(
                    'Python time API does not expose a conservative UTC uncertainty bound'),
                'source_valid': FieldValue.unknown(
                    'successful wall-clock read does not attest synchronization validity'),
                'pairing_span_ns': FieldValue.observed(mono_after - mono_before),
            }
        except Exception as exc:
            reason = f'host clock read failed: {type(exc).__name__}: {exc}'
            fields = {
                name: FieldValue.unavailable(reason) for name in FIELD_NAMES
            }

        metadata: dict[str, Any] = {'provider': 'system-stdlib', 'clock_info': {}}
        for name in ('time', 'monotonic'):
            try:
                info = time.get_clock_info(name)
                metadata['clock_info'][name] = {
                    'implementation': info.implementation,
                    'resolution_ns': int(round(info.resolution * 1_000_000_000)),
                    'monotonic': info.monotonic,
                    'adjustable': info.adjustable,
                }
            except Exception as exc:
                metadata['clock_info'][name] = {
                    'state': 'unavailable',
                    'reason': f'{type(exc).__name__}: {exc}',
                }
        return ClockObservation(FieldValue.observed(self.source_name), fields, metadata)


def _fixture_field(name: str, raw: Any) -> FieldValue:
    if isinstance(raw, dict) and 'state' in raw:
        state = raw['state']
        value = raw.get('value')
        reason = raw.get('reason')
        return FieldValue(value=value, state=state, reason=reason)
    if raw is None:
        return FieldValue.unknown(f'fixture did not provide {name}')
    return FieldValue.observed(raw)


class InjectedClockProvider(ClockProvider):
    """Deterministic sequence provider for tests and offline fixture capture."""

    def __init__(self, source_identity: str | None, samples: Iterable[dict[str, Any]]):
        self._source_identity = (FieldValue.observed(source_identity) if source_identity
                                 else FieldValue.unknown('fixture source identity omitted'))
        self._samples = iter(samples)
        self._index = 0

    def sample(self) -> ClockObservation:
        try:
            raw = next(self._samples)
        except StopIteration as exc:
            raise ValueError('Injected clock fixture is exhausted') from exc
        if not isinstance(raw, dict):
            raise ValueError('Each injected sample must be a JSON object')
        fields = {
            name: _fixture_field(name, raw.get(name))
            for name in FIELD_NAMES
        }
        self._index += 1
        return ClockObservation(
            source_identity=self._source_identity,
            fields=fields,
            source_metadata={'provider': 'injected-fixture', 'fixture_sample': self._index},
        )


def load_fixture(path: Path) -> InjectedClockProvider:
    data = json.loads(Path(path).read_text())
    if not isinstance(data, dict) or data.get('schema_version') != SCHEMA_VERSION:
        raise ValueError('Fixture must be a clock-sample JSON object with schema_version 1')
    samples = data.get('samples')
    if not isinstance(samples, list) or not samples:
        raise ValueError('Fixture must contain a non-empty samples array')
    return InjectedClockProvider(data.get('source_identity'), samples)


@dataclass(frozen=True)
class TimeQualityPolicy:
    max_sync_age_ms: int | None = None
    max_uncertainty_ms: int | None = None
    discontinuity_heuristic_ms: int = PROTOTYPE_DISCONTINUITY_HEURISTIC_MS

    def __post_init__(self) -> None:
        for name in ('max_sync_age_ms', 'max_uncertainty_ms', 'discontinuity_heuristic_ms'):
            value = getattr(self, name)
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
                raise ValueError(f'{name} must be a non-negative integer or unset')

    def as_json(self) -> dict[str, Any]:
        return {
            'max_sync_age_ms': self.max_sync_age_ms,
            'max_uncertainty_ms': self.max_uncertainty_ms,
            'discontinuity_heuristic_ms': self.discontinuity_heuristic_ms,
            'discontinuity_limit_status': 'unqualified-prototype-heuristic-not-radio-limit',
        }


def _integer_field(observation: ClockObservation, name: str) -> int | None:
    field = observation.fields[name]
    if field.state != 'observed' or isinstance(field.value, bool) or not isinstance(field.value, int):
        return None
    return field.value


def assess_observation(observation: ClockObservation,
                       previous: ClockObservation | None,
                       policy: TimeQualityPolicy) -> dict[str, Any]:
    reasons: list[str] = []
    events: list[str] = []
    invalid = False
    unqualified = False

    if observation.source_identity.state != 'observed':
        unqualified = True
        reasons.append('source_identity_unknown')
    for name in ('utc_ms', 'monotonic_ms', 'last_sync_monotonic_ms', 'uncertainty_ms', 'source_valid'):
        field = observation.fields[name]
        if field.state != 'observed':
            unqualified = True
            reasons.append(f'{name}_{field.state}')

    source_valid = observation.fields['source_valid']
    if source_valid.state == 'observed':
        if not isinstance(source_valid.value, bool):
            invalid = True
            reasons.append('source_valid_not_boolean')
        elif source_valid.value is False:
            invalid = True
            events.append('source_invalid')
            if previous and previous.fields['source_valid'].state == 'observed' \
                    and previous.fields['source_valid'].value is True:
                events.append('source_validity_lost')

    utc = _integer_field(observation, 'utc_ms')
    monotonic = _integer_field(observation, 'monotonic_ms')
    last_sync = _integer_field(observation, 'last_sync_monotonic_ms')
    uncertainty = _integer_field(observation, 'uncertainty_ms')
    for name, value in (('utc_ms', utc), ('monotonic_ms', monotonic),
                        ('last_sync_monotonic_ms', last_sync), ('uncertainty_ms', uncertainty)):
        field = observation.fields[name]
        if field.state == 'observed' and value is None:
            invalid = True
            reasons.append(f'{name}_not_integer')
        elif value is not None and value < 0:
            invalid = True
            reasons.append(f'{name}_negative')

    sync_age = None
    if monotonic is not None and last_sync is not None:
        sync_age = monotonic - last_sync
        if sync_age < 0:
            invalid = True
            events.append('sync_epoch_in_future')
        elif policy.max_sync_age_ms is None:
            unqualified = True
            reasons.append('maximum_sync_age_policy_unset')
        elif sync_age > policy.max_sync_age_ms:
            invalid = True
            events.append('sync_estimate_stale')
    if uncertainty is not None:
        if policy.max_uncertainty_ms is None:
            unqualified = True
            reasons.append('maximum_uncertainty_policy_unset')
        elif uncertainty > policy.max_uncertainty_ms:
            invalid = True
            events.append('uncertainty_exceeds_explicit_policy')

    utc_monotonic_delta_ms = None
    if previous is not None:
        prev_utc = _integer_field(previous, 'utc_ms')
        prev_mono = _integer_field(previous, 'monotonic_ms')
        prev_sync = _integer_field(previous, 'last_sync_monotonic_ms')
        if utc is None or monotonic is None or prev_utc is None or prev_mono is None:
            unqualified = True
            reasons.append('progress_comparison_unavailable')
        else:
            delta_utc = utc - prev_utc
            delta_mono = monotonic - prev_mono
            if delta_utc < 0:
                invalid = True
                events.append('utc_moved_backward')
            if delta_mono < 0:
                invalid = True
                events.append('monotonic_moved_backward')
            if delta_utc == 0 and delta_mono == 0:
                events.append('repeated_sample')
            elif delta_utc >= 0 and delta_mono >= 0:
                utc_monotonic_delta_ms = delta_utc - delta_mono
                if abs(utc_monotonic_delta_ms) > policy.discontinuity_heuristic_ms:
                    invalid = True
                    events.append('prototype_discontinuity_heuristic_exceeded')
            if last_sync is not None and prev_sync is not None and last_sync < prev_sync:
                invalid = True
                events.append('last_sync_epoch_moved_backward')

    if invalid:
        verdict = 'invalid'
    elif unqualified:
        verdict = 'unqualified'
    else:
        verdict = 'within_explicit_test_policy'
    return {
        'verdict': verdict,
        'scope': 'observation only; never radio acceptance or TX authorization',
        'reasons': reasons,
        'events': events,
        'sync_age_ms': sync_age,
        'utc_minus_monotonic_delta_ms': utc_monotonic_delta_ms,
        'discontinuity_heuristic_ms': policy.discontinuity_heuristic_ms,
    }


def _canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode('utf-8')


class SampleRecorder:
    def __init__(self, policy: TimeQualityPolicy | None = None):
        self.policy = policy or TimeQualityPolicy()
        self.sequence = 0
        self.previous_hash = ZERO_HASH
        self.previous_observation: ClockObservation | None = None

    def record(self, observation: ClockObservation) -> dict[str, Any]:
        self.sequence += 1
        body = {
            'schema_version': SCHEMA_VERSION,
            'sequence': self.sequence,
            'source_identity': observation.source_identity.as_json(),
            'fields': observation.field_values(),
            'source_metadata': observation.source_metadata,
            'policy': self.policy.as_json(),
            'assessment': assess_observation(observation, self.previous_observation, self.policy),
            'previous_hash': self.previous_hash,
        }
        record_hash = hashlib.sha256(_canonical_json(body)).hexdigest()
        result = dict(body, record_hash=record_hash)
        self.previous_hash = record_hash
        self.previous_observation = observation
        return result


def write_log(path: Path, provider: ClockProvider, count: int = 1,
              interval_ms: int = 0, policy: TimeQualityPolicy | None = None) -> dict[str, Any]:
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 10000:
        raise ValueError('count must be between 1 and 10000')
    if isinstance(interval_ms, bool) or not isinstance(interval_ms, int) or not 0 <= interval_ms <= 3_600_000:
        raise ValueError('interval_ms must be between 0 and 3600000')
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    recorder = SampleRecorder(policy)
    with path.open('xb') as stream:
        for index in range(count):
            if index and interval_ms:
                time.sleep(interval_ms / 1000)
            record = recorder.record(provider.sample())
            stream.write(_canonical_json(record) + b'\n')
            stream.flush()
        os.fsync(stream.fileno())
    return {'path': str(path), 'records': count, 'final_hash': recorder.previous_hash}


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate JSON key: {key}')
        result[key] = value
    return result


def verify_log(path: Path) -> dict[str, Any]:
    path = Path(path)
    data = path.read_bytes()
    errors: list[str] = []
    if not data:
        return {'valid': False, 'records': 0, 'final_hash': None, 'errors': ['empty log']}
    if not data.endswith(b'\n'):
        errors.append('incomplete final line')
    lines = data.splitlines()
    expected_previous = ZERO_HASH
    final_hash = None
    for expected_sequence, line in enumerate(lines, start=1):
        try:
            record = json.loads(line, object_pairs_hook=_unique_object)
            if not isinstance(record, dict):
                raise ValueError('record is not an object')
            if record.get('schema_version') != SCHEMA_VERSION:
                raise ValueError('unsupported schema version')
            if record.get('sequence') != expected_sequence:
                raise ValueError('sequence discontinuity')
            if record.get('previous_hash') != expected_previous:
                raise ValueError('previous hash mismatch')
            record_hash = record.get('record_hash')
            if not isinstance(record_hash, str) or len(record_hash) != 64:
                raise ValueError('missing or malformed record hash')
            body = dict(record)
            body.pop('record_hash')
            actual = hashlib.sha256(_canonical_json(body)).hexdigest()
            if record_hash != actual:
                raise ValueError('record hash mismatch')
            expected_previous = record_hash
            final_hash = record_hash
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            errors.append(f'line {expected_sequence}: {exc}')
            break
    return {'valid': not errors and final_hash is not None,
            'records': len(lines), 'final_hash': final_hash, 'errors': errors,
            'integrity_scope': 'tamper-evident hash chain; not a source signature or clock attestation'}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='new JSONL file; existing files are never overwritten')
    parser.add_argument('--provider', choices=('system', 'fixture'), default='system')
    parser.add_argument('--fixture', type=Path, help='JSON fixture used only with --provider fixture')
    parser.add_argument('--count', type=int, default=1, help='foreground samples, 1..10000; default 1')
    parser.add_argument('--interval-ms', type=int, default=0, help='delay between samples, 0..3600000')
    parser.add_argument('--max-sync-age-ms', type=int,
                        help='explicit analysis policy; omitted means unknown/unqualified')
    parser.add_argument('--max-uncertainty-ms', type=int,
                        help='explicit analysis policy; omitted means unknown/unqualified')
    parser.add_argument('--verify', type=Path, help='verify an existing JSONL hash chain')
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.verify:
        try:
            result = verify_log(args.verify)
        except OSError as exc:
            print(f'cannot read log: {exc}', file=sys.stderr)
            return 2
        print(json.dumps(result, indent=2))
        return 0 if result['valid'] else 1
    if args.output is None:
        parser.error('--output is required unless --verify is used')
    if args.provider == 'fixture':
        if args.fixture is None:
            parser.error('--provider fixture requires --fixture')
        try:
            provider: ClockProvider = load_fixture(args.fixture)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            parser.error(f'cannot load fixture: {exc}')
    else:
        if args.fixture is not None:
            parser.error('--fixture requires --provider fixture')
        provider = SystemClockProvider()
    try:
        policy = TimeQualityPolicy(args.max_sync_age_ms, args.max_uncertainty_ms)
        result = write_log(args.output, provider, args.count, args.interval_ms, policy)
    except (OSError, ValueError, TypeError) as exc:
        print(f'clock capture failed: {exc}', file=sys.stderr)
        return 2
    verification = verify_log(args.output)
    result.update({'log_integrity_valid': verification['valid'],
                   'log_verification': verification})
    print(json.dumps(result, indent=2))
    return 0 if verification['valid'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
