# Automated development plan

Current direction: prepare the first minimal custom-firmware experiment under
[FIRST_CUSTOM_FIRMWARE.md](FIRST_CUSTOM_FIRMWARE.md). This supersedes the earlier
queue in NEXT_STEPS.md and its unconditional recovery requirement for #13.
Use software and the existing computer/radio only; no hardware purchases,
internal connections or physical modification. Actual radio firmware writes
require a later explicit owner decision on the exact candidate and procedure.

## Active queue

1. Freeze and verify the baseline, target identity evidence and outstanding gaps.
2. Delegate independent bounded research on the exact update/boot path, a harmless
   same-length display-label site, and software-only restoration options.
3. Review and implement a constrained local candidate builder only after the
   exact patch policy and relevant acceptance evidence support it. Keep firmware
   outputs and unpublished packing code local, subject to the distribution policy.
4. Validate candidate-specific original-loader decode, integrity, protected bytes,
   modeled write effects and failure cases, deterministic construction, and source
   provenance. Resolve failed invariants and obtain independent review.
5. Assemble the exact-image first-test decision package and present remaining
   risks, including the possibility of a nonbooting radio with no demonstrated
   software restoration path. Request the owner's candidate-specific decision.
6. Do not autonomously install, open device interfaces, tune, transmit, or contact
   third parties. No intentional corrupt-image or power-interruption tests.

Recovery research remains important, but lack of demonstrated independent recovery
is not by itself a reason to stop preparatory work or suppress the decision package.
It is an explicit risk for the owner's later decision, not something a PR merge
or this automation may accept on their behalf. Issue #11 stays open until its
physical acceptance evidence exists. Successful first boot does not close native
FT8 audio, memory, scheduling or performance requirements.

## Per-run workflow and merge gate

The heartbeat `ic-7300-development-and-pr-review` runs every two hours.

- Refresh issues, PRs, origin/main and the checkpoint. Start at the first unblocked
  active package; do not redo completed provenance or CI work.
- Use `/Users/arthur/Documents/projects/ic-7300-development` and fresh `codex/`
  branches from current origin/main. Preserve the original dirty workspace at
  `/Users/arthur/Documents/projects/ic-7300_firmware`. No reset, clean, blanket
  staging or wholesale commit of that workspace.
- Use isolated worktrees for parallel implementation, independent reviewers and a
  single integration owner. Freeze sources and replay inputs during validation.
- Open and attach focused PRs with issue links, source revision, tests, evidence
  and limitations. Inspect actual Linux/macOS checks and applicable local full
  checks/corpus tests. No missing or skipped required checks count as success.
  Documentation-only changes need content/link/whitespace review; hosted checks
  still apply. Resolve substantive findings before merging.
- The owner authorizes normal passing PR approvals and merges. Recheck the exact
  head SHA and base compatibility, use a head-SHA merge guard and respect branch
  rules. Do not impersonate a reviewer or bypass GitHub self-approval restrictions.
  Desktop PR approval is not firmware-installation approval.
- Keep firmware, generated dumps, recordings, settings, station logs and personal
  data local and ignored. Follow the existing publication boundary; general merge
  authority does not authorize publishing patching tools pending review.
- Close issues only when all acceptance criteria are met. Record partial progress
  without closing #7, #10–#14 or native FT8 tasks on desktop evidence alone.
- Update the checkpoint. Notify only on meaningful completion, merge, failure,
  a concrete missing observation, or readiness for the first-test decision. Stay
  quiet when unchanged. Prefer useful bounded research over repeated blocker reports.

## Checkpoint

2026-09-27 implementation:

- Merged #36 (governance; closed #9), #37 (exact-image validation), #38
  (offline updater/controller harnesses), #39 (bounded selector probe), and #40
  (receive capture/replay, provenance fixes, and cancellation studies).
- Required capture batches now contain verified usable slots. Replay and both
  study runners reject changed inputs, executables, manifests, generated artifacts
  and source, including changes during final checks.
- Full profile at `ca25a43` passed 100 Python tests with zero skips, C tests,
  sanitizers, official-image round trips, repeated controller evidence and
  reference comparisons. The final likelihood-only fix at `3540a79` passed the
  complete synthetic profile; unchanged full-profile components retain their
  prior evidence. Local reports: `artifacts/development-20260927T230317103904Z/`
  and `artifacts/development-20260927T230543492387Z/`.
- The frozen cancellation candidate passed 14 synthetic cases and four 39-slot
  recordings. Behavior matched the previous candidate exactly, with no lost
  baseline matches or new unconfirmed messages. Local index:
  `artifacts/automation-final-behavior.json`. Isolated clipping/energy temporary
  allocation fell from 2,883,160 to 1,442,584 bytes; this is not whole-fit RSS or
  target-memory acceptance.
- The selector probe passed 15 bounded trials. Its conditional Thumb semantics
  narrow five candidate interpretations without proving runtime reachability.
- Packing/recompression tooling and generated instruction/CFG dumps remain local.
  The original dirty workspace is preserved. The durable integration checkout is
  `/Users/arthur/Documents/projects/ic-7300-development`; use fresh `codex/`
  branches from current `origin/main` there for subsequent work.
- PR #41 merged after both Ubuntu and macOS hosted synthetic jobs passed.
  Inspect both checks and independent review evidence before every future merge.


2026-09-28 first-candidate preparation:

- PR #42 established the current first-test plan. Clean baseline `c1e787b`
  passed the full desktop profile: 101 Python tests, zero skips, C tests,
  sanitizers, official-image round trips, controller repeats and reference
  comparisons. Local frozen manifest:
  `artifacts/first-custom-baseline-20260928/baseline.json`.
- [Updater footprint](../research/update-footprint.md) establishes full 64 KiB
  writes for differing units, conditional boot preservation, and selector-block
  exposure. DSP/FPGA no-touch behavior and physical destination contents remain
  unknown. Read-only reproduction: `tools/update_footprint.py`.
- [Software restoration](../research/software-restoration.md) distinguishes the
  observed official upgrade from untested same-version/custom-to-stock return.
  Failed-boot recovery remains unknown; #11 remains open.
- The `Information` label has a bounded original-code text-path trace, but lower
  rendering and live caller invariants are unresolved. `tools/display_label.py`
  explicitly reports `patch_qualified=false`; no patch interval is approved.
- Next: finish this label's renderer/caller qualification, inspect same-version
  stock acceptance and other-component update paths, then review local packing
  only after a qualified edit exists. Current-radio/market confirmation and
  current backup coverage remain pending. No candidate image or installation
  approval exists; all packing tools and firmware evidence remain local.


2026-09-28 bounded follow-up:

- PR #43 merged after independent review, full desktop validation (114 Python
  tests, zero skips), and both hosted jobs. The integration checkout is clean at
  `e4dfee3`; its tree matches the tested PR head. Local acceptance index:
  `artifacts/first-custom-baseline-20260928/pr43-validation-index.json`.
- The next read-only checks exercise the ordinary label wrapper/ASCII parser,
  separate updater command dispatch, and real component-change flag getter.
  [Same-version acceptance](../research/same-version-acceptance.md) remains
  conditional on unresolved UI command production. No physical recovery claim.
- Original-loader byte-range guards now reject mapped-page padding accesses.
  Retained local packing review identified a durability-ordering requirement for
  the future publisher; it remains blocked and unpublished.
- Next bounded questions: glyph/font layout for the proposed label, normal update
  command eligibility with matching identifiers, and any selected component
  handshake. No candidate exists. Target/market confirmation and current backup
  observations remain pending; do not re-ask broad approval or perform device I/O.


2026-09-28 layout and eligibility increment:

- PR #44 merged after exact-head independent review, Linux/macOS CI and the full
  desktop profile (125 Python tests, zero skips). Local index:
  `artifacts/pr44-validation-index.json`. Baseline `8f8e921` has the identical
  tested tree; saved report hashes rechecked before this increment.
- [UI producer mapping](../research/update-ui-producers.md) narrows normal update
  eligibility to two payload predicates and the writer of handshake value 1.
  Seeded-state traces do not establish normal same-version installation.
- The exact stock-update record supports local preparation while market remains
  UNKNOWN; resolve concrete compatibility conflicts, retain current-observation
  and exact-owner-decision requirements before installation.
- Local unpublished packing copy fixes audit-name durability and error-cleanup
  ordering. Independent review and nine synthetic primitive/durability tests
  passed; the historical unpublished CLI test is excluded, not counted as pass.
  Local record: `artifacts/local-packing-review-20260928T0407/validation-final.json`.
  The original dirty tool is unchanged and real-image policy remains blocked.
- No candidate exists; full exact-candidate acceptance/write/failure checks and
  the owner's decision package remain outstanding. Recovery #11 and native
  performance remain open.

- [Font metrics](../research/label-font-metrics.md) favor the two-character
  `Informaiton` proposal: both embedded fonts preserve advance and outer ink
  bounds. Next integrate descriptor/consumer and live-row evidence into a narrow
  policy review; static extents do not establish final rendered pixels.


2026-09-28 exact local candidate increment:

- PR #45 merged after independent review, full desktop profile (132 Python tests,
  zero skips) and Linux/macOS CI. Index: `artifacts/pr45-validation-index.json`.
- Independent policy reviews now justify only the two decoded bytes `ti` to `it`
  in `Information` for local construction. This is separate from generic probe
  results and not installation authority. Row translation is executed with an
  explicitly synthetic list, leaving live population/rendering unknown.
- A private candidate and durable audit exist under
  `artifacts/first-candidate-20260928T0607/`. Separate-interpreter construction
  produced identical bytes/audit; independent readback confirmed only the two
  decoded bytes changed and protected regions/suffix are unchanged. Original
  loader and stage-local header/payload checks passed. No packing source or
  candidate image is published. The original dirty source is preserved.
- Full-application transfer models now accept explicit modeled destination units.
  Complete exact-candidate write/failure validation and final decision package
  review remain required; use the local artifact index for completed runs.
- [Eligibility predicates](../research/update-eligibility-predicates.md) resolve
  seven RAM conditions without direct version/component reads. Normal entry and
  handshake production remain unproven; same-version restoration is conditional.
- Next inspect the bounded handshake writer, finish exact-candidate evidence and
  prepare owner observations/conditional restoration procedure. No radio I/O or
  firmware write is authorized. #11 and native performance remain open.
