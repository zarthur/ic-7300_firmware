# Next work — updated 2026-09-29

The owner has installed the approved display-only candidate and supplied a photo
showing the intended `Informaiton` label. Read the [physical result](../research/first-custom-boot.md).
The owner also confirms automatic restart, unchanged versions and about ten
minutes receiving without issue. The authorized display-only test and its wrap-up
are complete. Stock return is a separate unapproved, unperformed test.

Baseline reconciliation, readiness collection, settings-file backup and the exact
installation decision are complete. Preserve the private evidence and proceed from
current main; do not restart those tasks. See [issue status](WORK_STATUS.md).

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
- This exact custom candidate has reached the visible menu. Stock-to-stock
  reinstall, custom-to-stock return, complete physical write effects and
  failed-boot recovery remain unproven. Read the
  [restoration assessment](../research/software-restoration.md) and
  [last bounded handshake findings](../research/update-handshake-boundaries.md).

## Active work queue

| Order | Work | Completion criterion |
| --- | --- | --- |
| 1 | Recover one native receive interface (#14/#15/#17/#19) | The [native interface map](../research/native-receive-interface.md) follows the file-reader lead to SSIF0 DMA and two live sample queues. Exact-image probes establish extraction, wrap/overflow and recorder publication. Continue with channel/gain semantics, timer/sample alignment and owned diagnostic storage; #15 still requires timestamped target capture. See the [execution plan](NATIVE_RECEIVE_PLAN.md). |
| 2 | Design the bounded target adapter (#20–#22) | Separate the estimated 393,216-byte codec workspace from adapter/DMA/stack overhead and actual target RAM availability. Plan measurements under scope/UI/SD load. Host USB capture and host benchmarks do not establish native deadlines. |
| 3 | Evaluate a specific new decoder hypothesis (#23/#25) | Use frozen baseline/holdout corpora, report per-slot gains/losses/unconfirmed results and resource use, and reject lost baseline matches. Retain manual signal reports until calibration is validated. Do not repeat unchanged parameter sweeps. |

The owner confirmed current identity/versions and no modifications, and the radio
SD folder was copied and hash verified before card preparation. The exact
revision-3 candidate installation was separately approved. The photo confirms the
label change; the subsequent owner report confirms restart, versions and the
bounded receive observation. Retain the limited scope of these physical results.

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
