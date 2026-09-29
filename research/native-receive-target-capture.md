# First native receive target capture — 2026-09-29

The separately approved receive diagnostic ran on the same original IC-7300 as
the display-only test. The owner reports a normal automatic restart and normal
reception at **7.074 MHz, USB-D**, with no settings changes during recording.
The recording contains a complete native capture and a directly matching segment
of ordinary receiver audio. This advances #15 beyond offline emulation; the
remaining gain/control and lifecycle requirements below still prevent closure.

## Provenance and integrity

| Artifact | SHA-256 |
| --- | --- |
| Installed candidate supplied on the SD card | `0b1744d3d569350cf173ee91dc95abd076d465e250acb65e95c81cee494cd256` |
| Original returned WAV (751,440 bytes) | `b6befa5cc134a335d681c133c41d250cbddc30176355d185dc4a77cdb08fd4c2` |
| Recovered capture storage (90,128 bytes) | `328b4feb7d81d2cd42b4ea1c9e6384f7e6ea075ea92b8705601abbf2c5cc70c4` |

Candidate source is `f8ac78bd14a27f248d8f70126591c7ae85ab147c` with the preserved
display marker. [Wrapper analysis](native-receive-wrappers.md) describes the three
hooks. The added code reads receive/timing state, copies to bounded storage and
uses existing recorder payloads; it adds no PTT or transmit operation.
The owner performs installation; there is no physical flash readback. Successful
checksummed diagnostic output establishes execution of the diagnostic path, not
a byte-for-byte readback of the whole installed image.

The local SD copy was read twice and hashed, with a matching local copy retained.
The card's firmware file still matches the approved candidate. Raw recording,
settings, firmware and generated evidence remain in ignored local artifacts.
The WAV filename's January 2000 date is not UTC evidence. Host ingestion time
and radio acquisition timestamps are different facts.

The owner suspected early card removal. Inspection finds the RIFF length exactly
matches the file, `fmt ` identifies mono PCM16 at 8 kHz, all 751,248 data bytes
are present, and a complete 140-byte LIST chunk follows them. Chunk boundaries
cover the complete file. The nominal recorded duration is 46.953 seconds.
All 470 carrier frames are ordered and checksummed; strict reconstruction yields
FULL state and contiguous record sequences 0..511. No repair or re-recording was
needed. Binary diagnostic payload is intentionally not ordinary listenable audio.

## Channel, format and gain evidence

Each stream contains 18,432 signed 16-bit samples, 36 per block. Stream A varies
from -16,518 to +14,198 with no samples at either signed rail. Every stream B
sample is zero. Silence alone does not identify B as a transmit channel, nor
establish what it contains in another operating mode.

Starting at WAV audio sample 2,052, **3,024 consecutive samples exactly equal
every sixth sample of stream A, starting at phase zero, with unity gain**.
This is an exact signed-integer comparison, not a correlation or a gain fit.
It covers 504 of the 512 native blocks. The match reaches the start of the
carrier replacement at audio byte 10,152; the remaining eight blocks cannot be
compared to ordinary audio that was replaced by diagnostic data.

This confirms A supplies the recorder's receive samples in this USB-D observation,
and corroborates the original stride-six sample selector and queue ordering.
There is no 181/256 scaling on this observed segment. It does not determine RF
calibration, DSP AGC response, AF-volume independence, squelch gating, other modes,
or the meaning of the silent B stream.

## Timing and continuity evidence

Both expected DMA end pointers occur 256 times and alternate without exception.
All snapshot tick pairs agree, OSTM0 pending bit 6 is clear in both pending reads,
and before/after counters remain inside the recovered 0..32,000 interval.
Scheduler tick increments between blocks are 0 (128 times) or 1 (383 times).

For these unambiguous stored fields, the nominal projection uses
`delta_tick * 32001 + previous_counter - next_counter`. Across the 511 intervals
it totals 12,263,967 counter cycles. Assuming the firmware's intended 32 MHz scale:

- First-to-last observation span: 0.38324896875 seconds.
- Mean block interval: 749.997982 microseconds.
- Individual intervals: 23,934..24,110 counter cycles.
- Corresponding extracted-stream rate: approximately 48,000.129 samples/s.

This is a timer-relative estimate, not an independently calibrated frequency.
The observation follows DMA extraction; it is not first-sample acquisition time.
The first-to-last span excludes the duration of the final sample block.
Before/after raw register reads differ by 23..26 counter cycles, which measures
only that snapshot window, not total capture-hook latency or stack headroom.

Contiguous diagnostic sequence numbers plus alternating bank pointers and regular
observed cadence provide useful bounded evidence. They cannot prove absence of
all acquisition loss: an even number of missed banks can preserve alternation,
and no restart epoch is carried by this diagnostic. UTC remains separate (#17).

## Reproduction and remaining requirements

`tools/native_capture_report.py` is read-only. It validates the complete WAV,
strictly recovers one carrier, reports both streams and bank order, and suppresses
its nominal timing projection for ambiguous snapshot fields or epoch jumps.
Silence is never accepted as channel-identification evidence. It reports all
matching distinctive phase-zero/stride-six recorder prefixes at unity or the
recovered 181/256 integer gain. The input and analysis sources are checked for
changes during inspection. Existing report files are not overwritten.

```sh
.venv/bin/python tools/native_capture_report.py PRIVATE_RECORDING.wav \
  --output artifacts/native-target-report.json
```

Synthetic tests cover carrier corruption, WAV truncation/duplicate data chunks,
tick rollover, pending-interrupt ambiguity, repeated banks, silence, input mutation
and exact recorder matching. They contain no target recording or firmware bytes.

Next work is to resolve AF volume, squelch and AGC influence on the native tap,
and the native stop/restart and discontinuity contract. General mode/channel
routing remains open. Runtime ownership/headroom under sustained UI/scope/SD
load is not proved by a 384-ms capture (#14). The timestamped target artifact
exists, but the broader receive-interface identification is not yet complete.
