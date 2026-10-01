# V2 native receive diagnostic capture — 2026-10-01

This owner-run capture adds v2 timer/SSI observations to the existing USB-D
receive-path evidence. Arthur reports the radio operated as expected after the
update, in response to a question about normal receive and no freezes or
unexpected restarts. That is owner-reported behavior for this run, not an
independent observation. It does not establish recovery, operation in other
configurations, or calibrated behavior.

Arthur also confirms this was the planned **7.074 MHz USB-D, AF-volume-minimum**
setup. He is unsure of the other settings and reports they were unchanged
between captures. This setting context is owner-reported; the file does not
encode or independently verify the controls. It supports saying that stream A
remained nonzero in the reported minimum-AF trial, but does not explain stream B
or establish a gain curve.

## Provenance and integrity

| Item | Evidence |
| --- | --- |
| Target-reported components | Main CPU 1.42, Front CPU 1.01, DSP Program 1.07, DSP Data 1.00, FPGA 1.13; matches this repository's pinned v1.42 target record |
| Candidate on SD | `IC-7300/7300_142.dat`, SHA-256 `52db937a5077bd737a324b47c602ee5ead3cf5fe88ad2fb5a936c71dbd4c9db9` |
| Pre-replacement update file, preserved locally | SHA-256 `0b1744d3d569350cf173ee91dc95abd076d465e250acb65e95c81cee494cd256`; matches candidate package's installed-v1-input identity |
| Returned WAV | `Voice/20000108/20000108_185852.wav`, 777,360 bytes, SHA-256 `a3f071d17b67d3ee0bd2063f75a109e0c875c7222dd86f029789cfc2ce4c5783` |
| Recovered storage | 114,704 bytes, SHA-256 `41564ca5b439e37045a3f370bc2e4fcd87124a7ee6bef81fc22a1bd273c3e37f` |
| Schema-3 report | `artifacts/native-capture-v2-20261001/report-v2-schema3.json`, SHA-256 `07da86e0884e2393d8256bd19b5ba3d0ef2bfcda8ce8a85b963f522628bb9d31` |

The candidate hash identifies the update file on the card, not bytes read back
from radio flash. The WAV recovers the v2 carrier, and the owner reports the
post-update test, but installed-image identity remains owner-attributed rather
than independently verified. The original WAV, settings export, candidate and
full reports remain in ignored local artifacts; this note contains derived
measurements and hashes only. The radio clock is unset, so the `20000108` path,
file name and filesystem dates are not synchronized timestamps.

## Capture and stream observations

The parser accepted a complete mono signed PCM16, 8 kHz WAV: 48.573 seconds of
audio, with the carrier beginning at WAV sample 5,076 (audio byte 10,152). It
recovered all 598 ordered and checksummed transport frames and a full capture:
512 records, sequences 0–511, status 2, 114,704 bytes. All five logged flags
were zero; both epoch snapshots remained `(2, 4, 0)`. This means no tracked
event was recorded in those records; it is not proof that no event or loss went
unobserved.

Each record contains 36 signed 16-bit samples in each extracted stream. Across
the 512 records, stream A has 18,432 samples (range −14,386 to +14,630, RMS
4,217.12, one zero, no signed-16 rails). Stream B has 18,432 zero samples.
That proves what this diagnostic copied in this capture. It does not identify
stream B as transmit, a disabled receive channel, or any other semantic lane.
Earlier v1 captures also had zero-valued B; repetition supports a consistent
observation in these trials, not an explanation for it.

The exact integer comparison finds stream A's every-sixth-sample sequence at
unity scale in ordinary recorder audio, starting at WAV sample 2,052. The
3,024 matching samples represent 504 complete records, sequences 0–503, and end
at sample 5,076 exactly where the diagnostic carrier begins. Records 504–511
remain part of the recovered capture but cannot be compared against ordinary
audio because that WAV region was replaced by the carrier. The report now keeps
the matched record range separate from the 0–511 timing-segment search range.
The tested `181/256_toward_zero` transform did not match. This is exact digital
path evidence for this recording, not analog/RF gain calibration, AGC behavior,
or a gain-versus-control curve. The nominal 47,999.91-sample/s projection divided
by six is 7,999.985 recorder samples/s, consistent with the WAV's 8 kHz format;
that comparison inherits the timer-scale assumption.

## Timer and SSI observations

The report's raw summary records these values without interpreting SSI bit
fields:

| Observation | Result across 512 records |
| --- | --- |
| Tick before equals tick after | 512 records |
| Tick increments between records | 0: 128 intervals; 1: 383 intervals |
| Raw pending word | `0xb0040080` before and after in every record; bit 6 clear |
| Counter before / after ranges | 6,025–30,477 / 6,002–30,454 |
| Counter-before minus counter-after | 23: 498; 24: 9; 25: 4; 26: 1 |
| SSICR / SSIFCR | `0x3c2b0033` / `0x000000cc`, each in all records |
| SSISR values | `0x20000000`: 49; `0x20000002`: 222; `0x20000010`: 167; `0x20000012`: 74 |
| SSIFSR values | `0x02010000`: 25; `0x03000000`: 462; `0x03000100`: 3; `0x03000101`: 22 |
| SSITDMR | `0x00000000` in all records |

The nominal projection spans 12,264,023 timer cycles across 511 record
intervals. With the parser's assumed 32 MHz timer clock and 32,001-cycle
period, that is 0.3832507 seconds, 750.0014 microseconds per block on average,
and about 47,999.91 samples per second. The counter-before/after difference is
only the spacing between those two reads; it is not total handler latency.
These are timer-relative projections, not calibrated frequency or UTC. The
snapshots follow extraction and do not timestamp the first sample in a DMA
block. SSI registers can change between individual reads, so the values do not
form an atomic status snapshot or identify frame phase.

Both observed DMA bank identifiers occur 256 times, with no adjacent repeated
bank. This supports the expected alternation in captured records but cannot
exclude an even number of missed banks. It also does not prove which component
owned a buffer at runtime, target stack headroom, or an interrupt/timing margin.

## Reproduction and disposition

With the preserved local WAV, rerun the read-only report using:

```sh
artifacts/toolchains/python311/venv/bin/python \
  tools/native_capture_v2_report.py \
  artifacts/native-capture-v2-20261001/originals/Voice/20000108/20000108_185852.wav \
  --output artifacts/native-capture-v2-20261001/report-v2-schema3-recheck.json
```

Focused regression tests:

```sh
artifacts/toolchains/python311/venv/bin/python -m unittest discover \
  -s tests -p 'test_native_capture_v2_report.py' -v
```

The focused report tests pass after schema 3 was updated to summarize raw
timer/SSI words and to distinguish a true matched-sample endpoint from the
larger eligible timing segment. The prior schema-2 report remains locally
preserved for audit and is superseded for match-range reporting.

This advances Epic #3 issue #15 with a complete v2-format receive capture and
the owner's normal-operation report. The source review documents no transmit
operation in the diagnostic path and no TX/PTT was used, but this WAV cannot
prove the identity or call graph of the image in flash. It does not close #15 or
the epic: the radio flash was not read back, wall-clock synchronization is
unresolved under #17, gain/control variation and lifecycle/restart behavior
remain incomplete, and runtime ownership/timing margins are not measured. No
new radio action was performed for this analysis.
