# Automated work and receive checklist — updated 2026-09-29

## Current stock receive baseline — 2026-09-29

The owner reported the radio powered/connected in USB-D with audible FT8.
Operating frequency and mode are recorded privately as operator observations;
no CI-V polling or tuning commands were used. Exactly one stereo USB Audio CODEC
input was selected explicitly, with channel 0 used for replay. Physical source
association and unchanged settings throughout capture were not independently
monitored; filter/routing details and current component versions remain pending.

A 60-second check retained all 2,880,000 stereo frames and three complete slots.
The prototype matched 34 of 47 WSJT-X messages, with no prototype-only results.
The subsequent 600-second recording retained all 28,800,000 frames and 39 complete
slots. The prototype matched **412 of 579** reference messages, with **167
reference-only** and **zero prototype-only** results. Both replays completed
without errors. Counts are unique decoded text per slot, not unique stations or
a calibrated sensitivity measurement; different recordings cannot be compared
as if propagation were fixed.

Both captures passed host continuity/alignment checks without flagged blocks,
raw clipping or resampling clipping. The long capture's maximum adjacent ADC
timestamp residual was approximately 22.4 microseconds. Separate verification
recomputed WAV hashes/inventory, frame counts, channel statistics, callback
offsets/timing residuals and complete-slot headers/data lengths; all matched.
Host time-setting inspection required administrator access, so absolute UTC
accuracy remains unverified. These checks do not establish upstream radio sample
continuity or native CPU timing.

The executable was freshly built from clean `597deb0`, with pinned dependencies.
Replay verified unchanged inputs, binaries and source. Local evidence is retained
under `artifacts/receive-interface-20260929/` in the original evidence checkout:
`session-context.json`, `receive-baseline-provenance.json`, capture/replay folders
and independent-verification reports. Raw audio and decoded station data remain
ignored. The recording streams and decoder processes completed; no playback,
serial, settings or firmware-write commands were issued.

This completes a current host receive check with the stated labeling limits.
Current component versions, full configuration/source confirmation, ordinary
UI/update-menu observations and current readable settings-backup evidence still
belong in the exact-candidate readiness record. The
[bounded stored-audio investigation](../research/recorder-interface.md) separately
narrows the old recorder lead without claiming a native PCM interface.

## Unattended cancellation development and holdout captures

Two new 600-second recordings completed on 2026-09-27 with all 28,800,000 stereo
frames each, 39 usable slots each, no flagged blocks/clipping and passing host
continuity/alignment. No retries were required. Evidence is
`artifacts/cancellation-captures-20260927/report.json`; frequency/mode and unchanged
tuning remain unverified beyond operator context. Capture streams have ended.

A candidate frozen before either new recording was analyzed improved reference
matches from 299 to 300 on development audio (421 WSJT-X messages) and from 397 to
405 on the reserved holdout (513 WSJT-X messages). No baseline messages were lost
and no new unconfirmed messages appeared. The cancellation path remains an opt-in
desktop experiment above the current embedded memory target. See
[the cancellation study](../research/cancellation-study.md) for reproducible inputs,
limits, comparison reports and the separate updater-helper findings.

## Replacement ten-minute baseline

The owner authorized a repeat while leaving the controls untouched. Capture
`artifacts/receive-repeat-20260927T203546Z/` retained all 28,800,000 frames and
39 slots, with passing host continuity/alignment and no reported gaps/clipping.
The prototype matched 280 of WSJT-X's 344 per-slot messages, with 64 reference-only
and no prototype-only results. Both the 100-iteration and time-subdivision-4
variants reproduced the same 280 matches with no gains/losses. Defaults remain
unchanged. Frequency/mode and unchanged tuning were not independently monitored.
See [the study](../research/receive-study.md) for reports and remaining limits.
All recording and decoder processes ended; no serial, tuning, playback or TX
commands were issued by the agent.

## Completed ten-minute corpus and offline study

The subsequent owner-authorized 600-second capture completed with all 28,800,000
stereo frames, no reported gaps/clipping and 39 usable slots. The default prototype
produced 294 decodes versus WSJT-X's 340: 293 matched, 47 reference-only and one
unconfirmed prototype-only result. Eight offline variants were evaluated; defaults
remain unchanged. See [the full study](../research/receive-study.md) for evidence,
memory/time tradeoffs, the new synthetic overlap fixture and replay regression
checks. No tuning, serial, playback or TX commands were issued.

The owner confirmed a VFO tap during this recording and restoration of the
intended frequency. Its timing is unknown, so this corpus is not a fixed-frequency
baseline. The identical-audio decoder comparisons remain valid; host continuity
checks do not rule out tuning changes. See the study and capture-side
`session-context.json` for the qualification.

## FT8 reception after antenna connection — 2026-09-27

Following the antenna discussion, the owner requested another capture. A fresh
60-second recording on the same explicit USB input completed with 2,880,000
stereo frames at 48 kHz. Host continuity/alignment checks passed, with zero
flagged blocks, no clipping and approximately 3.08 microseconds maximum adjacent
ADC timestamp residual. Channel RMS increased to approximately 1,363 PCM counts
from approximately 97 in the preceding capture.

Both decoders completed without errors. The three complete 15-second slots
produced prototype/WSJT-X decode counts of **3/5, 4/4 and 2/3**, respectively:
**9 versus 12 total decodes across slots**. These counts are not unique-station
counts or a sensitivity curve. The source now contains decodable FT8, while
frequency/mode, antenna details, physical device association and absolute UTC
accuracy were not independently verified. No serial, tuning, playback or TX
commands were issued; all capture/decoder processes exited.

Evidence: `artifacts/receive-antenna-20260927T200946Z/capture.json` and
`artifacts/receive-antenna-20260927T200946Z/comparison.json`, with recordings,
hashes, timestamps and per-decoder logs in that ignored directory. This is the
first successful live FT8 comparison in these session records. The longer,
labeled receive/load scenarios remain pending.

## Successful input-only retry — 2026-09-27

The owner requested another radio-access attempt. Enumeration found exactly one
stereo input named `USB Audio CODEC`. A five-second probe and then a 60-second
capture both completed using that explicit input at 48 kHz. No serial port or
audio output was opened; no tuning, settings or firmware commands were sent.

The longer capture retained all 2,880,000 requested stereo frames. It reported no
flagged blocks or clipping and a maximum adjacent ADC timestamp residual of
approximately 2.96 microseconds. Host continuity/alignment checks passed, and
three complete host-UTC-aligned 15-second slots were exported at 12 kHz. Audio
was nonzero (channel RMS approximately 97 PCM counts; peaks below 500).

The prototype and installed WSJT-X decoder each processed all three slots with
exit code zero and no decoded messages. This establishes working host USB audio
acquisition, not FT8 sensitivity or on-radio runtime feasibility. Physical source
association, current frequency/mode/routing, signal conditions and absolute UTC
accuracy remain unverified. No cause is assigned to the earlier startup failure;
no permission or system-setting change was made by this retry.

Local evidence, including raw audio, timestamps, hashes and decoder logs:

- `artifacts/receive-retry-20260927T200323Z/capture.json` — five-second probe.
- `artifacts/receive-retry-long-20260927T200344Z/capture.json` — 60-second capture.
- `artifacts/receive-retry-long-20260927T200344Z/comparison.json` — three-slot comparison.

The next receive milestone is a source-verified, labeled FT8 recording and the
longer load scenarios below. Startup permission is no longer an observed blocker.
All streams/processes from this retry have exited; no background capture remains.

## Historical session — 2026-09-24

The following records the earlier failure. Later unattended desktop validation
and controller research are described in [NEXT_STEPS.md](NEXT_STEPS.md) and the
README; the successful retry above supersedes this session's capture blocker.

## Automated work

Desktop validation completed on the existing dirty worktree based on `1ab637b`:

- Initial `make -j4 test`: passed C codec/sequencer tests and simulation; Python
  discovered 41 tests with 20 optional research tests skipped by system Python.
- Research environment with the official-image opt-in: all 41 existing tests
  passed. After capture-tool and startup-timeout tests were added, all 46 passed
  with no skips.
- All three official images (1.40, 1.41, 1.42) passed digest, decompression and
  byte-identical reconstruction. Local report:
  `artifacts/next-baseline-firmware-results.json`.
- Updater-stage emulation completed; local report:
  `artifacts/next-updater-stages.json`. This refreshes modeled evidence; it does
  not resolve physical controller behavior or recovery.
- Independent WSJT-X corpus comparison completed; local report:
  `artifacts/next-codec-results.json`. The known -20 dB miss remains. Recorded
  corpus counts remain prototype/reference 0/1, 4/5 and 14/23. Command success
  does not mean sensitivity parity.
- Added `tools/capture_receive.py` and optional pinned `requirements-audio.txt`.
  Tests cover ambiguous/missing device refusal, full UTC-slot selection,
  timestamp/status discontinuities, passband preservation, alias rejection and
  compensated resampling delay. No serial or playback API is used.

Live capture did **not** succeed. The initial 60-second attempt stalled before
recording began and was terminated. After adding a process-level timeout, a
one-second startup probe failed within its 21-second bound and saved
`artifacts/receive-20260924-startup-check/failure.json`. No receiver samples or
live decoder comparison were obtained. Microphone permission or Core Audio
initialization was suspected, not confirmed; manual step 4 was the next unblocker
at that time. The 2026-09-27 retry succeeded without changing system settings.
Device enumeration itself succeeded, identifying one stereo USB input.
Desktop logs and source/report hashes are retained in `artifacts/automated-20260924/`.

The capture tool records stereo PCM16 at a requested 48 kHz, ADC timestamps,
status flags, sample counts, per-channel RMS/peak/clipping, hashes and host timing.
It selects one channel explicitly (default channel 0), resamples to 12 kHz and
exports only full host-UTC-aligned 15-second slots, excluding boundary transients.
It refuses aligned export after detected discontinuities or incomplete capture.
Host clock accuracy and radio-internal sample continuity remain unverified.

Implementation references: [sounddevice input streams](https://python-sounddevice.readthedocs.io/en/0.5.3/api/streams.html)
and [SciPy polyphase resampling](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.resample_poly.html).
This is host diagnostic tooling, not a real-time radio integration or TX clock.

## Manual steps: establish a labeled receive baseline

1. **Verify the physical source.** After any active capture finishes, disconnect
   only the radio's USB cable, run the listing command below, reconnect it and
   list again. Confirm the stereo USB Audio CODEC input disappears/reappears.
   Record that result and the current input name. This does not require opening
   the radio or changing firmware. Stop if multiple indistinguishable inputs
   remain; the tool intentionally refuses ambiguity.
2. **Check the radio configuration.** Record the displayed firmware, selected
   receive frequency, mode/filter, USB audio routing and output level. For a
   meaningful FT8 comparison, select an active FT8 receive signal and verify
   that receiver audio is routed to USB. These settings were not inferred from
   the USB device name. Keep other control/playback applications disconnected.
   Do not press PTT or enable automatic transmission.
3. **Before any future serial session**, verify USB SEND OFF, both USB keying
   options OFF, and the previously used connection-inhibit setting. Record
   changes since the earlier read session. The capture commands below do not
   open serial and do not require a new CI-V session.
4. **Handle macOS audio permission if prompted.** Allow microphone/input access
   for the process running capture only if you intend to record the receiver.
   If access was denied, enable that application in System Settings → Privacy
   & Security → Microphone and restart it as needed. Do not substitute a default
   microphone when USB acquisition fails.
5. **Check host time synchronization.** In macOS Date & Time, verify automatic
   time is enabled. Record the time source and any known uncertainty; this alone
   does not qualify subsecond UTC accuracy for future transmission.
6. **Run the four scenarios below.** Before each command, set the indicated radio
   controls and record them. Remain present; stop the command with Control-C if
   radio behavior is unexpected. A canceled run is incomplete and must be rerun
   into a new directory. Do not power-cycle or alter firmware.
7. **Review results.** Check `capture.json` for completeness, continuity, clipping
   and nonzero audio; inspect `comparison.json` and decoder logs. No decodes can
   reflect tuning, propagation, silence or decoder limits. Record actual scope/UI
   activity and SD status rather than assuming command success proves them.

Run commands from the repository root. Dependencies are already installed in the
project `.venv`; a fresh environment uses:

```sh
.venv/bin/python -m pip install -r requirements-audio.txt
.venv/bin/python tools/capture_receive.py --list
```

Each command records ten minutes, then compares exported slots. Output directories
must be new; choose a new suffix for repeated runs.

| Scenario | Operator steps before/during capture | Output directory |
| --- | --- | --- |
| Steady receive | Set and record the receive configuration; leave controls stable | `artifacts/rx-steady-01` |
| Scope/UI | Use normal scope and UI controls throughout; log the actions/times | `artifacts/rx-scope-01` |
| SD recording | Ensure card space, start stock receive recording, confirm recording indication; stop recording after capture | `artifacts/rx-sd-01` |
| Combined | Start receive recording, operate scope/UI, record actions; stop recording afterward | `artifacts/rx-combined-01` |

```sh
.venv/bin/python tools/capture_receive.py --device-name 'USB Audio CODEC' --seconds 600 --output artifacts/rx-steady-01 --jt9 /Applications/wsjtx.app/Contents/MacOS/jt9
.venv/bin/python tools/capture_receive.py --device-name 'USB Audio CODEC' --seconds 600 --output artifacts/rx-scope-01 --jt9 /Applications/wsjtx.app/Contents/MacOS/jt9
.venv/bin/python tools/capture_receive.py --device-name 'USB Audio CODEC' --seconds 600 --output artifacts/rx-sd-01 --jt9 /Applications/wsjtx.app/Contents/MacOS/jt9
.venv/bin/python tools/capture_receive.py --device-name 'USB Audio CODEC' --seconds 600 --output artifacts/rx-combined-01 --jt9 /Applications/wsjtx.app/Contents/MacOS/jt9
```

Keep raw recordings and station/device identifiers under ignored `artifacts/`.
Copy a [test record](TEST_CHECKLIST.md) for each scenario, with actual duration,
configuration, evidence paths and PASS / FAIL / NOT MEASURED conclusions.

## Current readiness and recovery follow-up

Use [the active queue](NEXT_STEPS.md), [first-test plan](FIRST_CUSTOM_FIRMWARE.md)
and [current policy](TEST_POLICY.md). The former service-inquiry, hardware-access
and unconditional recovery-proof instructions in this section are historical;
they do not govern the owner's current software-only first-candidate plan.

1. After recording ends, record actual component versions and any intervening
   changes, normal UI behavior and non-writing update-menu observations. No new
   firmware update or power cycle is implied by this observation task.
2. Identify a current settings export. If a new export is needed, use the reviewed
   owner-operated stock procedure, safely unmounting the card before removal.
   Retain computer copies, hashes, date, readability and explicit coverage gaps.
   Do not format a card, load ALL settings or infer calibration/flash coverage.
3. Add the observations and receive evidence to a new revision of the existing
   private decision package, preserving its reviewed history. Keep same-version
   return-to-stock and failed-boot recovery marked unproven. No automatic device
   action or third-party inquiry is part of completing the record.
4. Present the exact candidate/procedure for the owner's later decision. Unproven
   recovery may be accepted only for that exact experiment under the current
   policy; it does not close #11 or authorize TX. An additional conditional stock
   return must be explicitly included if proposed.
5. Keep packing-related tooling private pending the distribution review in #8.
   Continue bounded native audio/runtime research using existing software/evidence.

Labeled scope/UI/SD/combined-load scenarios remain follow-on operator sessions.
A successful host capture does not measure the native codec under those loads.
