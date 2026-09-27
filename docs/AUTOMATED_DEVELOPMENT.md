# Automated development plan

Reviewed 2026-09-27. This is the execution queue for the recurring development
task, alongside the research roadmap in [NEXT_STEPS.md](NEXT_STEPS.md).

## Reviewed state

- GitHub: 33 open issues, no open PRs. Main has no branch protection and there is
  no hosted CI workflow. The authenticated account has repository admin access.
- Local base: `1ab637b`, on `main`, with 20 modified tracked files and 43 untracked
  files. This substantial research baseline must be preserved and split into
  reviewed changes; it is not the code currently available from GitHub main.
- Fresh `make development-check` passed on the unchanged local source tree:
  95 Python tests, zero skips, C QSO/codec tests, simulation, ASan/UBSan checks,
  official-image round trips, repeated controller evidence, reference decoder
  comparisons and whitespace checks. Evidence is local at
  `artifacts/development-20260927T220429163603Z/report.json` and its sibling logs.
  This validates the recorded dirty tree, not a future commit or hardware behavior.
- Two independent review sub-agents assessed code and issue dependencies.
  Known sensitivity gaps remain; a passing benchmark does not establish parity
  with WSJT-X or feasibility on the radio processor.
- The owner reports that the radio is powered on and connected. No device I/O
  was performed during this review. Connection does not supply missing recovery,
  native runtime, tuning or regional qualification evidence.

## Ordered execution queue

| Order | Work package | Acceptance and issue relationship |
| --- | --- | --- |
| 1 | Fix replay provenance | `tools/compare_receive.py` can return PASS after a decoder binary or slot changes during replay. The reviewer reproduced exit 0 with mismatching recorded hashes. Freeze inputs/executables or detect changes and fail closed; include manifest, cached reference and source provenance. Regression tests must mutate inputs/binaries during a run and demonstrate rejection. Supports #23 and all replay-based merge decisions. |
| 2 | Reject unusable capture batches | `tools/capture_batch.py` can report PASS with zero exported slots. Require a nonempty validated slot inventory, consistent manifest hashes and usable audio before success. Test empty, missing and malformed slots with synthetic fixtures and no device access. Supports #15/#23. |
| 3 | Consolidate reviewed baseline | Inventory dependencies between the existing 63 changed/untracked files. Split governance/checklist, target validation, updater research, receive tooling and codec experiments into focused branches/PRs. Stage explicit paths only. Review original analysis and scan for prohibited content. Do not publish patching-related tools pending the outstanding distribution gate. Validate each resulting branch independently. |
| 4 | Add synthetic PR CI | After its dependencies are committed, bootstrap pinned codec sources, install pinned Python packages and run `make test-synthetic` in a clean runner. Never acquire official firmware or recordings in hosted CI. Upload only reviewed synthetic validation logs. Verify an actual passing PR run before relying on the check. |
| 5 | Reduce cancellation resources | Keep cancellation desktop-only and opt-in. Measure peak memory and execution work; retain frozen-corpus gains with zero baseline losses and no new unconfirmed messages. Run synthetic controls and development replays, then the held-out acceptance corpus without tuning against holdout outcomes. Supports #23/#20; does not close target-port acceptance. |
| 6 | Resolve bounded platform questions | Use independent read-only research agents for remaining selector-block consumers and cache/mapping helpers, then DSP/FPGA updater paths (#10). Trace native receive buffers, ownership, clocks and scheduling (#14/#15/#17/#19). Deliver reproducible bounded evidence and explicit unknowns, not speculative integration code. |

The first two findings are open at this checkpoint. Full-suite PASS does not
invalidate these independently reproduced gaps in test coverage.

## Per-run workflow

The active task heartbeat is `ic-7300-development-and-pr-review`, every two hours.
Each wakeup should make bounded progress on the first unblocked package:

1. Refresh issues, PRs, remote refs, local status and this checkpoint. Reuse
   existing work instead of opening duplicate branches or PRs.
2. Preserve the owner's dirty worktree. Use `codex/` branches in isolated
   worktrees for new changes. A worktree from HEAD does not contain the existing
   uncommitted baseline: copy only explicitly reviewed dependencies when needed.
   Never reset, clean, stash or wholesale commit the owner's changes.
3. Assign concrete independent implementation/review subtasks as useful.
   Give each implementation agent its own worktree; keep a single integration
   owner. Freeze a tree while validation runs. Do not launch competing builds
   or mutate shared replay inputs.
4. Implement one reviewable increment, add meaningful regression coverage and
   run the applicable checks. Resolve findings before publishing the PR.
5. Open and attach a focused PR with issue links, exact revision, behavior,
   tests, evidence limitations and remaining acceptance criteria. Do not use
   closing keywords for partially satisfied issues.
6. Have an independent reviewer inspect semantics, tests, scope and the actual
   diff. Record actionable findings and resolve them. Test success alone is
   insufficient for merge approval.
7. Apply the merge gate below. Update this checkpoint with completed work,
   merged PRs, revision-specific reports and the next bounded action.

Notify the owner only for meaningful completion, a merge, failure, or a new
blocker requiring action. If everything remaining depends on hardware or other
missing evidence, record that once and stay quiet until the state changes.

## Merge gate

The owner authorizes approving and merging sensible PRs that pass tests.

- Test the exact proposed revision in a clean checkout with pinned dependencies.
  Run synthetic validation for code changes; use the full local profile for
  firmware/emulation/codec changes and affected corpus replays for decoder work.
  Do not accept skipped required tests or reuse reports from another source tree.
- Inspect all required hosted checks and unresolved review findings. Until CI
  exists, absent checks are not a pass: explicit local revision-bound evidence
  and independent review are required. Documentation-only changes need link,
  content and whitespace review, not irrelevant hardware or codec tests.
- Recheck the PR head SHA, base compatibility and mergeability immediately before
  merging; use head-SHA matching for the merge operation. Revalidate relevant
  integration behavior if the base changed. Never bypass repository rules or
  force-push shared branches.
- Submit GitHub approval where the authenticated account is eligible. GitHub
  self-approval restrictions must not be bypassed: use the independent review
  evidence and merge only if repository rules permit it, or report the precise
  missing reviewer requirement.
- Check the publication boundary in CONTRIBUTING.md and LEGAL.md. Keep firmware,
  extracted content, disassembly dumps, recordings, settings and station logs
  out of commits and public evidence. Attach every created PR to this task.

## Issue acceptance and human-dependent work

- #9 is a near-term closure candidate after the checklist is adopted through a
  reviewed merged change. #7 remains open for regional qualification despite
  implemented exact-image validation.
- #10 remains open for incomplete controller/cache, selector and DSP/FPGA
  semantics. Desktop emulation is not physical controller verification.
- #11–#13 need physically demonstrated application-independent recovery and the
  exact reviewed candidate/procedure before a modified boot. Packing stays
  disabled until its evidence gates pass.
- #14/#22 require owned memory and scheduling measurements on the actual target;
  USB receive and host benchmarks cannot close them.
- #8/#33 retain the recorded distribution-review requirements. Do not infer
  approval from general PR merge authorization.
- #26–#30 retain their timing, interlock, operator and phased test prerequisites.
  This automation performs desktop work, without serial/audio device I/O,
  tuning, flashing or transmission. Prepare concrete procedures when hardware
  work is the next dependency and obtain the specific authorization required by
  TEST_POLICY.md. Do not contact the service provider on the owner's behalf.

## Checkpoint

2026-09-27: review and full baseline validation complete; no PRs available to
approve or merge. Recurring task active. Next run: provenance regression fix,
then empty-corpus rejection, followed by reviewed baseline consolidation and CI.
