# Issue 17: bounded IC-7300 CI-V clock observations

**State:** bounded host-only implementation with offline protocol coverage and
two explicitly authorized read-only port opens. The 2026-10-02 trial stopped
at offset decoding; a corrected six-query acquisition on 2026-10-03 completed
and is recorded below. The radio observation remains unqualified and does not
qualify the native UTC/monotonic timing gate.

## Protocol verified against the current Icom manual

The [IC-7300 full manual](https://www.icomfrance.com/uploads/files/produit/not-IC-7300_ENG_FM_12-en.pdf)
documents the CI-V envelope and default controller/radio addresses in section
19-2. The clock entries in section 19-5 describe `1A 05 00 94` as date,
`1A 05 00 95` as time, and `1A 05 00 96` as UTC offset. The command table gives
date data from `20 00 01 01` through `20 99 12 31`, time from `00 00` through
`23 59`, and refers offset layout to section 19-13. Section 19-13 lays out
offset time as two packed-BCD bytes (`HH MM`) followed by a direction byte:
`00` positive and `01` negative. The documented magnitude limit is `14 00`.

The read request carries the command/subcommand and **no setting data**. The
date query with the default address is:

```text
FE FE 94 E0 1A 05 00 94 FD
```

The `94` in the destination-address position is the default radio address; it
must be replaced with the configured address when different. The final `00 94`
is the date command/subcommand and stays unchanged. Replies reverse addresses
(`E0 94` by default) and append four date bytes (`20 YY MM DD`), two time bytes
(`HH MM`, no seconds), or three offset bytes (`HH MM sign`). The decoder treats
the digit pairs as packed BCD, validates calendar/time ranges, and enforces the
documented ±14:00 offset limit. The CI-V table does not specify a finer
offset-minute increment.

The same manual's section 19-5 lists USB transmission-control, CW-keying, and
RTTY/FSK line settings as `00=OFF`, `01=DTR`, and `02=RTS`. Merely opening a
host serial port is not assumed safe: DTR/RTS can be assigned to SEND or
keying. The live adapter does not use those lines for its protocol, but driver
and device behavior at open still requires an operator preflight.

The manual's section 12-10 says CI-V Transceive ON outputs status when a
transceiver setting changes. The parser accepts only a reply with the
configured controller/radio addresses and exact outstanding clock subcommand;
broadcast/status frames and other commands are ignored. A transceive-status
fixture covers the broadcast-address case. On partial failure, unrelated frame
contents are omitted from the log and only their count is retained. Section
12-11 describes USB Auto baud as following the external controller's rate; the
host rate must be an explicit supported value, but the negotiated rate is not
observed by this tool.

## Software and interpretation

`tools/civ_clock_measurement.py` contains pure frame builders/parsers, a bounded
read transaction, and a single-pass acquisition that reads date/time/offset
before and after the time sample. It ignores command echoes and unrelated
frames, but rejects malformed responses for the matching address and
subcommand. The only live-capable path requires an explicit port path, radio
address, baud rate, timeout, and the exact preflight acknowledgment. It does
not discover ports. Its only transmitted frames are the three fixed read
queries; no setting, write, PTT, or tune command exists in the tool.
The optional live adapter uses pinned PySerial 3.5 from
`requirements-radio-live.txt`; the offline codec, parser, and tests do not need
that optional package, and it is not part of the firmware.

Each query records host UTC and monotonic endpoints plus pairing span and
round-trip duration. The radio reports only whole minutes; the optional
reported UTC minute bucket is the encoded radio date/time/offset, not an
accuracy bound against host UTC. The tool explicitly records host-reference
quality and firmware clock-cache latency as unknown, and leaves the
radio-to-host UTC error bound null/unqualified. It also distinguishes the
observation window from host-reference validation and an actual RTC
synchronization/set event. The CI-V reads neither report nor perform such an
event; `last_sync_monotonic_ms` remains unknown/unavailable in the existing
clock logger, so conversion to the QSO clock gate fails closed.

The JSONL record uses `clock_sample_logger.SampleRecorder` and can be verified
with:

```sh
python3 tools/clock_sample_logger.py --verify /path/to/civ-clock.jsonl
```

Offline protocol inspection is available without serial dependencies:

```sh
python3 tools/civ_clock_measurement.py build-queries --radio-address 94
python3 tools/civ_clock_measurement.py parse-reply --kind date \
  --radio-address 94 --hex 'FE FE E0 94 1A 05 00 94 20 26 10 02 FD'
```

## Host-reference interval model

The pure, offline radio-minus-host interval and drift model, its evidence requirements, and its current provider/cache limitations are documented in [`issue17-host-reference-intervals.md`](issue17-host-reference-intervals.md). It does not turn this observation into an RTC synchronization event or a qualified UTC bound.

## Hardware interaction record and future preflight

### First trial: offset decoder failure, 2026-10-02

The operator explicitly approved one bounded trial using a manually identified
USB serial adapter, at configured radio address `94h` and host rate 19200 baud.
Read-only preflight records identified the interface and documented the radio
configuration; unique local adapter identifiers and the source photos are not
included here. CI-V USB baud was Auto, for which 19200 is a supported explicit
host rate. The negotiated rate was not independently measured.

The port opened once. The date and time queries completed; the UTC-offset
query stopped because the original decoder expected `sign HH MM`, while the
manual diagram shows `HH MM sign`. The reported parser error contains only the
first offset data byte (`0x04`). The tool did not save a raw frame, transaction
endpoint timestamps, or JSONL record for this failed acquisition; none are
reconstructed here. There was no retry, the remaining queries were not sent,
and the port was closed. No transmit behavior was reported; physical no-TX
behavior was not independently verified. The HH-MM-sign decoder correction was
subsequently covered offline and used in the successful bounded acquisition
below. This historical failure record is not a timing observation.

### Successful bounded acquisition: 2026-10-03

After fresh explicit approval, one port open used the same manually identified
USB serial adapter, radio address `94h`, and host rate 19200 baud. The
acquisition completed the six read-only queries in date/time/offset,
time/date/offset order and closed the port. No write, setting, PTT, or tune
command was sent, and there was no retry. The saved, hash-chained record is
available locally and its hash chain was verified, but the raw JSONL capture
is excluded from the published changes.

Before that open, read-only OS inventory reconfirmed the manually selected USB
serial interface, and process listing showed no holder of its host device node.
The radio's connector settings were not freshly photographed or independently
rechecked during this second pass; prior preflight records are not a current
hardware guarantee.

Both brackets reported radio date `2000-01-10`, minute `19:26`, and UTC offset
`-04:00`. The encoded radio-reported UTC minute bucket was
`2000-01-10T23:26:00Z` through (exclusive) `23:27:00Z`. It is only the radio's
minute-resolution report, not a measured UTC error interval. The six query
round trips ranged from 12.273271 ms to 13.195958 ms; the whole first-query
start through last-query completion bracket was 76.255563 ms. No unrelated
frames were ignored. Per-transaction host UTC and monotonic endpoints were
recorded in the local log; the host clock source's synchronization quality and
uncertainty were not validated.

The logger marks the result **unqualified**: host reference quality is
unknown, firmware clock-cache latency is unknown, and no actual RTC sync/set
event was observed. The 12–13 ms transport round trips are not a bound on
radio sampling latency or radio-to-host UTC error. The radio's reported year
and date may warrant operator investigation, but the observation alone does
not establish why they have those values. The operator reports the radio
stayed in receive and behaved as expected while watched during this successful
trial. That is an owner-reported operational observation, not instrumented RF
evidence or proof of no transmission. This was a single supervised software
measurement, not a long-duration collection, and it does not qualify native
timing.

### Suggested next Issue 17 measurement (not performed)

First, have the operator read the radio's displayed date, time, and configured
UTC offset without opening a port or changing settings, then compare that
observation with this saved CI-V record. This checks whether the unexpected
reported 2000 date is visible on the radio without guessing its cause. For a
later accuracy measurement, use a host UTC source with documented synchronization
validity and a conservative uncertainty bound, then repeat one short,
preauthorized six-query CI-V bracket while recording the source evidence. The
radio's firmware clock-cache latency still needs an independent bound before
claiming a radio-to-host error bound; the CI-V round-trip duration cannot supply
it. No one-hour collection is needed for this next step. Any new port open
requires the checklist and fresh approval. Any correction to radio date/time is
a separate setting operation and requires separate explicit authorization.

### Stop/go checklist before any future port open

Recheck **MENU » SET > Connectors** (manual pages 12-9 through 12-11) without
changing any value. Stop if any item or identity is uncertain:

- [ ] USB SEND, USB Keying (CW), and USB Keying (RTTY) are all OFF. If any is
  DTR or RTS, do not open the port. Keep Inhibit Timer at USB Connection ON as
  a secondary safeguard, not a TX guarantee.
- [ ] USB Serial Function is CI-V. Confirm the current CI-V address and whether
  USB is linked to REMOTE. For USB Unlink, use the USB baud setting; when the
  radio is Auto, choose an explicit supported host rate (previously 19200).
- [ ] Confirm the manually intended device path and its USB identity using
  read-only OS inventory. Do not scan for ports, probe, or open a terminal.
- [ ] Confirm IC-7300 receive state, operator presence, no other controller or
  active footswitch/PTT/CW/RTTY keying path, and obtain fresh explicit approval
  for one bounded attempt. The 2026-10-03 authorization covered only that
  completed attempt and does not authorize another port open.

The adapter sets DTR and RTS false and disables RTS/CTS and DSR/DTR handshaking
before open, then sets both lines false again after open. Driver, OS, adapter,
or radio behavior during open can still create a transient line state; this is
not a physical no-transmit guarantee. The live path sends at most six reads in
date/time/offset, time/date/offset order, with a default one-second response
timeout and 500 ms write timeout. Stop on any unexpected behavior, timeout, or
malformed reply; send no corrective command and require fresh approval before
another attempt. Even a successful read is only a transport/decoding
observation: host UTC reference quality, firmware cache latency, RTC sync/set
time, and radio-to-host UTC error bound remain unknown, so native timing stays
unqualified. Any RTC date/time setting would be a separate write operation and
requires separate explicit authorization; no such setting was made here.
