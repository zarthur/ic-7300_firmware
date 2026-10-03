#!/usr/bin/env python3
"""Bounded, read-only IC-7300 CI-V clock observations.

The pure codec and fixture paths never touch hardware. The optional live path
requires one manually named serial port and an exact operator preflight phrase;
it never enumerates ports and contains only the three documented read queries.
Opening a serial port can still have OS-specific DTR/RTS effects, so the hardware
checklist must be completed before using the live subcommand.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time as datetime_time, timedelta, timezone
import argparse
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Callable

from clock_sample_logger import (
    ClockObservation,
    FieldValue,
    SampleRecorder,
    SystemClockProvider,
    TimeQualityPolicy,
    verify_log,
)


DEFAULT_RADIO_ADDRESS = 0x94
DEFAULT_CONTROLLER_ADDRESS = 0xE0
CI_V_HEADER = b"\xfe\xfe"
CI_V_END = 0xFD
READ_PREFIX = b"\x1a\x05"
SUBCOMMANDS = {
    "date": b"\x00\x94",
    "time": b"\x00\x95",
    "utc_offset": b"\x00\x96",
}
REPLY_DATA_LENGTHS = {"date": 4, "time": 2, "utc_offset": 3}
MAX_FRAME_BYTES = 64
MAX_RECEIVE_BYTES = 4096
MAX_QUERY_TIMEOUT_MS = 5000
MIN_QUERY_TIMEOUT_MS = 100
PREFLIGHT_ACK = (
    "I verified USB SEND, CW keying, and RTTY FSK assignments are OFF; "
    "DTR/RTS will not be used for transmit or keying."
)
MANUAL_URL = "https://www.icomfrance.com/uploads/files/produit/not-IC-7300_ENG_FM_12-en.pdf"


class CivProtocolError(ValueError):
    """A matching CI-V response violates the documented frame/data format."""


class CivTimeout(TimeoutError):
    """A query did not receive a matching reply before its bounded deadline."""


@dataclass(frozen=True)
class FailedCivTransaction:
    kind: str
    request_hex: str
    response_hex: str
    response_truncated: bool
    started: HostEndpoint
    completed: HostEndpoint
    outcome: dict[str, str]
    ignored_frame_count: int

    def as_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "request_hex": self.request_hex,
            "response_hex": self.response_hex,
            "response_truncated": self.response_truncated,
            "started": self.started.as_json(),
            "completed": self.completed.as_json(),
            "round_trip_ns": self.completed.host_monotonic_ns
            - self.started.host_monotonic_ns,
            "outcome": {"status": "failed", **self.outcome},
            "ignored_frame_count": self.ignored_frame_count,
            "raw_capture_scope": "matching reply bytes only; unrelated frame contents omitted",
        }


class CivTransactionError(RuntimeError):
    """A failed bounded query with its safe, bounded transaction evidence."""

    def __init__(self, transaction: FailedCivTransaction):
        self.transaction = transaction
        outcome = transaction.outcome
        super().__init__(f"CI-V {transaction.kind} query {outcome['code']}: {outcome['message']}")


class CivAcquisitionError(RuntimeError):
    """Partial six-query acquisition; no radio clock value is inferred."""

    def __init__(self, completed: list["CivTransaction"],
                 failed: FailedCivTransaction, not_attempted: tuple[str, ...]):
        self.completed = tuple(completed)
        self.failed = failed
        self.not_attempted = not_attempted
        super().__init__(
            f"CI-V acquisition stopped on {failed.kind}: {failed.outcome['code']}"
        )

    def as_json(self) -> dict[str, Any]:
        return {
            "model": "Icom IC-7300",
            "acquisition_state": "failed_partial",
            "completed_transactions": [
                item.as_json(include_ignored=False) for item in self.completed
            ],
            "failed_transaction": self.failed.as_json(),
            "not_attempted_queries": list(self.not_attempted),
            "radio_clock_value": None,
            "scope": "partial read-only transport evidence; no complete measurement",
        }


@dataclass(frozen=True)
class HostEndpoint:
    host_utc_ns: int
    host_monotonic_ns: int
    monotonic_bracket_span_ns: int

    def as_json(self) -> dict[str, int]:
        return {
            "host_utc_ns": self.host_utc_ns,
            "host_monotonic_ns": self.host_monotonic_ns,
            "monotonic_bracket_span_ns": self.monotonic_bracket_span_ns,
        }


@dataclass(frozen=True)
class CivTransaction:
    kind: str
    request_hex: str
    response_hex: str
    value: Any
    started: HostEndpoint
    completed: HostEndpoint
    ignored_frames: tuple[dict[str, str], ...]

    @property
    def round_trip_ns(self) -> int:
        return self.completed.host_monotonic_ns - self.started.host_monotonic_ns

    def as_json(self, *, include_ignored: bool = True) -> dict[str, Any]:
        result = {
            "kind": self.kind,
            "request_hex": self.request_hex,
            "response_hex": self.response_hex,
            "value": jsonable_value(self.value),
            "started": self.started.as_json(),
            "completed": self.completed.as_json(),
            "round_trip_ns": self.round_trip_ns,
        }
        if include_ignored:
            result["ignored_frames"] = list(self.ignored_frames)
        return result


def _check_radio_address(address: int) -> int:
    if isinstance(address, bool) or not isinstance(address, int) or not 0 <= address <= 0xDF:
        raise ValueError("radio address must be a configured CI-V address in 00..DF")
    return address


def _check_controller_address(address: int) -> int:
    if isinstance(address, bool) or not isinstance(address, int) or not 0 <= address <= 0xFC:
        raise ValueError("controller address must be a CI-V address in 00..FC")
    return address


def _check_kind(kind: str) -> str:
    if kind not in SUBCOMMANDS:
        raise ValueError(f"unsupported CI-V clock query: {kind!r}")
    return kind


def build_read_query(kind: str, radio_address: int = DEFAULT_RADIO_ADDRESS,
                     controller_address: int = DEFAULT_CONTROLLER_ADDRESS) -> bytes:
    """Build one documented 1A 05 clock read request, with no setting data."""
    kind = _check_kind(kind)
    radio_address = _check_radio_address(radio_address)
    controller_address = _check_controller_address(controller_address)
    if radio_address == controller_address:
        raise ValueError("radio and controller addresses must differ")
    return (CI_V_HEADER + bytes((radio_address, controller_address)) + READ_PREFIX
            + SUBCOMMANDS[kind] + bytes((CI_V_END,)))


def _decode_bcd_byte(raw: int, field: str) -> int:
    high, low = raw >> 4, raw & 0x0F
    if high > 9 or low > 9:
        raise CivProtocolError(f"{field} contains a malformed BCD byte 0x{raw:02x}")
    return high * 10 + low


def decode_radio_date(data: bytes) -> date:
    if len(data) != REPLY_DATA_LENGTHS["date"]:
        raise CivProtocolError(f"date reply needs 4 data bytes, got {len(data)}")
    century = _decode_bcd_byte(data[0], "date century")
    year_low = _decode_bcd_byte(data[1], "date year")
    month = _decode_bcd_byte(data[2], "date month")
    day = _decode_bcd_byte(data[3], "date day")
    if century != 20:
        raise CivProtocolError(f"IC-7300 date century must be 20, got {century}")
    try:
        return date(century * 100 + year_low, month, day)
    except ValueError as exc:
        raise CivProtocolError(f"invalid radio date: {exc}") from exc


def decode_radio_time(data: bytes) -> datetime_time:
    if len(data) != REPLY_DATA_LENGTHS["time"]:
        raise CivProtocolError(f"time reply needs 2 data bytes, got {len(data)}")
    hour = _decode_bcd_byte(data[0], "time hour")
    minute = _decode_bcd_byte(data[1], "time minute")
    try:
        return datetime_time(hour, minute)
    except ValueError as exc:
        raise CivProtocolError(f"invalid radio time: {exc}") from exc


def decode_utc_offset(data: bytes) -> timedelta:
    if len(data) != REPLY_DATA_LENGTHS["utc_offset"]:
        raise CivProtocolError(f"UTC offset reply needs 3 data bytes, got {len(data)}")
    # Section 19-13 lays out the offset payload as packed-BCD HH MM followed
    # by a direction byte (00 positive, 01 negative).
    hours = _decode_bcd_byte(data[0], "UTC offset hour")
    minutes = _decode_bcd_byte(data[1], "UTC offset minute")
    sign_byte = data[2]
    if sign_byte not in (0x00, 0x01):
        raise CivProtocolError(f"UTC offset sign must be 00 or 01, got 0x{sign_byte:02x}")
    if hours > 14 or minutes > 59 or (hours == 14 and minutes != 0):
        raise CivProtocolError("UTC offset is outside -14:00..+14:00")
    magnitude = timedelta(hours=hours, minutes=minutes)
    return magnitude if sign_byte == 0 else -magnitude


def decode_reply_payload(kind: str, data: bytes) -> Any:
    kind = _check_kind(kind)
    return {
        "date": decode_radio_date,
        "time": decode_radio_time,
        "utc_offset": decode_utc_offset,
    }[kind](data)


def split_complete_frames(stream: bytes, *, max_stream_bytes: int = MAX_RECEIVE_BYTES,
                          max_frame_bytes: int = MAX_FRAME_BYTES) -> tuple[list[bytes], bytes]:
    """Extract complete FE FE ... FD frames, retaining only a bounded suffix."""
    if len(stream) > max_stream_bytes:
        raise CivProtocolError(f"receive stream exceeds {max_stream_bytes} bytes")
    pending = bytearray(stream)
    frames: list[bytes] = []
    while True:
        start = pending.find(CI_V_HEADER)
        if start < 0:
            pending = bytearray(b"\xfe" if pending.endswith(b"\xfe") else b"")
            break
        if start:
            del pending[:start]
        # A noise byte or extended FE preamble can leave a run of three or
        # more FE bytes. Addresses exclude FE, so the last pair is the frame
        # header and earlier FE bytes are preamble/noise.
        while pending.startswith(CI_V_HEADER + b"\xfe"):
            del pending[0]
        end = pending.find(bytes((CI_V_END,)), len(CI_V_HEADER))
        if end < 0:
            if len(pending) > max_frame_bytes:
                raise CivProtocolError(f"unterminated CI-V frame exceeds {max_frame_bytes} bytes")
            break
        frame = bytes(pending[:end + 1])
        if len(frame) > max_frame_bytes:
            raise CivProtocolError(f"CI-V frame exceeds {max_frame_bytes} bytes")
        frames.append(frame)
        del pending[:end + 1]
    return frames, bytes(pending)


def _classify_frame(frame: bytes, kind: str, radio_address: int,
                    controller_address: int) -> tuple[Any | None, str]:
    request = build_read_query(kind, radio_address, controller_address)
    if frame == request:
        return None, "command_echo"
    if len(frame) < 6 or not frame.startswith(CI_V_HEADER) or frame[-1] != CI_V_END:
        return None, "malformed_unrelated_frame"
    destination, source = frame[2], frame[3]
    if destination != controller_address or source != radio_address:
        return None, "unrelated_address"
    payload = frame[4:-1]
    expected = READ_PREFIX + SUBCOMMANDS[kind]
    if payload[:len(expected)] != expected:
        return None, "unrelated_command"
    expected_payload_length = len(expected) + REPLY_DATA_LENGTHS[kind]
    if len(payload) != expected_payload_length:
        raise CivProtocolError(
            f"matching {kind} reply has {len(payload) - len(expected)} data bytes; "
            f"expected {REPLY_DATA_LENGTHS[kind]}"
        )
    try:
        value = decode_reply_payload(kind, payload[len(expected):])
    except CivProtocolError:
        raise
    return value, "matching_reply"


def _matching_reply_bytes(stream: bytes, kind: str, radio_address: int,
                          controller_address: int) -> tuple[bytes, bool]:
    """Keep only complete or partial frames identified as this query's reply."""
    header = CI_V_HEADER + bytes((controller_address, radio_address))
    command = READ_PREFIX + SUBCOMMANDS[kind]
    bounded = stream[:MAX_RECEIVE_BYTES]
    try:
        frames, remainder = split_complete_frames(bounded)
        matching = [
            frame for frame in frames
            if len(frame) >= len(header) + len(command)
            and frame.startswith(header)
            and frame[len(header):].startswith(command)
        ]
        # A partial frame is retained only after both reversed addresses and
        # at least one byte of the expected command identify it as this reply.
        if remainder.startswith(header) and len(remainder) > len(header):
            payload = remainder[len(header):]
            if command.startswith(payload) or payload.startswith(command):
                matching.append(remainder)
        raw = b"".join(matching)
        return raw, len(raw) > MAX_FRAME_BYTES
    except CivProtocolError:
        # Preserve a bounded matching prefix if an overlong frame itself caused
        # frame splitting to fail. Never serialize neighboring frame contents.
        offset = bounded.find(CI_V_HEADER)
        while offset >= 0:
            candidate = bounded[offset:]
            if (len(candidate) >= len(header) + len(command)
                    and candidate.startswith(header)
                    and candidate[len(header):].startswith(command)):
                end = candidate.find(bytes((CI_V_END,)), len(header))
                raw = candidate[:end + 1] if end >= 0 else candidate
                return raw[:MAX_FRAME_BYTES], len(raw) > MAX_FRAME_BYTES
            offset = bounded.find(CI_V_HEADER, offset + 1)
        return b"", False


def parse_reply_stream(stream: bytes, kind: str, radio_address: int = DEFAULT_RADIO_ADDRESS,
                       controller_address: int = DEFAULT_CONTROLLER_ADDRESS) -> tuple[Any, bytes, list[dict[str, str]]]:
    """Select one exact addressed reply; discard echoes and unrelated frames."""
    kind = _check_kind(kind)
    _check_radio_address(radio_address)
    _check_controller_address(controller_address)
    frames, remainder = split_complete_frames(stream)
    ignored: list[dict[str, str]] = []
    for frame in frames:
        value, classification = _classify_frame(
            frame, kind, radio_address, controller_address)
        if classification == "matching_reply":
            return value, frame, ignored
        ignored.append({"frame_hex": frame.hex(" ").upper(), "reason": classification})
    raise CivTimeout(
        "no matching CI-V reply in bounded stream; "
        f"ignored={len(ignored)}, incomplete_suffix_bytes={len(remainder)}"
    )


def _bcd_byte(value: int) -> int:
    return ((value // 10) << 4) | (value % 10)


def _reply_frame(kind: str, data: bytes, radio_address: int,
                 controller_address: int = DEFAULT_CONTROLLER_ADDRESS) -> bytes:
    """Fixture/test helper for the documented reversed-address reply shape."""
    _check_kind(kind)
    return (CI_V_HEADER + bytes((controller_address, radio_address)) + READ_PREFIX
            + SUBCOMMANDS[kind] + data + bytes((CI_V_END,)))


def capture_host_endpoint() -> HostEndpoint:
    mono_before = time.monotonic_ns()
    utc_ns = time.time_ns()
    mono_after = time.monotonic_ns()
    if mono_after < mono_before:
        raise RuntimeError("host monotonic clock moved backward while pairing endpoint")
    return HostEndpoint(utc_ns, (mono_before + mono_after) // 2,
                        mono_after - mono_before)


def _get_frame_value(frame: bytes, kind: str, radio_address: int,
                     controller_address: int) -> tuple[Any | None, str]:
    return _classify_frame(frame, kind, radio_address, controller_address)


def transact_read(transport: Any, kind: str, radio_address: int, *,
                  controller_address: int = DEFAULT_CONTROLLER_ADDRESS,
                  timeout_ms: int = 1000,
                  endpoint: Callable[[], HostEndpoint] = capture_host_endpoint,
                  monotonic_ns: Callable[[], int] = time.monotonic_ns,
                  sleeper: Callable[[float], None] = time.sleep) -> CivTransaction:
    """Send one read query and wait for its addressed response within a hard bound."""
    kind = _check_kind(kind)
    query = build_read_query(kind, radio_address, controller_address)
    if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int) \
            or not MIN_QUERY_TIMEOUT_MS <= timeout_ms <= MAX_QUERY_TIMEOUT_MS:
        raise ValueError(f"timeout_ms must be in {MIN_QUERY_TIMEOUT_MS}..{MAX_QUERY_TIMEOUT_MS}")
    started = endpoint()
    rx = bytearray()
    pending = bytearray()
    ignored: list[dict[str, str]] = []
    try:
        written = transport.write(query)
        if written is not None and written != len(query):
            raise OSError(f"short CI-V write: sent {written} of {len(query)} bytes")
        flush = getattr(transport, "flush", None)
        if flush is not None:
            flush()

        deadline = monotonic_ns() + timeout_ms * 1_000_000
        while monotonic_ns() < deadline:
            chunk = transport.read(1)
            if not chunk:
                sleeper(0.001)
                continue
            if not isinstance(chunk, (bytes, bytearray)):
                raise TypeError("CI-V transport read() must return bytes")
            rx.extend(chunk)
            if len(rx) > MAX_RECEIVE_BYTES:
                raise CivProtocolError(f"CI-V response exceeded {MAX_RECEIVE_BYTES} bytes")
            pending.extend(chunk)
            frames, suffix = split_complete_frames(bytes(pending))
            pending = bytearray(suffix)
            for frame in frames:
                value, classification = _get_frame_value(
                    frame, kind, radio_address, controller_address)
                if classification == "matching_reply":
                    completed = endpoint()
                    return CivTransaction(
                        kind=kind,
                        request_hex=query.hex(" ").upper(),
                        response_hex=frame.hex(" ").upper(),
                        value=value,
                        started=started,
                        completed=completed,
                        ignored_frames=tuple(ignored),
                    )
                ignored.append({"frame_hex": frame.hex(" ").upper(), "reason": classification})
        raise CivTimeout(
            f"timed out waiting for CI-V {kind} reply after {timeout_ms} ms; "
            f"received_bytes={len(rx)}, ignored_frames={len(ignored)}"
        )
    except Exception as exc:
        completed = endpoint()
        if isinstance(exc, CivTimeout):
            code = "timeout"
        elif isinstance(exc, CivProtocolError):
            code = "malformed_response"
        elif isinstance(exc, OSError):
            code = "transport_error"
        else:
            code = "read_error"
        raw_response, response_truncated = _matching_reply_bytes(
            bytes(rx), kind, radio_address, controller_address)
        failure = FailedCivTransaction(
            kind=kind,
            request_hex=query.hex(" ").upper(),
            response_hex=raw_response.hex(" ").upper(),
            response_truncated=response_truncated,
            started=started,
            completed=completed,
            outcome={"code": code, "error_type": type(exc).__name__,
                     "message": str(exc)},
            ignored_frame_count=len(ignored),
        )
        raise CivTransactionError(failure) from exc


def radio_utc_bucket(radio_date: date, radio_time: datetime_time,
                     offset: timedelta) -> dict[str, Any]:
    """Return the minute bucket encoded by the sequential radio fields."""
    local_minute = datetime.combine(radio_date, radio_time).replace(
        tzinfo=timezone(offset))
    utc_minute = local_minute.astimezone(timezone.utc)
    end = utc_minute + timedelta(minutes=1)
    return {
        "reported_utc_minute_start": utc_minute.isoformat(),
        "reported_utc_minute_end_exclusive": end.isoformat(),
        "precision_ms": 60_000,
        "scope": "radio-reported minute bucket; not an error bound against host UTC",
    }


def analyze_transition(date_before: date, time_before: datetime_time,
                       date_after: date, time_after: datetime_time,
                       window_elapsed_ns: int) -> dict[str, Any]:
    """Describe observed minute/date movement without assuming a sample instant."""
    unknown_latency = {
        "value": None,
        "state": "unknown",
        "reason": "IC-7300 firmware clock-cache/read latency was not measured",
    }
    if window_elapsed_ns < 0:
        return {"state": "invalid", "reason": "host monotonic window moved backward",
                "firmware_cache_latency_ms": unknown_latency}
    if window_elapsed_ns >= 60_000_000_000:
        return {
            "state": "unresolved",
            "reason": "query window spans at least one minute; multiple transitions may fit",
            "window_elapsed_ns": window_elapsed_ns,
            "firmware_cache_latency_ms": unknown_latency,
        }
    before_minute = time_before.hour * 60 + time_before.minute
    after_minute = time_after.hour * 60 + time_after.minute
    date_delta = (date_after - date_before).days
    if date_delta == 0 and after_minute == before_minute:
        state = "same_reported_minute"
        reason = "the two time reads reported the same minute"
    elif date_delta == 0 and after_minute == before_minute + 1:
        state = "minute_transition_bracketed"
        reason = "successive time reads bracketed one minute step on the same date"
    elif date_delta == 1 and before_minute == 23 * 60 + 59 and after_minute == 0:
        state = "midnight_rollover_bracketed"
        reason = "successive date/time reads bracketed the day and minute rollover"
    else:
        state = "inconsistent_or_unresolved"
        reason = "date/time reports do not describe a single ordinary minute step"
    return {
        "state": state,
        "reason": reason,
        "date_delta_days": date_delta,
        "reported_minute_delta": after_minute - before_minute,
        "window_elapsed_ns": window_elapsed_ns,
        "firmware_cache_latency_ms": unknown_latency,
    }


def jsonable_value(value: Any) -> Any:
    if isinstance(value, (date, datetime_time)):
        return value.isoformat()
    if isinstance(value, timedelta):
        total = int(value.total_seconds())
        sign = "+" if total >= 0 else "-"
        total = abs(total)
        hours, remainder = divmod(total, 3600)
        minutes = remainder // 60
        return f"{sign}{hours:02d}:{minutes:02d}"
    return value


def collect_measurement(transport: Any, radio_address: int, *,
                        controller_address: int = DEFAULT_CONTROLLER_ADDRESS,
                        timeout_ms: int = 1000,
                        transact: Callable[..., CivTransaction] = transact_read) -> dict[str, Any]:
    """Acquire two bounded date/time/offset brackets using only read commands."""
    order = ("date", "time", "utc_offset", "time", "date", "utc_offset")
    transactions: list[CivTransaction] = []
    for index, kind in enumerate(order):
        try:
            transaction = transact(
                transport, kind, radio_address,
                controller_address=controller_address, timeout_ms=timeout_ms)
        except CivTransactionError as exc:
            raise CivAcquisitionError(
                transactions, exc.transaction, order[index + 1:]) from exc
        transactions.append(transaction)
    before_date, before_time, before_offset, after_time, after_date, after_offset = (
        transaction.value for transaction in transactions)
    elapsed_ns = transactions[-1].completed.host_monotonic_ns \
        - transactions[0].started.host_monotonic_ns
    transition = analyze_transition(
        before_date, before_time, after_date, after_time, elapsed_ns)
    return {
        "model": "Icom IC-7300",
        "radio_address": f"0x{_check_radio_address(radio_address):02X}",
        "controller_address": f"0x{_check_controller_address(controller_address):02X}",
        "protocol": "CI-V command 1A 05; documented date/time/UTC offset reads only",
        "query_order": list(order),
        "transactions": [item.as_json() for item in transactions],
        "radio_report_before": {
            "date": before_date.isoformat(),
            "time": before_time.isoformat(timespec="minutes"),
            "utc_offset": jsonable_value(before_offset),
        },
        "radio_report_after": {
            "date": after_date.isoformat(),
            "time": after_time.isoformat(timespec="minutes"),
            "utc_offset": jsonable_value(after_offset),
            "reported_utc_minute_bucket": radio_utc_bucket(
                after_date, after_time, after_offset),
        },
        "transition_bracket": transition,
        "timing_limits": {
            "host_utc_reference_quality": {
                "state": "unknown",
                "reason": "stdlib wall-clock reads do not validate synchronization or expose a conservative error bound",
            },
            "firmware_cache_latency_ms": {
                "value": None,
                "state": "unknown",
                "reason": "radio firmware clock sampling/cache latency is not exposed by CI-V",
            },
            "radio_time_precision_ms": 60_000,
            "radio_to_host_utc_error_bound_ms": {
                "value": None,
                "state": "unqualified",
                "reason": "host reference quality and firmware cache latency are unknown",
            },
            "actual_radio_rtc_sync_or_set_event": {
                "state": "not_observed",
                "event_host_utc_ns": None,
                "reason": "these read-only commands do not report or perform an RTC sync/set event",
            },
            "host_reference_validation": {
                "state": "not_performed",
                "checked_at_host_utc_ns": None,
                "reason": "the measurement tool records host timestamps but does not validate the host UTC source",
            },
        },
        "source_references": [{
            "title": "Icom IC-7300 Full Manual, sections 19-2, 19-5, 19-13",
            "url": MANUAL_URL,
        }],
        "scope": "read-only observation; does not qualify native timing or authorize TX",
    }


def make_clock_observation(measurement: dict[str, Any],
                           host_provider: SystemClockProvider | None = None) -> ClockObservation:
    """Attach CI-V provenance to the existing host logger without inventing quality."""
    host_provider = host_provider or SystemClockProvider()
    host = host_provider.sample()
    metadata = {
        "provider": "host-stdlib-clock-with-read-only-IC-7300-CI-V-observation",
        "host_source_metadata": host.source_metadata,
        "radio_clock_measurement": measurement,
        "integrity_scope": "hash chain detects record edits; it is not clock attestation",
    }
    return ClockObservation(host.source_identity, host.fields, metadata)


def make_failure_clock_observation(
        acquisition: CivAcquisitionError,
        host_provider: SystemClockProvider | None = None) -> ClockObservation:
    """Log partial query evidence without inventing a radio clock sample."""
    host_provider = host_provider or SystemClockProvider()
    host = host_provider.sample()
    metadata = {
        "provider": "host-stdlib-clock-with-failed-read-only-IC-7300-CI-V-attempt",
        "host_source_metadata": host.source_metadata,
        "radio_clock_measurement": acquisition.as_json(),
        "integrity_scope": "hash chain detects record edits; it is not clock attestation",
    }
    return ClockObservation(host.source_identity, host.fields, metadata)


def append_clock_log(path: Path, observation: ClockObservation,
                     policy: TimeQualityPolicy | None = None) -> dict[str, Any]:
    """Append one non-overwriting schema-1 record verifiable by clock_sample_logger."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"refusing to overwrite existing log: {path}")
    recorder = SampleRecorder(policy or TimeQualityPolicy())
    record = recorder.record(observation)
    encoded = json.dumps(record, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8") + b"\n"
    with path.open("xb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    verification = verify_log(path)
    return {
        "path": str(path),
        "record_hash": record["record_hash"],
        "log_integrity_valid": verification["valid"],
        "assessment": record["assessment"],
        "verification": verification,
    }


def open_live_serial(port: str, baud: int, *, preflight_ack: str,
                     serial_module: Any | None = None) -> Any:
    """Open only an explicitly named port after the required human preflight."""
    if preflight_ack != PREFLIGHT_ACK:
        raise PermissionError("live CI-V requires the exact hardware preflight acknowledgment")
    if not isinstance(port, str) or not port.strip():
        raise ValueError("an explicit serial port path is required; port scanning is disabled")
    if isinstance(baud, bool) or not isinstance(baud, int) or not 300 <= baud <= 115200:
        raise ValueError("baud must be an explicit integer in 300..115200")
    if serial_module is None:
        try:
            import serial as serial_module  # type: ignore[no-redef]
        except ImportError as exc:
            raise RuntimeError("live mode requires optional pyserial; offline codec remains available") from exc
    connection = serial_module.Serial(
        port=None,
        baudrate=baud,
        timeout=0.05,
        write_timeout=0.5,
        xonxoff=False,
        rtscts=False,
        dsrdtr=False,
    )
    # Set the requested idle line state before opening, then reinforce it after.
    try:
        connection.dtr = False
        connection.rts = False
        connection.port = port
        connection.open()
        connection.dtr = False
        connection.rts = False
    except Exception:
        close = getattr(connection, "close", None)
        if close is not None:
            close()
        raise
    return connection


def parse_address(text: str) -> int:
    try:
        return int(text, 16)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("address must be hexadecimal, e.g. 94 or E0") from exc


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build-queries", help="print the three bounded offline read frames")
    build.add_argument("--radio-address", type=parse_address, default=DEFAULT_RADIO_ADDRESS,
                       help="configured radio CI-V address in hex (default 94)")
    build.add_argument("--controller-address", type=parse_address,
                       default=DEFAULT_CONTROLLER_ADDRESS)

    parse = commands.add_parser("parse-reply", help="parse one or more captured CI-V frames offline")
    parse.add_argument("--kind", choices=tuple(SUBCOMMANDS), required=True)
    parse.add_argument("--radio-address", type=parse_address, required=True)
    parse.add_argument("--controller-address", type=parse_address,
                       default=DEFAULT_CONTROLLER_ADDRESS)
    parse.add_argument("--hex", required=True, help="captured bytes as whitespace-separated hex")

    live = commands.add_parser("live", help="one bounded read-only hardware acquisition")
    live.add_argument("--port", required=True, help="explicit port path; never auto-discovered")
    live.add_argument("--radio-address", type=parse_address, required=True,
                      help="configured radio CI-V address in hex; never scanned")
    live.add_argument("--controller-address", type=parse_address,
                      default=DEFAULT_CONTROLLER_ADDRESS)
    live.add_argument("--baud", type=int, required=True,
                      help="configured CI-V baud rate; must match the radio")
    live.add_argument("--timeout-ms", type=int, default=1000,
                      help="per-query timeout, 100..5000 ms")
    live.add_argument("--output", type=Path, required=True,
                      help="new JSONL output path; an existing file is never overwritten")
    live.add_argument("--preflight-ack", required=True,
                      help=f"must exactly match: {PREFLIGHT_ACK!r}")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "build-queries":
            result = {kind: build_read_query(kind, args.radio_address,
                                             args.controller_address).hex(" ").upper()
                      for kind in SUBCOMMANDS}
            print(json.dumps(result, indent=2))
            return 0
        if args.command == "parse-reply":
            try:
                data = bytes.fromhex(args.hex)
            except ValueError as exc:
                parser.error(f"--hex must contain whitespace-separated byte values: {exc}")
            value, frame, ignored = parse_reply_stream(
                data, args.kind, args.radio_address, args.controller_address)
            print(json.dumps({"kind": args.kind, "value": jsonable_value(value),
                              "response_hex": frame.hex(" ").upper(),
                              "ignored_frames": ignored}, indent=2))
            return 0
        if not MIN_QUERY_TIMEOUT_MS <= args.timeout_ms <= MAX_QUERY_TIMEOUT_MS:
            parser.error(f"--timeout-ms must be in {MIN_QUERY_TIMEOUT_MS}..{MAX_QUERY_TIMEOUT_MS}")
        # Reject invalid addresses and the acknowledgment before any import/open.
        _check_radio_address(args.radio_address)
        _check_controller_address(args.controller_address)
        if args.radio_address == args.controller_address:
            parser.error("radio and controller addresses must differ")
        if args.output.exists():
            parser.error(f"refusing to overwrite existing output: {args.output}")
        transport = open_live_serial(args.port, args.baud,
                                     preflight_ack=args.preflight_ack)
        try:
            try:
                measurement = collect_measurement(
                    transport, args.radio_address,
                    controller_address=args.controller_address,
                    timeout_ms=args.timeout_ms,
                )
            except CivAcquisitionError as exc:
                observation = make_failure_clock_observation(exc)
                result = append_clock_log(args.output, observation)
                result["acquisition_state"] = "failed_partial"
                result["failure"] = exc.as_json()
                print(f"CI-V acquisition failed: {exc}", file=sys.stderr)
                print(json.dumps(result, indent=2))
                return 2
            observation = make_clock_observation(measurement)
            result = append_clock_log(args.output, observation)
        finally:
            transport.close()
        print(json.dumps(result, indent=2))
        return 0 if result["log_integrity_valid"] else 1
    except (OSError, ValueError, TypeError, RuntimeError, CivProtocolError, CivTimeout) as exc:
        print(f"CI-V measurement failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
