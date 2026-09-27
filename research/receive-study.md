# Live receive corpus and decoder investigation — 2026-09-27

Subsequent bounded waveform fitting and subtraction are documented in the
[cancellation study](cancellation-study.md), including a frozen holdout evaluation.
The investigations below remain the historical baseline and rejected-parameter evidence.

## Repeat capture with controls left untouched — 2026-09-27

After reporting the VFO tap, the owner authorized a new ten-minute baseline and
stated they would leave the radio controls untouched. This replaces the earlier
recording for the baseline purpose. Unchanged tuning and frequency/mode were not
independently monitored; this is an operator-labeled session, not instrumented
proof of fixed tuning. The agent used only USB audio input.

The new capture retained **28,800,000 stereo frames** and **39 complete slots**.
Host continuity/alignment passed: zero flagged blocks, no raw or resampling
clipping, and a maximum adjacent ADC timestamp residual of **43.29 microseconds**.
Channel RMS was approximately 1,355/1,356 PCM counts, with peaks 4,687/4,693.
Absolute UTC and physical source association remain unverified.

The default prototype decoded **280** messages versus WSJT-X's **344**:
**280 matched**, **64 reference-only**, and **zero prototype-only**. All decoder
invocations completed. Of the misses, 63 had nearby candidates and one did not;
proximity alone does not identify the cause. Counts use unique text per slot.

Both previously promising experiments—100 LDPC iterations and time subdivision
4—also matched **280**, with **zero gains and zero losses** relative to the new
default baseline. Their gains on the earlier recording did not repeat here.
Both passed the no-regressions replay gate; this does not establish decoder
parity or general performance equivalence. Defaults remain unchanged.

Evidence is local and ignored:

- `artifacts/receive-repeat-20260927T203546Z/`: audio, hashes, timing, capture report
  and operator context in `session-context.json`.
- `artifacts/receive-study-20260927/repeat-baseline/report.json`: default comparison.
- `artifacts/receive-study-20260927/repeat-iter100/report.json` and
  `repeat-time4/report.json`: cached-reference comparisons on the exact same slots.

Recording and decoder processes have ended. The earlier tuning-change corpus is
preserved separately for regression testing; no slots were retrospectively
excluded without event timing evidence.

## Earlier capture and reference comparison

The owner authorized a ten-minute receive baseline after the successful antenna
retry. The input-only capture selected the unique stereo `USB Audio CODEC` at
48 kHz. No serial port, audio output, tuning, PTT or firmware interface was used.
The agent did not operate radio controls. Frequency/mode, physical source
association, antenna details and absolute UTC accuracy were not independently
verified. Host builds/analysis ran during capture; this is not a qualified radio
UI/scope/SD load scenario.

The owner subsequently confirmed a VFO tap **during this capture**, followed by
restoring the intended frequency. The exact time and affected slots are unknown.
This recording is therefore not a fixed-frequency baseline. Identical-audio
decoder comparisons and regression results remain valid, but the tuning change
adds uncertainty to explanations of individual misses. USB continuity metrics
do not detect tuning changes. The original manifest and recordings are preserved;
`session-context.json` beside the capture records this operator disclosure.

All **28,800,000 stereo frames** were retained over the requested 600 seconds.
Host continuity/alignment checks passed: zero status-flagged blocks, zero clipped
samples, and a maximum adjacent ADC timestamp residual of approximately
**23.17 microseconds**. Channel RMS was approximately 1,337/1,338 PCM counts and
peaks were 4,728/4,731. Host checks do not prove radio-internal sample continuity.
After resampling and boundary exclusion, **39 complete 15-second slots** remained.

The default prototype produced **294 decodes**, versus **340** from WSJT-X:
**293 exact per-slot matches**, **47 reference-only messages**, and **one
prototype-only message**. Counts represent unique decoded text within each slot;
repeated messages in different slots count again. WSJT-X is a comparison reference,
not exhaustive ground truth. The unmatched prototype result remains unconfirmed,
not a proven false positive. No recorded callsigns or messages are copied here.

Local evidence:

- `artifacts/receive-baseline-20260927T201438Z/`: raw/converted audio, slots,
  timestamps, capture manifest and input hashes.
- `artifacts/receive-study-20260927/long-baseline/report.json`: per-slot matches,
  misses, reference SNR/frequency/DT, nearby candidate stages, executable hashes
  and logs. All decoder invocations completed without errors.
- `artifacts/receive-study-20260927/study-summary.json`: experimental comparisons,
  per-slot gains/losses and serial timing measurements.
- `artifacts/receive-study-20260927/local-regression-manifest.json`: frozen input
  hashes and baseline match sets; private station data stays ignored.

## What the misses establish

The default candidate lists contained at most 101 entries, below the 140-entry
limit. Increasing that capacity alone therefore recovered nothing. Of 47 misses,
43 had a candidate within one 6.25 Hz tone spacing; four did not. Proximity cannot
identify a particular transmission conclusively. Aggregate candidate outcomes
were 294 decoded, 563 duplicate payloads, 1,917 LDPC failures and one CRC failure;
there were no unpack failures in this capture.

Reference SNR for the misses ranged from -24 to +5 dB, with median -11 dB;
14 were below -15 dB. Thus the gap is not limited to very weak signals. Twenty-seven
misses had another reference signal within 50 Hz, and 23 had a stronger neighbor.
This supports investigating interference handling, without proving the cause of
each individual miss.

A deterministic synthetic test provides separate evidence: two generated standard
messages 14 Hz apart, mixed at a 2:1 amplitude ratio, produce one default-prototype
decode and two WSJT-X decodes. This is now the `close_overlap` benchmark case.
Acceptance requires the stronger prototype message and both reference messages;
the weaker prototype message remains a characterization result, so future
improvement is allowed and a known limitation is not mislabeled as parity.

## Offline parameter experiments

All variants used identical saved slots and the same reference results. No further
radio access was needed. The earlier three-slot sample also remained 9/12 under
all eight variants. On the larger capture:

| Variant | Reference matches | Gained / lost vs default | Peak requested heap | Median post-capture decode |
| --- | ---: | ---: | ---: | ---: |
| Default: 140 candidates, score 10, 25 iterations, time/frequency subdivision 2 | 293 | 0 / 0 | 236,436 B | 7.60 ms |
| 280 candidates | 293 | 0 / 0 | 236,436 B | 7.70 ms |
| 560 candidates | 293 | 0 / 0 | 236,436 B | 7.63 ms |
| 100 iterations | 295 | 2 / 0 | 236,436 B | 21.47 ms |
| 560 candidates, score 5, 100 iterations | 295 | 2 / 0 | 236,436 B | 208.82 ms |
| Time subdivision 4 | 301 | 8 / 0 | 403,464 B | 14.84 ms |
| Frequency subdivision 4 | 260 | 1 / 34 | 472,584 B | 12.15 ms |
| Both subdivisions 4 | 264 | 3 / 32 | 806,640 B | 19.06 ms |
| Both 4, 560 candidates, score 5, 100 iterations | 266 | 3 / 30 | 806,640 B | 204.87 ms |

Timing used normal `decode`, one subprocess at a time over all 39 slots, and
excluded waterfall construction. These are host elapsed times, not calibrated
CPU costs or on-radio deadline measurements. Heap excludes candidate arrays,
FFT stack scratch, allocator overhead and runtime requirements. Compile flags,
source snapshots and executable hashes are retained in `variants.json` and the
ignored variant directories. The pinned third-party checkout was not modified.

**Decision: keep defaults.** Higher iterations buy two matches at increased work.
Time subdivision 4 is useful evidence for future design, but its heap alone
exceeds the current 384 KiB codec-workspace target before stack/runtime overhead.
This is not proof that the radio could never reserve more memory. Frequency
subdivision changes regress this recording. One session does not establish a
sensitivity curve or justify claiming general improvement.

## Reproduction and regression checks

`ft8_proto inspect FILE.wav` provides candidate diagnostics while preserving the
normal decoded-message output. `tools/compare_receive.py` verifies capture quality
flags and slot hashes, records misses and accepts `--reference` to reuse a complete
comparison on the same input and reference decoder. Add `--require-no-regressions`
to reject any lost per-slot baseline match even when total decode counts rise.
See the README and prototype interface documentation for command examples and
bounded experimental build settings.

The default replay reproduced all 293 matched messages. The regression gate also
correctly rejected the frequency-subdivision-4 variant's 34 losses despite its
one gain. Earlier saved/corpus files produced identical decoded records before
and after adding diagnostics. Synthetic tests cover reference parsing/completion,
input tampering and slot-inventory rejection, matching/deduplication, observer
transparency, and gains that must not hide losses. Recordings remain local;
committed regression material is original code and generated synthetic audio.

Validation evidence: `artifacts/development-20260927T202147099520Z/report.json`
(synthetic: 51 Python tests plus three sanitizer WAV tests) and
`artifacts/development-20260927T202227183941Z/report.json` (full: 68 Python tests,
C suites, sanitizers, firmware/controller checks and the expanded 22-case codec
benchmark). Both passed without skips. A subsequently added replay-gate test and
its positive/negative live-corpus checks passed separately; their reports are
`regression-replay/report.json` and `regression-rejection/report.json` under the
study directory. The latter's FAIL is the expected rejection of a regressing
experimental decoder.

A subsequent full run,
`artifacts/development-20260927T203620330356Z/report.json`, passed all 69 Python
tests with zero skips, C/sanitizer checks, image reconstruction, repeated
controller reporting and required codec benchmark checks. This includes the
latest replay-regression test.

Next decoder work: investigate interference cancellation or improved likelihood
estimation using the frozen corpus plus generated overlap fixtures, and validate
against independent recordings. Additional labeled radio-load captures and
native runtime/recovery research remain separate work; this session did not
establish on-radio FT8 feasibility. All capture and decoding processes have ended.

## Likelihood and overlap follow-up — 2026-09-27

The repeat recording's 64 reference-only messages include 17 with nonnegative
reference SNR (range -25 to +8 dB; median -6.5 dB). Its candidate attempts include
1,850 LDPC failures and one CRC failure. Nearby candidates for missed messages
include 257 LDPC failures, but also 43 decoded/duplicate candidates: proximity is
not a reliable identity match, particularly with overlapping transmissions.

Static inspection of pinned `ft8/decode.c` shows that FT8 symbol evidence is the
difference between maxima of four tone magnitudes for each bit, followed by one
variance normalization over 174 bit scores and LDPC decoding. Nine experiments
changed this evidence model in isolated generated copies: three scale factors,
three absolute caps, and three smooth-maximum temperatures. The smooth maximum
is an experimental score aggregation, not a calibrated physical likelihood.
The dependency checkout and production decoder were not changed.

| Experiment | Earlier corpus: gains / losses | Repeat corpus: gains / losses |
| --- | ---: | ---: |
| Scale 0.5 | 0 / 6 | 0 / 8 |
| Scale 0.75 | 0 / 1 | 0 / 2 |
| Scale 1.25 | 0 / 0 | 0 / 2 |
| Cap 2 | 1 / 10 | 0 / 25 |
| Cap 4 | 2 / 1 | 0 / 4 |
| Cap 6 | 1 / 1 | 0 / 1 |
| Smooth maximum, temperature 1 | 1 / 0 | 0 / 0 |
| Smooth maximum, temperature 3 | 0 / 2 | 0 / 4 |
| Smooth maximum, temperature 6 | 0 / 6 | 0 / 10 |

All counts are relative to the exact matched-message set on that corpus, not
net count differences. Both fresh baseline builds reproduced 293/280 reference
matches respectively. No experiment gained matches on the repeat corpus, so
none meets the repeated-gain adoption criterion. Keep production defaults.
The completed study's PASS means the experiments ran successfully, not that the
experimental decoder passed an adoption gate.

Six generated two-message fixtures test 14/25/50 Hz spacing and weaker/stronger
amplitude ratios of 0.25/0.5. WSJT-X decoded both known messages in all six.
Every prototype variant decoded only the stronger message at 14 and 25 Hz,
and both at 50 Hz. No unexpected synthetic messages occurred. Subtracting the
**exact known stronger waveform and amplitude** from each synthetic mixture
restored the weaker decode in all six baseline controls (and every variant).
This demonstrates interference in these fixtures; it is an oracle control, not
an implemented receiver cancellation algorithm. Real recordings do not supply
exact amplitude, phase, timing or channel response, so this result does not
establish that practical subtraction will recover any particular live miss.

Requested heap stayed at 236,436 bytes. Serial six-fixture post-capture decode medians
were approximately 5.0–5.3 ms across builds; this small sample is not a timing
benchmark and excludes waterfall construction. No target CPU, stack or memory
qualification is implied. The standard codec benchmark now retains required
isolated-weak and 50 Hz two-message controls plus the characterized 25 Hz overlap
limitation; known sensitivity limitations remain separate from regression gates.

Reproduce offline, using complete local comparison reports and a new output
folder (no radio access):

```sh
.venv/bin/python tools/study_likelihood.py \
  --reference artifacts/receive-study-20260927/long-baseline/report.json \
  --reference artifacts/receive-study-20260927/repeat-baseline/report.json \
  --output artifacts/likelihood-new-run
```

The command verifies the pinned clean dependency, builds fresh objects, records
source/compiler/command/executable/input hashes and logs, and saves an atomic
report. Each compile/decode subprocess group is bounded. `--variant` can narrow
the study; baseline is always included. References are checked against capture
and slot hashes by the existing offline replay tool. Outputs contain private
station data and must remain ignored. Local final evidence is
`artifacts/likelihood-controls-20260927/report.json`; the earlier
`likelihood-study-20260927` and `likelihood-overlap-20260927` directories preserve
preceding experiments. Their common live-data outcomes agree.

Next targeted decoder work is phase/timing/amplitude estimation for subtraction
of a decoded strong signal, first against these generated mixtures. Any real
cancellation path must preserve the original-pass messages, limit work/memory,
and survive independent recorded and noise cases before adoption. Broader
updater research remains a separate desktop workstream.

Validation for this follow-up: synthetic report
`artifacts/development-20260927T205540564878Z/report.json` passed 52 Python tests;
full report `artifacts/development-20260927T205553000922Z/report.json` passed 69.
Both had zero skips and passed their C/sanitizer stages. The full run also passed
firmware reconstruction, repeated controller reporting, and all required gates
in the expanded 25-case codec benchmark. Documentation was finalized afterward;
production codec and pinned dependency contents remain unchanged by this follow-up.
