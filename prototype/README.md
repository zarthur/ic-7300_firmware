# Portable FT8 prototype interfaces

`codec.h` separates fixed-rate mono float PCM from the codec. Input blocks include
a first-sample index and belong to one UTC-aligned slot. Gaps, overlaps, nonfinite
samples and input beyond 15 seconds are rejected. Monitor processing retains a
spectral waterfall rather than a whole audio recording. The CLI treats WAV start
as time zero; it does not infer UTC from the filename. `time_offset_s` is the
decoder's candidate coordinate including its analysis-window delay, not a
calibrated WSJT-X DT field. `sync_score` is explicitly not SNR.

`ft8_proto inspect FILE.wav` emits the same decoded messages as `decode`, plus
one diagnostic JSON row per attempted candidate: rank/total, frequency, candidate
time, sync score, LDPC error count, unpack result and terminal stage (`ldpc`,
`crc`, `duplicate`, `unpack`, `decoded`). `ft8_rx_finish_observed` exposes the
optional observer callback; the original `ft8_rx_finish` API remains supported.
Inspection timings include diagnostic output and are not a performance benchmark.

`ft8_proto decode-payload FILE.wav` adds `payload_hex` and the 79 encoded `tones`
to accepted decoded-message rows. These come directly from the decoded payload,
not text re-encoding. The optional output supports the bounded desktop
[cancellation experiment](../research/cancellation-study.md). Neither `decode`
nor `inspect` enables cancellation, and their existing JSON output is preserved.
The decoded-message C structure now carries payload/tones, so callers must rebuild.

Offline builds may override `FT8_RX_CANDIDATES` (1–1024, default 140),
`FT8_RX_MIN_SCORE` (0–255, default 10), `FT8_RX_ITERATIONS` (1–200, default 25),
and `FT8_RX_TIME_OSR`/`FT8_RX_FREQ_OSR` (2 or 4, defaults 2). Use separate build
directories and record flags/executable hashes. Larger settings have substantial
memory/CPU costs and do not establish suitability for the radio. No receive
defaults changed as part of the live-capture investigation.

TX generates 79 symbols (151,680 samples / 12.64 seconds) in caller-sized chunks.
The WAV adapter inserts 0.5 seconds of leading silence and pads to 15 seconds.
Sampling is 12 kHz PCM16; adapting the radio's native rate requires validated
resampling, including group delay and clock accuracy.

`qso.h` is independent of the codec and platform. Initialize local callsign,
four-character grid, selected peer, operator-supplied report, slot parity and
retry limit; then explicitly enable. It supports responding to a selected CQ
with grid -> R-report -> 73, or grid -> report -> RR73. Completion means the local
terminal message finished; it does not prove the remote station logged the QSO.
CQ origination and arbitrary/hashed callsigns are deferred. Reports currently
require an operator input because calibrated SNR estimation is not implemented.

RX transitions require messages addressed to/from the configured stations, in
the immediately following opposite-parity slot, after a transmission. Duplicate,
old, future, wrong-peer, malformed and wrong-state messages are ignored. Retry
limit counts additional attempts per state. A tick in slot milliseconds 500..600
reserves transmission; missed windows are skipped. Integrators should prepare
waveforms earlier and use hardware timestamps for accurate start time.

`station.h` joins reservations and waveform generation. Each audio pull validates
the reservation generation, so cancel or a clock jump suppresses subsequent
chunks. All calls run in one serialized event loop. A hardware adapter must also
flush already-enqueued DMA samples and release PTT immediately on cancellation;
this offline prototype has no DMA/PTT backend. Call `qso_tx_finished` only after
playback actually finishes, not when generation is complete. TX generation is
not a substitute for a radio output-completion callback.

The codec allocation wrapper measures requested heap and aborts on allocation
failure, matching the host-only prototype. Before embedded use, replace upstream
monitor initialization with a checked/static workspace API. The upstream FFT
uses variable-size stack scratch. Peak requested heap excludes allocator overhead,
stack and process runtime. Single-threaded allocation instrumentation is for
measurement only.
