# Bounded cancellation study — 2026-09-27

## Scope and frozen candidate

This is an opt-in desktop experiment, not the default or an embedded receiver.
The owner authorized two unattended ten-minute USB-input recordings and offline
research. No serial, tuning, audio-output, PTT, settings or firmware commands are
part of these tools. No physical configuration or unchanged tuning is independently
verified. Original capture audio and original-pass messages are preserved.

`tools/capture_batch.py` requests one development recording and one reserved
holdout. Each gets at most two attempts, with child-process-group limits, explicit
quality checks and atomic final reports. An unavailable radio does not authorize
configuration changes. Capture failure is recorded and independent offline work
can continue. The launch source for the running batch was preserved in its
artifact directory before retry/interruption handling received additional tests.

Candidate `artifacts/cancellation-candidate-final-20260927/candidate.json` binds a
fresh executable, decoder/fitter/evaluator source hashes, pinned clean dependency
state, NumPy/SciPy versions, and build command. Source snapshots and compiler
output are retained beside it. The candidate was frozen before either new
recording was analyzed. No holdout-derived tuning is allowed for this candidate.
The earlier `cancellation-candidate-20260927` snapshot is superseded by this final
snapshot after an empty-study rejection guard was added, before any holdout use.

## Algorithm and bounded work

The separate `decode-payload` command exports the actual decoded ten-byte payload
and 79 encoded tones. Existing `decode`/`inspect` output contracts are unchanged.
Candidates that cannot be unpacked remain outside accepted message rows; there is
no guessing or re-encoding from displayed callsigns. The optional payload fields
increase the decoded-message structure but do not change the default algorithm.

`tools/cancellation.py` constructs the complex GFSK envelope, downconverts the
received samples around the decoded frequency, and fits at 300 samples/second.
It searches 81 frequency offsets across ±4 Hz and timing within ±240 ms of the
coarse decoder candidate, then refines with at most 100 optimizer iterations.
Complex least-squares amplitude supplies amplitude and phase. The fit receives
only the samples and decoded tones, never fixture truth or WSJT-X messages.
Timing radius and the conservative 0.65 coherence threshold were selected using
synthetic fixtures and wrong-template rejection before freezing.

Poor coherence, optimizer failure, search-boundary fits, energy increases and
residuals that would clip are rejected. Candidates are ordered by synchronization
score, a proxy rather than a calibrated received-power ordering. Cancellation
uses a separate buffer and at most two passes/eight attempted signals per slot;
skips and reached limits are explicit. The slot deadline is 120 seconds, with an
outer 150-second process-group limit. Deadline/error stops fail study completion.
A finite pass/signal cap defines the completed bounded algorithm, not exhaustive
decoding. All original-pass messages remain in the output union.

## Synthetic evidence

Fourteen fixtures include silence, three seeded noise inputs, a single signal,
14/25/50 Hz two-signal mixtures at two strength ratios, independent phase/timing
changes, fractional frequencies, and an overlap with seeded noise. The C transmit
generator provides waveforms; Python applies independent transformations. No
waveform is played to a device. Known payloads are evaluation truth only.

All fourteen frozen-candidate cases complete with exactly the expected messages.
The baseline has 12 expected per-case messages and cancellation has 19: all seven
designated overlap cases recover the weaker signal, no baseline message is lost,
and no unexpected messages appear. Repeating the complete synthetic study yields
identical behavioral reports after excluding elapsed time and resource readings.
Tests separately reject an incorrect candidate that shares synchronization and
part of its payload with the real signal, and cover deadlines and configured caps.
These fixtures do not establish a general false-positive rate or sensitivity curve.

## Recorded-audio evidence

| Corpus | Baseline reference matches | Cancellation reference matches | Gained / lost | New unconfirmed |
| --- | ---: | ---: | ---: | ---: |
| Earlier 39-slot recording, operator-reported VFO tap | 293 | 296 | 3 / 0 | 0 |
| Replacement 39-slot recording | 280 | 287 | 7 / 0 | 0 |
| New development recording, 39 slots | 299 | 300 | 1 / 0 | 0 |
| Reserved holdout recording, 39 slots | 397 | 405 | 8 / 0 | 0 |

The earlier corpus retains its one pre-existing prototype-only result. Matching
uses unique exact text per slot, not unique stations or complete RF ground truth.
The unchanged-decoder match sets reproduce the prior reports before evaluating
cancellation. Reference messages are supplied only to scoring after fitting.
The new development reference contains 421 messages and the holdout 513, so
121 and 108 reference-only messages remain respectively after cancellation. Both
new captures retained all 28,800,000 stereo frames, with zero flagged blocks or
clipping and passing host continuity/alignment checks; maximum adjacent timestamp
residuals were 21.58 and 22.42 microseconds. No retries were needed. These are
separate recording intervals in the same session, not a population sensitivity
study. Any future new prototype-only outputs must remain labeled unconfirmed.

## Resource limits and decision

Input and residual arrays alone occupy 2,880,000 bytes for a full slot, already
above the current 393,216-byte codec workspace target. The NumPy/SciPy process
also uses temporary arrays and interpreter memory. Initial isolated-worker
measurements have peak process RSS up to approximately 138 MB and recorded-slot
cancellation median times of about 0.52–0.55 seconds (maximum about 0.62 seconds).
These include fitting and decoder calls but exclude worker startup; they are host
observations under concurrent work, not target deadlines or per-fit allocation
bounds. Reports retain each measurement and process-lifetime RSS scope.

The experiment remains desktop-only. Repeated gains justify further algorithm
research, but this implementation cannot be adopted as the native radio decoder
within the current memory target. General channel response, time-varying phase,
frequency drift and interference remain unresolved modeling limits. Default
production decoding remains unchanged.

## Reproduction and evidence

Use `tools/study_cancellation.py --make-fixtures --exe EXE --output NEW_DIR` to
create deterministic inputs, and `--freeze --output NEW_DIR` to build and bind a
candidate. Evaluate with `--candidate CANDIDATE_JSON --fixtures FIXTURES_JSON`
or `--reference COMPLETE_COMPARE_RECEIVE_JSON`, always specifying a new output
directory. A held-out run uses `--role holdout`; its designation is a research
workflow promise, not access control. `--repeat PRIOR_REPORT` checks identical
behavior including fitted parameters and execution limits while excluding only
elapsed time and resource measurements. Empty suites, changed binaries/sources,
changed dependencies, and unfinished slot execution cannot produce study PASS.
Study PASS denotes completed execution; synthetic acceptance and gains/losses
are reported separately.

Current ignored evidence directories:

- `artifacts/cancellation-captures-20260927/`: bounded recordings and context.
- `artifacts/cancellation-fixtures-20260927/`: deterministic generated fixtures.
- `artifacts/cancellation-candidate-final-20260927/`: frozen source/build manifest.
- `artifacts/cancellation-synthetic-20260927/` and `cancellation-synthetic-repeated-20260927/`.
- `artifacts/cancellation-earlier-20260927/` and `cancellation-repeat-20260927/`.
- `artifacts/cancellation-development-reference-20260927/` and `cancellation-development-20260927/`.
- `artifacts/cancellation-holdout-reference-20260927/` and `cancellation-holdout-20260927/`.
- `artifacts/cancellation-recorded-repeated-20260927/` and `cancellation-holdout-repeated-20260927/`.

Station messages, raw audio, binaries and detailed fits remain local and ignored.
No firmware-installation or recovery claim follows from any of these results.


## Validation and remaining boundaries

Final synthetic profile: `artifacts/development-20260927T211837900876Z/report.json`,
74 Python tests, zero skips. Final full profile:
`artifacts/development-20260927T211836774386Z/report.json`, 95 Python tests, zero
skips; C/sanitizer suites, all three official-image reconstructions, repeated
controller report and required 25-case codec checks passed. Five cancellation-core
tests also passed using the sanitizer-built payload decoder; evidence is
`artifacts/cancellation-payload-sanitizer.log`. Known decoder sensitivity limits
remain characterized separately. The earlier full run correctly failed its
source-change gate during concurrent test editing; it was superseded by the
stable final run. Documentation was finalized after these code checks.

The parallel updater task is documented in
[the mapping/cache follow-up](updater-emulation.md#mappingcache-helper-follow-up--2026-09-27).
Original helper instructions build section descriptors and reach a strict CLIDR
read boundary at `0x200052e0`. Explicit cache stimuli reach an external-controller
read at `0x200b92d4`; scripted immediate/delayed/busy responses narrow control-flow
knowledge without qualifying cache coherency or hardware effects. Existing caller
helper substitutions remain explicit. Full validation includes those new tests.

No human intervention was required for this package. Native integration still
needs verified audio/buffer interfaces, available memory and target timing;
modified firmware additionally requires independent physical recovery evidence.
The next automated decoder task is reducing cancellation memory and work while
preserving these frozen corpus results, rather than enabling it by default.

Final behavioral repeats matched exactly on the synthetic suite, the older
replacement recording, and the new holdout. The package index is
`artifacts/cancellation-package-20260927.json`. All capture and decoder processes
have exited; all changes remain local and uncommitted.
