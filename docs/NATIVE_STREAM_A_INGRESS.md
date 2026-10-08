# Native stream-A decoder ingress — local design contract

This host-only slice prepares a decoder path for source-labeled native stream-A
PCM. It does not alter the radio image, USB query protocol, recorder allocation,
or capture ownership.

## Host block contract

`tools/native_stream_decode.py` accepts `NativeSampleBlock` values with these
fields:

- `source`: exactly `native_stream_a`.
- `sample_format`: signed little-endian PCM16.
- `stream_id`: one identifier for a single continuous segment.
- `sequence` and `first_sample_index`: consecutive block order and sample
  position in the declared source domain.
- `sample_rate_hz` and `sample_rate_basis`: an explicit rate and one of
  `measured`, `nominal`, or `synthetic`. The tool does not infer or qualify the
  rate.
- `pcm16le`: the samples in that block.

The adapter rejects mixed sources, changed stream IDs, sequence gaps, sample
index gaps or overlaps, and changing rate metadata before concatenating data.
Each segment is resampled on the host to 12 kHz. A complete 180,000-sample
decoder window is required; shorter input returns `insufficient_samples` and
does not invoke the decoder. Window positions are relative to the supplied
sample index. No UTC or FT8 slot phase is assigned.

The v2 storage adapter selects only `stream_a`, validates the existing v2
storage decoder, and gives one export a capture-relative sample index. It
requires one complete 512-record capture and rejects epoch/loss/nested-callback
flags. Separate exports get different stream IDs and are never joined by this
adapter. The SSI-observation-unavailable flag is retained as metadata; it does
not alter the captured sample words.

## Requirements for a future query-only diagnostic export

The existing v2 layout stores 36 samples per stream in each of 512 fixed
224-byte records. The maximum stream-A export is therefore 18,432 samples. At
the currently projected nominal rate near 48 kHz, that is about 0.38 seconds.
The v2 transport carries one fixed storage object; complete export does not
mean the native stream was recorded for longer. A 15-second window at 48 kHz
would require 720,000 samples, or 20,000 records in this layout. Do not enlarge
the buffer or assume repeated exports are continuous without separate memory
ownership and sample-timeline evidence.

For a useful full-window decoder input, the diagnostic task should provide:

1. Explicit `native_stream_a` labeling, signed PCM16 format, and the exact
   sample rate with its basis/provenance. Keep recorder PCM and stream B as
   separately labeled data sources.
2. A stable segment/stream ID, monotonically increasing block sequence, and
   first-sample index for every block. Report drops, overruns, resets and epoch
   changes so the host can stop at each discontinuity.
3. Enough continuous samples for at least 180,000 samples after conversion to
   12 kHz. At a 48 kHz source rate, that requires at least 720,000 source
   samples. Preserve shorter exports as separate segments; do not concatenate
   them unless the producer proves continuity across the boundary.
4. A recorder-audio reference as a separate source with its own sample rate and
   index origin, for comparison only. Any timestamp must name its clock domain
   and uncertainty; UTC should be claimed only after it is independently
   qualified.
5. Evidence that query reads use already-owned capture storage and expose
   existing samples without changing capture capacity, rearm behavior, RAM
   ownership, or PTT routing.

If the query-only path can return only the current 512-record snapshot, the
host adapter can validate and account for it but it cannot supply a complete
FT8 window. No native stream-A decoder result or on-radio behavior is claimed by
this design.
