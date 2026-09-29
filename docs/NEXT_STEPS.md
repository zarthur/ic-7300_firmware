# Next work — updated 2026-09-29

The first display-only candidate has been built and independently reviewed as a
conditional technical draft. The current milestone is to complete current-radio
and backup evidence, then present the exact candidate and procedure for the
owner's decision under [the first-test plan](FIRST_CUSTOM_FIRMWARE.md).

PRs #36–#49 are merged. The September 29 review found no open PRs. Candidate
construction, bounded label/updater analysis and the conditional procedure are
completed desktop work; they should not be restarted while observations are
pending. See [issue status](WORK_STATUS.md) for completed evidence and remaining
acceptance criteria, and [checkpoint history](AUTOMATED_DEVELOPMENT.md#checkpoint)
for the sequence of completed work.

## Current evidence

- The original IC-7300's official 1.41 → 1.42 update is recorded. The initial
  preparation base remains the exact pinned v1.42 image in
  [supported targets](SUPPORTED_TARGETS.md).
- A local two-byte display edit changes `Information` to `Informaiton`.
  Deterministic construction, protected-region checks, original-loader decoding
  and bounded updater/write/failure models have been reviewed. Private files are
  indexed by `artifacts/pr46-validation-index.json`; the conditional procedure and
  manifest are under `artifacts/decision-review-20260928T0808/` in the evidence
  checkout. Firmware and unpublished packing sources stay local.
- PR #48 completed baseline reconciliation: the old working files are privately
  archived with per-file dispositions; no obsolete runtime code needs porting.
  Continue from current main and retain the old evidence checkout unchanged.
- PR #49 retained a passing full profile with 142 Python tests and zero skips
  on `983b5ee` (the same source tree as merged `7ac5b19`). That merged baseline
  passed both hosted synthetic jobs in
  [run 36582605304](https://github.com/zarthur/ic-7300_firmware/actions/runs/36582605304).
  These results apply to their recorded revisions, not arbitrary dirty worktrees.
- Stock USB receive capture/replay and the bounded cancellation study are
  complete. [Receive findings](../research/receive-study.md) and
  [cancellation findings](../research/cancellation-study.md) retain measured
  limits. Cancellation remains an opt-in desktop experiment; target memory and
  timing are unmeasured.
- Normal same-version/custom-to-stock installation, physical write effects and
  failed-boot recovery remain unproven. Read the
  [restoration assessment](../research/software-restoration.md) and
  [last bounded handshake findings](../research/update-handshake-boundaries.md).

## Active work queue

| Order | Work | Completion criterion |
| --- | --- | --- |
| 1 | Collect missing current-radio evidence (#7/#11/#13/#32) | Confirm the same original radio, current component versions and intervening changes; record normal stock boot/receive/UI behavior and observed update-menu availability. Verify current settings-export paths, hashes and readability locally and list uncovered storage. These observations do not demonstrate same-version installation or failed-boot recovery. |
| 2 | Finalize the existing decision package (#10/#12/#13/#31/#32) | Incorporate the observations, preserve candidate/base identity and historical provenance, freeze a procedure revision/manifest, and present the PASS/FAIL/UNKNOWN evidence and phase-specific responses for the owner's exact decision. Include conditional stock return explicitly if proposed; it is another write. |
| 3 | Recover one native receive interface (#14/#15/#17/#19) | Continue from the bounded entry `0x2006bfd4` in [the recorder findings](../research/recorder-interface.md). The previous lead is stored-file parsing, not a live PCM ring. Establish sample format, ownership, lifecycle, task and timestamp boundaries. Deliver a reproducible interface map or a precise unresolved boundary. This desktop work can proceed while owner observations are pending. |
| 4 | Design the bounded target adapter (#20–#22) | Separate the estimated 393,216-byte codec workspace from adapter/DMA/stack overhead and actual target RAM availability. Plan measurements under scope/UI/SD load. Host USB capture and host benchmarks do not establish native deadlines. |
| 5 | Evaluate a specific new decoder hypothesis (#23/#25) | Use frozen baseline/holdout corpora, report per-slot gains/losses/unconfirmed results and resource use, and reject lost baseline matches. Retain manual signal reports until calibration is validated. Do not repeat unchanged parameter sweeps. |

PR #49 already added current stock host-receive evidence to decision-package
revision 2. Do not repeat the capture solely to complete the queue: missing inputs
are same-radio/version/change confirmation, boot/UI observations, current backup
evidence and SD/power/operator readiness. The private wrap-up audit under
`artifacts/wrap-up-20260929/` rechecks retained manifests, all 90 archived source
files and the full-profile source identity; it is not a new hardware test.

## Decision and validation rules

Use [TEST_POLICY.md](TEST_POLICY.md) for the current candidate-specific policy.
Unknown market information alone does not prevent continued exact-base offline
preparation; resolve concrete compatibility conflicts. The owner may later accept
unproven recovery for an exact candidate, but neither a PR merge nor this roadmap
supplies that decision or completes #11. A failed boot could leave the radio
unusable with the available setup. No hardware purchases or internal connections
are planned.

Do not infer firmware-write authority from readiness observations. Any later
installation must follow the exact authorized procedure, with separate records
for visible change, normal receive/UI behavior and any authorized stock return.
TX work #26–#30 remains downstream of platform, timing and operator-control gates.

For code changes, use the applicable local checks and both hosted synthetic jobs.
`make test-synthetic` exercises the firmware-free profile; `make development-check`
requires the pinned local dependencies, official images and WSJT-X. Missing
prerequisites or required skips are not PASS. Documentation-only changes need
content, links and whitespace review plus normal hosted checks. Re-run expensive
candidate/corpus checks only when changed code or evidence invalidates them.
Use the [test checklist](TEST_CHECKLIST.md) to record actual results and limits.

## Historical work

The superseded September 24–27 roadmap remains available in
[Git history at 24b6934](https://github.com/zarthur/ic-7300_firmware/blob/24b693404f553509af247ea03bfec6ffd9ba7c38/docs/NEXT_STEPS.md).
Its capture-tool implementation tasks, inactive-CI statement and unconditional
recovery gate are not the current queue. Preserve historical measurements in
research records rather than treating them as fresh verification.
