# Work status — 2026-09-29

Reviewed against `main` at `7ac5b19`, merged PRs #36–#49, the 32 open issues,
and the retained candidate/validation manifests. No open PRs were present at
review time. The table records partial progress; it does not close issues or
replace their acceptance criteria. See [the ordered work queue](NEXT_STEPS.md).

## Implementation issues

| Issue | Established progress | Remaining acceptance / next action |
| --- | --- | --- |
| [#7](https://github.com/zarthur/ic-7300_firmware/issues/7) Target matrix | Published original-model matrix; exact-image gates; observed official update | Same-radio/current pre-install versions and no modifications confirmed; regional qualification remains incomplete. |
| [#8](https://github.com/zarthur/ic-7300_firmware/issues/8) Distribution review | License and third-party notices retained | Closed as not planned; legal review is deferred and may be revisited if needed. |
| [#10](https://github.com/zarthur/ic-7300_firmware/issues/10) Updater semantics | Container checks, loader, selector and bounded transfer/controller/UI traces | Complete acceptance specification across supported targets; physical/task effects and complete selector-block ownership remain unknown. |
| [#11](https://github.com/zarthur/ic-7300_firmware/issues/11) Recovery | Failure-class matrix and conditional software restoration assessment | Successful physical recovery procedure is not demonstrated; same-version/custom-to-stock return is untested. Risk acceptance does not complete this issue. |
| [#12](https://github.com/zarthur/ic-7300_firmware/issues/12) Packer | Private constrained candidate builder/audit reviewed for one exact edit | General deterministic packer acceptance and distribution remain incomplete; preserve the narrow local policy. |
| [#13](https://github.com/zarthur/ic-7300_firmware/issues/13) Visible-only proof | Authorized display test complete: photo confirms label; owner confirms automatic restart, unchanged versions and about ten minutes receiving without issue | Stock return remains unapproved/unperformed, so broader acceptance remains open; see [physical result](../research/first-custom-boot.md). |
| [#14](https://github.com/zarthur/ic-7300_firmware/issues/14) Runtime headroom | [Allocator/startup map](../research/native-receive-memory.md) establishes a 348,152-byte shared arena, framebuffer ownership and a padding candidate | Qualify diagnostic placement and live availability, then measure CPU/stack behavior under load; the 393,216-byte reservation cannot fit this entire heap. |
| [#15](https://github.com/zarthur/ic-7300_firmware/issues/15) Receive interface | [Native path map](../research/native-receive-interface.md) identifies SSIF0 DMA, planar PCM16 extraction, two queues, recorder publication and nominal-rate evidence; original-instruction probes cover all first-queue index pairs | [V1 and v2 target captures](../research/native-receive-v2-target-capture.md) now include a full v2-format export at owner-reported 7.074 MHz USB-D and minimum AF volume; 3,024 stream-A samples match recorder audio at unity. The [DSP-to-SSIF0 crosswalk](../research/native-dsp-ssif0-bridge.md) connects existing source maps; the caller A4 slot and selected control predicates are now source-offset verified, but live values and physical frame phase remain unresolved. Stream B is zero in both captures, but its meaning and global gain/control dependence remain unknown. Flash identity, timestamp quality, loss/restart association and runtime ownership remain unproven; #15 stays open. |
| [#16](https://github.com/zarthur/ic-7300_firmware/issues/16) Playback/PTT interface | [Native output-queue slice](../research/native-playback-queues.md) verifies two 12-byte rings, cursor wrap/empty/reset behavior, a six-entry producer guard and DMA-service pop calls; the portable station layer now has a host-only queued/drained/aborted/flushed/failed mock contract | Voice/file worker ownership of these rings and real backend signals remain unknown. Worker return is not a verified DMA-drain, audible-completion, flush or PTT-release signal. No hardware mapping or PTT safety claim. |
| [#17](https://github.com/zarthur/ic-7300_firmware/issues/17) UTC interface | [Native timer map](../research/native-receive-timing.md) identifies delay, scheduler and audio-service counters, intended scale and rollover | Establish coherent acquisition epoch, physical clock accuracy, RTC association/setting behavior and clock-jump gate. |
| [#18](https://github.com/zarthur/ic-7300_firmware/issues/18) UI/settings | One display label has bounded consumer/renderer/font evidence and is now visibly running on the radio | Native UI hook, live behavior and settings persistence remain incomplete; design RAM-only feature state. |
| [#19](https://github.com/zarthur/ic-7300_firmware/issues/19) DSP transport | SSIF0 slave framing, DMAC3 bank addresses and CPU queue ownership recovered with reproducible offline evidence | Resolve DSP stream identity/control handshakes and validate physical continuity/concurrency. |
| [#20](https://github.com/zarthur/ic-7300_firmware/issues/20) Target codec | Portable C codec and host allocation measurements | Bounded/static workspace, target ABI build and target-compatible tests. |
| [#21](https://github.com/zarthur/ic-7300_firmware/issues/21) Streaming receive | Host USB capture/resampling/aligned replay | Native nonblocking adapter depends on #15/#20; host capture does not satisfy it. |
| [#22](https://github.com/zarthur/ic-7300_firmware/issues/22) Target deadlines | Host timings and documented capture/decode deadline gap | Measure worst-case target decoding with concurrent scope/UI/SD load. |
| [#23](https://github.com/zarthur/ic-7300_firmware/issues/23) Sensitivity | Reference comparisons, frozen corpora, replay regression gate and cancellation study | Retain capability limits; evaluate concrete new hypotheses with no lost baseline matches and target resource accounting. |
| [#24](https://github.com/zarthur/ic-7300_firmware/issues/24) Caller UI | Desktop message/selection interfaces | Implement and validate on-device list/caller selection without implicit TX. |
| [#25](https://github.com/zarthur/ic-7300_firmware/issues/25) Signal reports | Prototype uses manual reports; sync score is not calibrated SNR | Record the initial-release deferral decision or validate a calibrated estimator. |
| [#26](https://github.com/zarthur/ic-7300_firmware/issues/26) TX adapter | Desktop waveform independently decoded | Native audio/PTT/timing prerequisites and dummy-load measurements remain. |
| [#27](https://github.com/zarthur/ic-7300_firmware/issues/27) Sequencer | Desktop selected-caller exchange and cancellation tests | Integrate operator controls and physical completion semantics; retain bounded exchange scope. |
| [#28](https://github.com/zarthur/ic-7300_firmware/issues/28) TX interlocks | Desktop reservation/cancellation behavior | Native per-session arm, time/frequency/mode gates, watchdog and immediate audio/PTT stop with fault injection. |
| [#29](https://github.com/zarthur/ic-7300_firmware/issues/29) Identification/control | Published operating constraints | Required jurisdiction-specific review and reviewable configured identity/operator controls. |
| [#30](https://github.com/zarthur/ic-7300_firmware/issues/30) Phased interoperability | Desktop and stock receive comparisons | Native receive-only, dummy-load and supervised on-air phases after all TX prerequisites. |
| [#31](https://github.com/zarthur/ic-7300_firmware/issues/31) Regression/HIL plan | Checklist, Linux/macOS synthetic CI, full desktop profile and candidate matrix | Complete firmware-keyed hardware coverage and explicit untested/failure cases. |
| [#32](https://github.com/zarthur/ic-7300_firmware/issues/32) Operator documentation | Conditional procedure and restoration limits reviewed | Incorporate current evidence; complete applicable fresh-user dry run without claiming untested restoration. |
| [#33](https://github.com/zarthur/ic-7300_firmware/issues/33) Prerelease | Reproducibility and provenance tooling exist | Controlled release remains downstream of validation, documentation and dependency license/notice checks. |

## Epic roll-up

| Issue / epic | Status |
| --- | --- |
| [#1 / Epic 0](https://github.com/zarthur/ic-7300_firmware/issues/1) Governance | #9 is closed; #8 is closed as not planned, to revisit if needed; #7 remains open. |
| [#2 / Epic 1](https://github.com/zarthur/ic-7300_firmware/issues/2) Platform | Desktop evidence advanced; hardware acceptance for #10–#14 remains incomplete. |
| [#3 / Epic 2](https://github.com/zarthur/ic-7300_firmware/issues/3) Interfaces | Native receive/ownership/timing are the next bounded research slice; #15–#19 remain open. |
| [#4 / Epic 3](https://github.com/zarthur/ic-7300_firmware/issues/4) Receive | Host pipeline and studies exist; #20–#25 require target integration or explicit release decisions. |
| [#5 / Epic 4](https://github.com/zarthur/ic-7300_firmware/issues/5) Transmit | Desktop primitives exist; #26–#30 remain behind native interface, timing and operator-control gates. |
| [#6 / Epic 5](https://github.com/zarthur/ic-7300_firmware/issues/6) Release | Desktop CI is active; #31–#33 retain hardware/documentation/distribution gaps. |

## Reconciliation record

A verified private archive preserves 90 tracked/untracked source files from the
old checkout, along with its diff, status and hashes. The 65 pre-existing changed
paths comprise 35 exact matches to merged main, 27 divergent files, and three
local-only files. The September 29 planning document is one additional local-only
file. Per-file comparisons and dispositions are retained under the ignored
`artifacts/reconciliation-20260929T133556Z/` directory in the original evidence
checkout. Original files and retained candidate evidence were not modified.

The divergent files contain older implementations, missing merged hardening,
superseded policy/documentation, or unpublished packing integration. Current main
is the implementation baseline; no old executable code is ported in this
reconciliation. The local-only packing source/test and generated platform report
remain private. The new roadmap carries forward the planning document's actions.

Validation for this documentation increment: review relative links, Markdown
structure and whitespace, confirm the issue list and recorded CI/evidence facts,
and require normal hosted synthetic checks before merge. Hardware fields in the
[test checklist](TEST_CHECKLIST.md) are N/A; this increment performs no radio I/O,
image construction, firmware write, dependency change or runtime-code change.

## Wrap-up verification

The September 29 follow-up rehashed the retained decision-package dependencies,
PR #46 evidence index, reconciliation archive and all 90 archived source files.
All 824 recorded integrity/source checks passed. The retained PR #49 full profile
has 142 Python tests with zero skips and all stages passing; its source hashes
match merged `7ac5b19`. Hosted Linux/macOS validation also passed for that merge
in [run 36582605304](https://github.com/zarthur/ic-7300_firmware/actions/runs/36582605304).
Private audit script/results are under `artifacts/wrap-up-20260929/` in the
original evidence checkout. Integrity checks do not independently repeat the
experiments or establish physical readiness.

Baseline reconciliation is complete. Preserve the stale evidence checkout;
start new source work from current main. Readiness observations, backup verification and the exact installation decision
are now complete. The display-only test is complete: label, automatic restart, unchanged versions
and about ten minutes receiving without issue are documented. Stock return is
unapproved/unperformed and remains separate from the next desktop work. This does not block desktop native-interface
research. No issue is closed by this status correction.
