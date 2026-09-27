# Next work plan — updated 2026-09-27

Current execution priority is [the first custom-firmware plan](FIRST_CUSTOM_FIRMWARE.md).
The roadmap below is historical context. Its hardware-purchase suggestions and
unconditional recovery-proof gate are superseded by the software-only,
candidate-specific owner-decision policy in TEST_POLICY.md.

USB input capture and live FT8 decoding succeeded on 2026-09-27. After the antenna
discussion, a 60-second repeat passed host continuity checks without clipping;
the prototype decoded 9 messages across three slots versus WSJT-X's 12. The
earlier capture had no decodes. Current tuning and physical source association
remain unverified. See [the receive record](RECEIVE_VALIDATION.md). Capture startup
is no longer an observed blocker; longer labeled receive/load testing remains next.

The subsequent [ten-minute corpus and offline decoder study](../research/receive-study.md)
is complete: 39 slots, 294 prototype decodes versus 340 reference decodes, 293
matches, no reported host gaps/clipping. Eight parameter variants were measured;
defaults remain unchanged and an overlap regression fixture plus replay gate are
available. Next decoder work is interference/likelihood research against the
frozen corpus and independent recordings. Labeled scope/UI/SD load scenarios and
native hardware feasibility remain open.
The owner reported a VFO tap during that capture and subsequent restoration;
its timing is unknown. The corpus remains useful for identical-audio comparisons
but is not a fixed-frequency baseline. A fresh, owner-authorized ten-minute capture with the operator committed to
leaving controls untouched has now completed: 39 slots, 280 matched prototype
decodes versus 344 reference decodes, no prototype-only results, and passing host
continuity/alignment without clipping. The two promising variants each produced
the same 280 matches, so their earlier gains did not repeat. Unchanged tuning was
not independently monitored. See the study for replacement-baseline evidence.

The subsequent likelihood study tested nine isolated decoder variants against
both 39-slot corpora. None improved the repeat corpus. Six synthetic overlap
cases plus ideal known-waveform subtraction controls isolate an interference
limitation at 14/25 Hz spacing. Defaults remain unchanged; the standard benchmark
now includes isolated-weak and separated-signal controls. Next decoder work is
bounded strong-signal subtraction, beginning with phase/timing/amplitude
estimation on generated mixtures. See the receive study for reproduction and
experimental outcomes.

A bounded [cancellation experiment](../research/cancellation-study.md) now recovers
all seven designated synthetic overlap messages and adds 3/7 reference matches
to the two older recorded corpora without losing baseline matches. The frozen
candidate adds 1/8 matches on new development/holdout captures respectively,
without losses or new unconfirmed results. Both ten-minute captures passed their
quality checks, and no radio controls were operated.
It remains desktop-only: sample buffers alone exceed the current codec workspace
target. Mapping/cache-helper execution also now reaches precise CPU-cache and
external-controller dependencies; see the updater follow-up.

## Unattended desktop package

The validation/updater package now provides `make test-synthetic` and
`make development-check` (full). Both use fresh build directories, reject required
test skips and changed source, and save atomic reports with explicit unexecuted
steps. The full profile verifies the original-image corpus and runs the controller
report twice for identical evidence. No hardware or hosted CI is involved.

The controller harness executes original erase, program, transfer-status and
flash-status polling code. Scripted successful/delayed responses return; stuck
status responses hit the harness limit without reaching caller cleanup. Mapping
and cache helper effects remain modeled, with exact unmodeled stopping points.
A bounded selector search also identifies a conditional startup reader feeding
the updater selector byte. See the [controller findings](../research/updater-emulation.md#controller-follow-up--2026-09-25).

Next independent desktop research: resolve the two mapping/cache helper families,
classify remaining selector-block candidates, and investigate DSP/FPGA paths.
Recovery, receive source/configuration verification, and target measurements remain
separate human-dependent blockers. Do not interpret completed desktop work as
closure of issues #10–#14 or permission to enable packing.

The earlier plan below is retained as the receive/platform roadmap. Its host
inventory and test counts refer to 2026-09-24; current results are recorded in each
ignored `artifacts/development-*/report.json`, not inferred from this history.

## Objective and verified starting point

Advance native FT8 feasibility by collecting stock receive evidence and resolving
the remaining platform blockers. The next milestone is a repeatable receive
baseline plus a more complete updater specification and concrete recovery route.

Planning inputs: current working tree, open GitHub issues #7–#30, and the linked
research records below. Existing uncommitted work must be preserved and reviewed;
the test counts below are historical rather than current verification evidence.

Host-only inspection on 2026-09-24 found the IC-7300 CP2102 USB interface and
`/dev/cu.usbserial-<radio>`. A USB Audio CODEC input and output are enumerated with
two channels each and a current host rate of 48 kHz. The default audio input is
Display Audio, so capture must select the radio input explicitly. Verify audio
source association with a controlled receive observation before labeling samples.
The host rate does not establish the radio's internal PCM format or sample rate.
No serial port or audio stream was opened during planning.

Prior evidence establishes the owner's official 1.41 → 1.42 update and two CI-V
status queries. USB connection does not establish flash readback, spare RAM,
debug access or recovery without a working application.

## Ordered work packages

| Priority | Work and issues | Deliverable and completion criteria |
| --- | --- | --- |
| 1 | Consolidate the desktop baseline (#7, #9–#12) | Review existing changes, reconcile older status text with later evidence, run the commands below, and record revision/dirty state, dependency versions and results. Separate implemented criteria from open criteria; do not close an issue based only on partial desktop success. |
| 2 | Stock USB receive baseline (supports #15, #21, #23) | Implement an input-only capture tool with explicit device selection, bounded duration, timestamps and gap/clipping statistics. Verify with synthetic fixtures, then collect radio audio after the receive-session checklist. Convert explicitly to mono PCM16 at 12 kHz with documented resampling delay. Compare identical aligned 15-second segments with the prototype and pinned WSJT-X decoder; retain hashes, counts and limitations. A valid silent capture is acquisition evidence, not decoder acceptance. |
| 3 | Finish updater/controller research (#10) | Trace real controller completion/status/error handling beneath erase/program calls; identify ownership of the entire selector erase block; extend original-routine emulation and rejection/fault tests. Cover DSP/FPGA paths or explicitly retain them as unresolved acceptance criteria. Publish routine boundaries, modeled dependencies, and evidence for each conclusion. |
| 4 | Resolve recovery access and backup coverage (#11) | Use the existing service inquiry to seek an authoritative procedure for this board revision. The inquiry is drafted, not sent. Identify boot, both application banks, selector metadata, calibration/configuration and other component storage coverage. Deliver a board-specific recovery proposal with tools, electrical/reset ownership, repeated-read verification and official-content restoration criteria. |
| 5 | Resolve a display-only patch site and packing policy (#12, #13, #18) | Trace every known consumer of one diagnostic string, verify rendering/length semantics and exclude compatibility/control uses. Define exact preimage, approved region and preserved bytes. Validate each candidate's bounded original-loader decode, including lookahead, within the proven original span. Keep real output disabled until all policy gates are supported by evidence. |
| 6 | Recover native receive and runtime interfaces (#14, #15, #17, #19) | Trace recorder paths into PCM queues/DMA, buffer ownership, task lifecycle and timestamps; identify allocator, stacks and scheduling APIs. Produce an evidence-backed interface map and bounded-workspace design for #20. USB captures inform codec testing but do not complete the native interface work. |

Packages 2–6 can progress independently where they involve desktop research or
stock receive observation. Recovery is the critical dependency for modified boots,
not a reason to stop decoder, capture-tool or reverse-engineering work.

## First implementation session

1. Preserve the existing worktree and inventory report freshness. Run the desktop
   baseline using the existing dependencies and official images:

   ```sh
   make -j4 test
   IC7300_TEST_IMAGE=artifacts/original/7300_142.dat .venv/bin/python -m unittest discover -s tests -v
   python3 tools/verify_firmware.py --output artifacts/next-baseline-firmware-results.json
   git diff --check
   ```

   Record skips and failures explicitly. Reproduction from committed HEAD does
   not verify these uncommitted changes. Rerun expensive emulation/recompression
   when changed code or stale evidence requires it.
2. Build and test the input-only capture utility. Use a new ignored evidence
   directory for raw audio, metadata and device identifiers. Add only original
   code, synthetic fixtures and sanitized summaries to Git.
3. Prepare a stock receive test record from [TEST_CHECKLIST.md](TEST_CHECKLIST.md).
   Reuse the prior documented safe USB SEND/keying configuration; check for changes
   since that session and competing port owners before any serial access. If CI-V
   is needed, constrain it to the already documented frequency/mode queries with
   RTS/DTR false, exclusive access and bounded timeouts. Capture can run without
   opening CI-V. Do not change tuning or route host playback to the radio.
4. Capture at least ten minutes per practical receive scenario: steady receive,
   scope/UI activity, SD recording, and combined load. Record actual configuration,
   elapsed duration, sample counts, discontinuities and host clock information.
   Operator changes to radio controls are explicit steps in the record.
5. Compare aligned segments against the reference decoder. Distinguish host/USB
   buffering faults from codec misses; rerun affected cases after fixes. Report
   the observed sensitivity gap without claiming target CPU feasibility.
6. Continue the controller/error-path analysis and update the blocker evidence.

## Blockers and how they clear

| Blocked outcome | Missing evidence | Required next decision or result |
| --- | --- | --- |
| Application-independent recovery (#11) | Qualified access, complete backup coverage and physical restoration proof | Authoritative service procedure or a qualified board-specific investigation; then a separately reviewed official-content recovery experiment. An ordinary SD update is insufficient. |
| Production packer (#12) | Remaining acceptance semantics and verified patch policy | Reproducible controller/validation findings, exact-base approved region and bounded per-image decode/audit checks. The existing unchanged-application recompression result already addresses one storage/lookahead case; do not repeat it as if unresolved. |
| Visible custom boot (#13) | Recovery proof and validated exact candidate | First demonstrate recovery for the relevant failure class; then present the exact image hash, offline results and installation/rollback procedure for hardware review under TEST_POLICY.md. |
| On-radio memory/CPU feasibility (#14, #22) | Owned workspace, runtime interfaces and safe measurement access | Establish at least 393,216 bytes of reservable codec workspace plus separately budgeted adapter/DMA/runtime overhead; measure stacks and scheduling under load. Host timing and static image gaps do not satisfy this. |
| Target qualification (#7) | Region and actual board/part identification | Record owner-visible identification first; defer internal inspection until a concrete board-specific plan exists. |
| Distribution (#8) | Qualified review required by project policy | Obtain the recorded distribution review before publishing patching-related tooling; local research may continue. |

If independent recovery remains unavailable, continue stock USB receive validation,
offline analysis and bounded codec work while retaining the modified-boot blocker.
Do not use corrupt images, forced downgrades or interrupted writes to discover a
recovery path. TX tasks #26–#30 follow later platform, timing and operator-control
milestones; they are not part of this work session.

## Evidence references

- [Stock update](../research/stock-update.md) and [physical CI-V reads](../research/radio-readonly.md)
- [Latest updater stages and remaining gates](../research/updater-emulation.md)
- [Recovery access and unsent service inquiry](../research/recovery-access.md)
- [Platform measurement procedure](PLATFORM_VALIDATION.md) and [test policy](TEST_POLICY.md)
- [Integration limits](../research/integration.md)
- [GitHub task backlog](https://github.com/zarthur/ic-7300_firmware/issues)
