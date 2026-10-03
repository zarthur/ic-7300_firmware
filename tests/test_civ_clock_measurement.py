import json
from datetime import date, time as datetime_time, timedelta
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import civ_clock_measurement as civ
from clock_sample_logger import (
    ClockObservation,
    FieldValue,
    SystemClockProvider,
    TimeQualityPolicy,
    verify_log,
)


RADIO = 0x94
CONTROLLER = 0xE0


def bcd(value):
    return ((value // 10) << 4) | (value % 10)


def response(kind, data, radio=RADIO):
    prefix = civ.READ_PREFIX + civ.SUBCOMMANDS[kind]
    return (b"\xfe\xfe" + bytes((CONTROLLER, radio)) + prefix + data + b"\xfd")


class FakeClock:
    def __init__(self):
        self.mono = 10_000_000_000
        self.utc = 1_800_000_000_000_000_000

    def endpoint(self):
        self.mono += 1_000_000
        self.utc += 1_000_000
        return civ.HostEndpoint(self.utc, self.mono, 100)

    def monotonic_ns(self):
        return self.mono


class FakeTransport:
    def __init__(self, frames):
        self.frames = list(frames)
        self.pending = bytearray()
        self.writes = []

    def write(self, data):
        self.writes.append(bytes(data))
        self.pending.extend(self.frames.pop(0))
        return len(data)

    def flush(self):
        pass

    def read(self, count):
        if not self.pending:
            return b""
        result = bytes(self.pending[:count])
        del self.pending[:count]
        return result


class CivQueryTests(unittest.TestCase):
    def test_builders_match_documented_queries_and_parameterize_address(self):
        expected = {
            "date": "FE FE 94 E0 1A 05 00 94 FD",
            "time": "FE FE 94 E0 1A 05 00 95 FD",
            "utc_offset": "FE FE 94 E0 1A 05 00 96 FD",
        }
        for kind, hex_bytes in expected.items():
            self.assertEqual(civ.build_read_query(kind).hex(" ").upper(), hex_bytes)
            query = civ.build_read_query(kind, radio_address=0x88)
            self.assertEqual(query[2], 0x88)
            self.assertEqual(query[6:8], civ.SUBCOMMANDS[kind])
            self.assertEqual(query[-1], 0xFD)
            self.assertEqual(len(query), 9)

    def test_builder_rejects_invalid_or_conflicting_addresses(self):
        for address in (-1, 0xE0, 0xFD, True, 1.5):
            with self.subTest(address=address), self.assertRaises(ValueError):
                civ.build_read_query("date", radio_address=address)
        with self.assertRaises(ValueError):
            civ.build_read_query("date", radio_address=0xE0, controller_address=0xE0)
        with self.assertRaises(ValueError):
            civ.build_read_query("set_time")


class CivDataParserTests(unittest.TestCase):
    def test_bcd_date_time_and_utc_offset(self):
        self.assertEqual(civ.decode_radio_date(bytes.fromhex("20 26 10 02")),
                         date(2026, 10, 2))
        self.assertEqual(civ.decode_radio_time(bytes.fromhex("23 59")),
                         datetime_time(23, 59))
        self.assertEqual(civ.decode_utc_offset(bytes.fromhex("05 30 00")),
                         timedelta(hours=5, minutes=30))
        self.assertEqual(civ.decode_utc_offset(bytes.fromhex("03 03 00")),
                         timedelta(hours=3, minutes=3))
        self.assertEqual(civ.decode_utc_offset(bytes.fromhex("04 00 01")),
                         -timedelta(hours=4))
        # The live trial's parser error reported 0x04 as the first data byte;
        # the manual places direction last, so HH=04, MM=00, sign=00 is +04:00.
        self.assertEqual(civ.decode_utc_offset(bytes.fromhex("04 00 00")),
                         timedelta(hours=4))

    def test_offset_reply_frame_uses_hour_minute_then_direction(self):
        frame = response("utc_offset", bytes.fromhex("04 30 00"))
        value, parsed, ignored = civ.parse_reply_stream(frame, "utc_offset")
        self.assertEqual(value, timedelta(hours=4, minutes=30))
        self.assertEqual(parsed, frame)
        self.assertEqual(ignored, [])

    def test_rejects_bad_bcd_dates_times_lengths_and_offsets(self):
        malformed = (
            (civ.decode_radio_date, bytes.fromhex("2A 26 10 02")),
            (civ.decode_radio_date, bytes.fromhex("20 26 02 30")),
            (civ.decode_radio_time, bytes.fromhex("24 00")),
            (civ.decode_radio_time, bytes.fromhex("12 6A")),
            (civ.decode_utc_offset, bytes.fromhex("04 00 02")),
            (civ.decode_utc_offset, bytes.fromhex("1A 00 00")),
            (civ.decode_utc_offset, bytes.fromhex("04 6A 00")),
            (civ.decode_utc_offset, bytes.fromhex("14 05 00")),
            (civ.decode_utc_offset, bytes.fromhex("15 00 00")),
        )
        for decode, payload in malformed:
            with self.subTest(payload=payload.hex()), self.assertRaises(civ.CivProtocolError):
                decode(payload)
        for decode, payload in ((civ.decode_radio_date, b"\x20"),
                                (civ.decode_radio_time, b"\x01\x02\x03"),
                                (civ.decode_utc_offset, b"\x00\x01")):
            with self.subTest(decode=decode.__name__), self.assertRaises(civ.CivProtocolError):
                decode(payload)

    def test_reply_parser_skips_echo_unrelated_frames_and_wrong_addresses(self):
        query = civ.build_read_query("date")
        echo = query
        unrelated_command = b"\xfe\xfe\xe0\x94\x00\x00\xfd"
        transceive_status = bytes.fromhex("FE FE 00 94 00 00 00 00 00 00 FD")
        wrong_address = response("date", bytes.fromhex("20 26 10 02"), radio=0x88)
        expected = response("date", bytes.fromhex("20 26 10 02"))
        stream = (b"noise" + echo + unrelated_command + transceive_status
                  + wrong_address + expected)
        value, frame, ignored = civ.parse_reply_stream(stream, "date")
        self.assertEqual(value, date(2026, 10, 2))
        self.assertEqual(frame, expected)
        self.assertEqual([item["reason"] for item in ignored], [
            "command_echo", "unrelated_command", "unrelated_address",
            "unrelated_address",
        ])

    def test_matching_reply_with_malformed_length_fails_closed(self):
        short = response("date", bytes.fromhex("20 26 10"))
        with self.assertRaisesRegex(civ.CivProtocolError, "expected 4"):
            civ.parse_reply_stream(short, "date")

    def test_echo_and_unrelated_frames_without_reply_time_out(self):
        stream = civ.build_read_query("time") + b"\xfe\xfe\xe0\x94\x00\x00\xfd"
        with self.assertRaises(civ.CivTimeout):
            civ.parse_reply_stream(stream, "time")

    def test_stream_parser_is_bounded_and_keeps_only_incomplete_suffix(self):
        frames, tail = civ.split_complete_frames(b"noise\xfe" + response(
            "time", bytes.fromhex("12 34")))
        self.assertEqual(frames, [response("time", bytes.fromhex("12 34"))])
        self.assertEqual(tail, b"")
        with self.assertRaisesRegex(civ.CivProtocolError, "exceeds"):
            civ.split_complete_frames(b"x" * (civ.MAX_RECEIVE_BYTES + 1))
        with self.assertRaisesRegex(civ.CivProtocolError, "unterminated"):
            civ.split_complete_frames(b"\xfe\xfe" + b"x" * civ.MAX_FRAME_BYTES)


class CivAcquisitionTests(unittest.TestCase):
    def test_transaction_records_both_host_endpoints_and_ignores_echo(self):
        expected = response("time", bytes.fromhex("12 34"))
        transport = FakeTransport([civ.build_read_query("time") + expected])
        clock = FakeClock()
        # A one-byte fake read also exercises incremental frame assembly.
        transaction = civ.transact_read(
            transport, "time", RADIO, endpoint=clock.endpoint,
            monotonic_ns=clock.monotonic_ns, sleeper=lambda _seconds: None,
        )
        self.assertEqual(transaction.value, datetime_time(12, 34))
        self.assertEqual(transaction.ignored_frames[0]["reason"], "command_echo")
        self.assertGreater(transaction.completed.host_monotonic_ns,
                           transaction.started.host_monotonic_ns)
        self.assertGreater(transaction.round_trip_ns, 0)

    def test_malformed_matching_reply_logs_partial_transaction_without_unrelated_bytes(self):
        malformed = response("utc_offset", bytes.fromhex("04 00 02"))
        unrelated = bytes.fromhex("FE FE 00 94 00 00 00 00 00 00 FD")
        transport = FakeTransport([
            response("date", bytes.fromhex("20 26 10 02")),
            response("time", bytes.fromhex("12 34")),
            unrelated + malformed,
        ])
        clock = FakeClock()

        def transact(stream, kind, address, **kwargs):
            return civ.transact_read(stream, kind, address,
                                     endpoint=clock.endpoint,
                                     monotonic_ns=clock.monotonic_ns,
                                     sleeper=lambda _seconds: None,
                                     **kwargs)

        with self.assertRaises(civ.CivAcquisitionError) as caught:
            civ.collect_measurement(transport, RADIO, transact=transact)
        partial = caught.exception.as_json()
        self.assertEqual(partial["acquisition_state"], "failed_partial")
        self.assertEqual(len(partial["completed_transactions"]), 2)
        failed = partial["failed_transaction"]
        self.assertEqual(failed["outcome"]["code"], "malformed_response")
        self.assertEqual(failed["outcome"]["status"], "failed")
        self.assertEqual(failed["response_hex"], malformed.hex(" ").upper())
        self.assertFalse(failed["response_truncated"])
        self.assertEqual(failed["ignored_frame_count"], 1)
        self.assertEqual(partial["not_attempted_queries"], ["time", "date", "utc_offset"])
        for transaction in partial["completed_transactions"] + [failed]:
            self.assertIn("host_utc_ns", transaction["started"])
            self.assertIn("host_monotonic_ns", transaction["started"])
            self.assertIn("host_utc_ns", transaction["completed"])
            self.assertIn("host_monotonic_ns", transaction["completed"])

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "partial-clock.jsonl"
            result = civ.append_clock_log(
                output, civ.make_failure_clock_observation(caught.exception))
            self.assertTrue(result["log_integrity_valid"])
            self.assertTrue(verify_log(output)["valid"])
            log_text = output.read_text()
            record = json.loads(log_text)
            logged = record["source_metadata"]["radio_clock_measurement"]
            self.assertEqual(logged["failed_transaction"]["response_hex"],
                             malformed.hex(" ").upper())
            self.assertNotIn(unrelated.hex(" ").upper(), log_text)
            self.assertEqual(record["assessment"]["verdict"], "unqualified")
            self.assertEqual(record["fields"]["last_sync_monotonic_ms"]["value"], None)

    def test_timeout_logs_only_partial_matching_reply_and_endpoint_pair(self):
        partial_reply = response("utc_offset", bytes.fromhex("04 30 00"))[:-1]
        transport = FakeTransport([
            response("date", bytes.fromhex("20 26 10 02")),
            response("time", bytes.fromhex("12 34")),
            partial_reply,
        ])
        clock = FakeClock()

        def monotonic_ns():
            clock.mono += 1_000_000
            return clock.mono

        def transact(stream, kind, address, **kwargs):
            return civ.transact_read(stream, kind, address,
                                     endpoint=clock.endpoint,
                                     monotonic_ns=monotonic_ns,
                                     sleeper=lambda _seconds: None,
                                     **kwargs)

        with self.assertRaises(civ.CivAcquisitionError) as caught:
            civ.collect_measurement(transport, RADIO, timeout_ms=100,
                                    transact=transact)
        failed = caught.exception.as_json()["failed_transaction"]
        self.assertEqual(failed["outcome"]["code"], "timeout")
        self.assertEqual(failed["response_hex"], partial_reply.hex(" ").upper())
        self.assertFalse(failed["response_truncated"])
        self.assertLess(failed["started"]["host_monotonic_ns"],
                        failed["completed"]["host_monotonic_ns"])

    def test_midnight_date_rollover_is_bracketed_without_claiming_latency(self):
        frames = [
            response("date", bytes.fromhex("20 26 12 31")),
            response("time", bytes.fromhex("23 59")),
            response("utc_offset", bytes.fromhex("00 00 00")),
            response("time", bytes.fromhex("00 00")),
            response("date", bytes.fromhex("20 27 01 01")),
            response("utc_offset", bytes.fromhex("00 00 00")),
        ]
        transport = FakeTransport(frames)
        clock = FakeClock()

        def transact(stream, kind, address, **kwargs):
            return civ.transact_read(stream, kind, address,
                                     endpoint=clock.endpoint,
                                     monotonic_ns=clock.monotonic_ns,
                                     sleeper=lambda _seconds: None,
                                     **kwargs)

        measurement = civ.collect_measurement(transport, RADIO, transact=transact)
        self.assertEqual(measurement["transition_bracket"]["state"],
                         "midnight_rollover_bracketed")
        self.assertEqual(measurement["radio_report_after"]["date"], "2027-01-01")
        self.assertEqual(measurement["radio_report_after"]["time"], "00:00")
        self.assertEqual(measurement["timing_limits"]["firmware_cache_latency_ms"]["value"],
                         None)
        self.assertEqual(measurement["timing_limits"]["radio_to_host_utc_error_bound_ms"]["value"],
                         None)
        self.assertEqual(measurement["timing_limits"]["actual_radio_rtc_sync_or_set_event"]["state"],
                         "not_observed")
        self.assertEqual(transport.writes, [civ.build_read_query(kind, RADIO) for kind in (
            "date", "time", "utc_offset", "time", "date", "utc_offset")])

    def test_minute_transition_and_long_or_inconsistent_windows_are_not_overclaimed(self):
        boundary = civ.analyze_transition(date(2026, 10, 2), datetime_time(12, 34),
                                          date(2026, 10, 2), datetime_time(12, 35),
                                          2_000_000_000)
        self.assertEqual(boundary["state"], "minute_transition_bracketed")
        wrapped_without_date = civ.analyze_transition(
            date(2026, 10, 2), datetime_time(23, 59),
            date(2026, 10, 2), datetime_time(0, 0), 2_000_000_000)
        self.assertEqual(wrapped_without_date["state"], "inconsistent_or_unresolved")
        too_slow = civ.analyze_transition(
            date(2026, 10, 2), datetime_time(12, 34),
            date(2026, 10, 2), datetime_time(12, 35), 60_000_000_000)
        self.assertEqual(too_slow["state"], "unresolved")
        self.assertEqual(too_slow["firmware_cache_latency_ms"]["state"], "unknown")

    def test_radio_utc_bucket_is_a_reported_minute_not_host_accuracy(self):
        bucket = civ.radio_utc_bucket(date(2026, 10, 2), datetime_time(12, 0),
                                     timedelta(hours=-7))
        self.assertEqual(bucket["reported_utc_minute_start"], "2026-10-02T19:00:00+00:00")
        self.assertEqual(bucket["reported_utc_minute_end_exclusive"], "2026-10-02T19:01:00+00:00")
        self.assertIn("not an error bound", bucket["scope"])

    def test_existing_clock_logger_keeps_missing_quality_unknown_and_hash_verifiable(self):
        measurement = {
            "timing_limits": {
                "radio_to_host_utc_error_bound_ms": {"value": None, "state": "unqualified"},
                "actual_radio_rtc_sync_or_set_event": {"state": "not_observed"},
            },
        }

        class UnqualifiedHostProvider(SystemClockProvider):
            def sample(self):
                return ClockObservation(
                    FieldValue.observed("fixture:host-without-reference-quality"),
                    {
                        "utc_ms": FieldValue.observed(123),
                        "monotonic_ms": FieldValue.observed(456),
                        "last_sync_monotonic_ms": FieldValue.unavailable("fixture lacks last sync"),
                        "uncertainty_ms": FieldValue.unavailable("fixture lacks error bound"),
                        "source_valid": FieldValue.unknown("fixture does not attest validity"),
                        "pairing_span_ns": FieldValue.observed(100),
                    },
                    {"provider": "deterministic-fixture"},
                )

        observation = civ.make_clock_observation(measurement, UnqualifiedHostProvider())
        with self.assertRaisesRegex(ValueError, "unqualified"):
            observation.to_qso_clock_sample_fields(TimeQualityPolicy())
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "clock.jsonl"
            result = civ.append_clock_log(output, observation)
            self.assertTrue(result["log_integrity_valid"])
            self.assertTrue(verify_log(output)["valid"])
            record = json.loads(output.read_text())
            self.assertEqual(record["assessment"]["verdict"], "unqualified")
            self.assertIsNone(record["fields"]["last_sync_monotonic_ms"]["value"])
            metadata = record["source_metadata"]["radio_clock_measurement"]["timing_limits"]
            self.assertIsNone(metadata["radio_to_host_utc_error_bound_ms"]["value"])
            self.assertEqual(metadata["actual_radio_rtc_sync_or_set_event"]["state"],
                             "not_observed")

    def test_live_serial_open_requires_exact_ack_and_deasserts_control_lines_before_open(self):
        events = []

        class FakeSerial:
            def __init__(self, **kwargs):
                events.append(("init", kwargs))
                self._port = None

            @property
            def port(self):
                return self._port

            @port.setter
            def port(self, value):
                self._port = value
                events.append(("port", value))

            @property
            def dtr(self):
                return False

            @dtr.setter
            def dtr(self, value):
                events.append(("dtr", value))

            @property
            def rts(self):
                return False

            @rts.setter
            def rts(self, value):
                events.append(("rts", value))

            def open(self):
                events.append(("open", self._port))

        class FakeSerialModule:
            Serial = FakeSerial

        with self.assertRaises(PermissionError):
            civ.open_live_serial("/dev/fake-radio", 19200,
                                 preflight_ack="unchecked", serial_module=FakeSerialModule)
        self.assertEqual(events, [])
        connection = civ.open_live_serial(
            "/dev/fake-radio", 19200, preflight_ack=civ.PREFLIGHT_ACK,
            serial_module=FakeSerialModule)
        self.assertIsInstance(connection, FakeSerial)
        self.assertEqual([item[0] for item in events],
                         ["init", "dtr", "rts", "port", "open", "dtr", "rts"])
        self.assertFalse(events[1][1])
        self.assertFalse(events[2][1])
        self.assertEqual(events[3], ("port", "/dev/fake-radio"))


if __name__ == "__main__":
    unittest.main()
