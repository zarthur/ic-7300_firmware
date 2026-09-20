# Feasibility decision and integration design

**Decision: pursue Cortex-A9 integration, conditional on recovering audio APIs,
memory ownership and scheduling headroom.** Offline results support a compact
FT8 implementation, but do not yet establish a bootable custom image or real-time
operation inside Icom firmware.

## Established evidence

- Official v1.40/1.41/v1.42 images have four independently MD5-checked payloads.
  They extract successfully and reconstruct byte-identically. Only the main
  payload changes between these releases. The mirror v1.42 is identical.
- The bootloader implements the recovered LZSS format, expanding the application
  to 0x20005000. Main boot vectors map to 0x18000000; relocated loader code maps
  to 0x20004000. The application contains mixed ARM and Thumb interworking.
- Portable C generation is independently decoded by installed WSJT-X v3.0.2.
  Standard QSO messages, deterministic noise/offset/overlap tests and independent
  recorded-audio comparisons are in codec-results.json.
- Sequencing tests cover both supported exchange paths, parity, retries,
  cancellation, duplicate/old/future messages and discontinuous clocks. The
  station adapter validates reservations on every generated audio chunk.

## Resource budget and performance limits

The initial Apple M1 Pro host run measured 236,436 bytes of requested peak codec
heap, including a 167,028-byte waterfall over 200..3000 Hz. RX context is 7,816
bytes; TX context is 23,152 bytes. FFT stack arrays alone account for about
30,728 bytes at N=3840; that is not a full worst-case stack measurement. Reserve
at least 384 KiB for a first ARM prototype, then measure stack high-water marks
and DMA queues. This budget is an estimate, not an established free region.

Host post-capture decode times were approximately 3..13 ms in the first corpus;
total WAV processing approximately 11..21 ms. See the committed result revision
for exact values. Mach-O __text is roughly 39 KiB; alignment, runtime, libm and
different target code generation make this unsuitable as an exact firmware-size
prediction. Do not count macOS's virtual __PAGEZERO as executable storage.

**Deadline gap:** the current prototype consumes a complete 15-second capture.
The next FT8 transmission normally starts 0.5 seconds into the next slot, leaving
under 0.5 seconds for late decoding, sequencing and output setup. A commonly
quoted 2.36-second remainder is not automatically available with this capture
strategy. Future integration should overlap FFT processing with capture and
consider decoding shortly after the nominal signal end at 13.14 seconds, while
allowing late signals. Demonstrate the chosen deadline on the actual CPU under
scope/UI/SD load before claiming real-time feasibility. No defensible CPU timing
estimate can be obtained by scaling the M1 clock to Cortex-A9 frequency.

The compact decoder missed the deterministic -20 dB case that WSJT-X decoded;
recorded-file counts in the first run were 0/1, 4/5, and 14/23 (prototype/WSJT-X).
Those tests document a sensitivity/capability gap, not an error rate or sensitivity
curve. Candidate score is not calibrated SNR; the prototype uses an explicit
operator-supplied signal report until an estimator is validated.

## Candidate firmware interfaces

All addresses refer to v1.42 decoded RAM image. These are evidence-backed leads,
not callable APIs. Reproduce pointer searches with tools/trace.py.

| Area | Evidence | Next resolution |
|---|---|---|
| Update validation | MD5 init 0x2003c860; transform 0x2003c890; update 0x2003d38c; finalize candidate 0x2003d458 | Fully recover validation and write ordering |
| Update flow | MD5 init callers 0x2002580c, 0x20025930, 0x20025d94, 0x20026040; file seek 0x2c and 16-byte comparisons visible | Determine header/trailer tests and bank selection |
| Flash destination | At 0x20025de0..0x20025df4 selects 0x400000 or 0x10000; loader selects 0x18400000 or 0x18010000 | Possible alternate image banks; do not assume rollback/recovery |
| Receive recording | 0x20068840 loads recorder metadata; parser calls nearby 0x200686cc/0x20068744 | Trace beyond file metadata into buffers and DMA |
| Voice playback | 0x2006a90c scans eight voice files; literal load 0x2006a944 and calls 0x20068c50/0x20068dfc | Recover stream format, queue ownership, start/stop and sample rate |
| GUI/settings | Firmware Update, Time Set, PTT and voice controls have string/table references in address-map.json | Decode widget descriptors, callbacks and persistence layout |
| DSP transport | Service diagram signals and recorder paths | Recover framing, handshakes and data ownership |
| RTC/timers/scheduler | RTC identified; reset vector and startup calls mapped | Locate driver, timer frequency, task creation and priority scheme |
| TX/PTT | Voice playback and PTT UI references | Recover transmit lifecycle and cancellation callback |

Full audio buffer addresses, task priorities, allocation regions, RTC driver and
transmit entry points have not been identified. Ghidra import support is supplied
but Ghidra was unavailable; the script remains unexecuted. Capstone validates the
recorded instruction evidence and xref candidates, not a complete decompilation.

## Intended radio data flow

Existing RX PCM -> rate conversion -> streaming FFT/FT8 decode -> station list ->
selected caller -> QSO state machine -> FT8 waveform -> existing TX PCM queue.
Keep demodulation/RF DSP and FPGA behavior intact for the initial integration.

Use the portable sample/message/slot interfaces in prototype/codec.h and qso.h.
The hardware adapter owns buffers and timestamps; codec work must not block the
audio ISR. The UI owns callsign/grid, peer selection, TX parity, enable/cancel,
retry limit, audio offset and subsecond UTC adjustment. Settings layout must be
recovered before persisting new fields. Initially keep new state in RAM.

Cancellation invalidates pending waveform reservations, flushes DMA and releases
PTT. Desktop tests exercise invalidation; DMA/PTT behavior is future hardware
work. A slot change or restart does not implicitly enable TX. Explicitly confirm
output completion before advancing terminal QSO states.

## What the next phase must establish

1. Recover updater semantics, including alternate-bank behavior, and determine
   a readback/recovery procedure before the first modified boot experiment.
2. Resolve the recorder/playback interfaces and sample rate; instrument RX-only
   timestamped audio capture through the existing path.
3. Measure unused RAM, stack peaks and execution time under normal radio load.
   Confirm a 384 KiB workspace or revise the implementation based on evidence.
4. Identify a minimal UI hook and produce a visible-only firmware modification
   after a validated packer and recovery route exist.
5. Integrate native receive decoding, calibrated SNR and then timed transmission.

This phase ends with a specific feasibility boundary: codec interoperability and
container extraction are demonstrated; spare runtime resources, audio injection,
modified-image acceptance and recovery remain unproven. No image is flash-ready.
