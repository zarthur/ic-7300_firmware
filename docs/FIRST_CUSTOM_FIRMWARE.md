# Plan for the first custom-firmware experiment

Owner direction, 2026-09-27: use software and the existing computer/radio only.
Build enough evidence for an informed first test; absolute certainty and a
physically proven independent recovery route are not unconditional prerequisites
for presenting that test for the owner's decision. This authorizes preparation,
not an installation. The exact candidate and procedure require a later explicit
decision before any firmware write.

## Objective and scope

Produce one local, exact-base candidate that changes a harmless display label,
plus a reviewable evidence package and proposed installation/observation plan.
The first milestone is a visible change with normal stock receive behavior, not
native FT8 integration. No RF, PTT, timing, calibration, boot-selector, settings
format or compatibility/version identifier changes are intended.

Use the pinned original IC-7300 v1.42 base. Confirm the actual radio's model,
installed version and relevant variant information from existing evidence or
owner observations. A USB device name is not target qualification. Do not buy
hardware, open the radio, attach internal probes, or invent recovery commands.

## Ordered work packages

| Order | Work | Deliverable and exit criteria |
| --- | --- | --- |
| 1 | Freeze the baseline (#7/#10/#31) | Record Git revision, exact base-image hash, pinned dependencies, clean-build results and current device evidence. Re-run affected full local checks and both hosted synthetic jobs. List unknown variant information and resolve anything material to target compatibility before candidate construction. |
| 2A | Trace the candidate's update/boot path (#10) | Map acceptance checks, erase/program ranges and order, selector activation, loader input bounds and known rejection/cleanup paths. Distinguish original execution from modeled hardware. Explicitly identify whether unchanged boot/other components are still rewritten by the stock updater; unchanged bytes do not imply no flash operation. Keep unresolved controller/cache and selector-block behavior visible. |
| 2B | Qualify one display-only patch site (#13/#18) | Trace known references, rendering, length and terminator behavior. Check for control/compatibility uses and indirect-reference uncertainty. Choose a same-length label with exact preimage and allowed interval. Reject a candidate if evidence cannot support display-only use; do not substitute an actual version/compatibility field. |
| 2C | Assess software-only restoration (#11/#32) | Document existing boot/update entry and what remains accessible after each failure class. Separate return-to-stock through a working menu from recovery after failure to boot. Record backup coverage and gaps, including calibration and selector metadata. No deliberate corruption or interrupted writes on the radio. An unknown or unavailable route is a disclosed risk, not invented recovery evidence. |
| 3 | Implement the constrained local candidate builder (#12) | Review the retained local packing primitives and their tests. Enable only a code-reviewed exact-base/exact-region policy after 2A/2B support it; no arbitrary patch or force option. Emit an image only into ignored local storage with a durable audit. Keep patching-related tooling unpublished pending the existing distribution review. |
| 4 | Validate the exact candidate offline (#10/#12/#31) | Run the validation matrix below against immutable inputs. Two clean builds must produce identical candidate hashes. Independently review the patch site, builder, changed ranges, acceptance results and limitations. Resolve failed invariants before advancing. |
| 5 | Assemble the first-test decision package (#13/#32) | Present exact candidate/base hashes, intended visible result, evidence, unresolved risks, current backups, stock baseline observations, installation steps, post-boot checks and conditional restoration procedure. Explicitly state if a failure could leave the radio unusable with the available setup. Ask for the owner's decision once the package is concrete. |
| 6 | Conduct only the specifically authorized test (#13) | Owner present; use the reviewed stock installation mechanism and exact candidate. Observe visible change, boot and normal receive/UI behavior, with no TX test. Follow the predefined failure response and approved return-to-stock steps where accessible. Record actual outcomes; do not infer recovery from successful installation. |

2A, 2B and 2C can run as separate bounded research sub-agents. Integrate their
findings before selecting the candidate policy. Stop inconclusive research after
a bounded pass, record exact gaps, and choose the next question that changes the
candidate decision; do not indefinitely repeat broad scans.

## Offline validation matrix

- Container: known base, dimensions, payload boundaries, integrity fields and
  trailer; reject unknown bases, wrong preimages, changed lengths, overlapping or
  out-of-region edits, truncated input and malformed patch descriptions.
- Decoded application: the intended same-length label is the only decoded change.
  Bootloader and other payload bytes remain identical. Record the actual compressed
  diff, which may be larger than the decoded edit; preserve unused stream tail and
  require candidate-specific original-loader decode within the proven source span,
  including lookahead. A no-op recompression is not proof for the edited candidate.
- Device acceptance: execute recovered original validator/loader routines on the
  actual candidate. Report modeled calls/registers and unexecuted paths explicitly.
  A host checksum pass alone is insufficient.
- Write simulation: enumerate original updater writes for this exact candidate.
  Simulate short reads, corrupt checksums, stuck/delayed completion, write errors
  and interruption at relevant boundaries. Report resulting boot/selector state
  as unknown when the model cannot determine it. These are desktop simulations,
  never instructions to interrupt power during a physical update.
- Reproducibility: bind reports to source revision, dependencies, input/output
  hashes and invariant results. Detect source/artifact changes during validation.
  Require deterministic repeat results and independent review, not test counts
  or a fabricated probability of success.

## Decision rules

Proceed to an owner decision only when the target and exact patch are justified,
required offline checks pass, and a reviewer finds the evidence supports the
proposed limited experiment. Known corruption, unexplained modified bytes,
failed validation, an unsupported base, or an unjustified patch site must be
fixed first. Unknown physical effects remain labeled unknown.

Unproven independent recovery may be accepted only as an explicit risk in the
owner's later decision about this exact candidate. It cannot be silently waived
by a PR merge, a schedule, or this planning request. That decision does not make
issue #11 complete or establish that the radio is recoverable. Do not promise
that a reboot, second bank, USB connection or stock SD file will repair a failed
boot. If software restoration is unavailable, say so plainly.

Define stop conditions by phase: before starting a write, stop for any mismatch;
during a write, follow the documented updater procedure and do not interrupt
power or improvise retries; after a failed boot, stop further actions unless an
already reviewed software recovery procedure applies. Identify any undocumented
failure response in the decision package before the test, not during it.

## First-test record

Prepare these fields without inventing values:

- Base and candidate SHA-256, source commit, exact display preimage/replacement
  and decoded interval; protected-region and compressed-stream audit.
- Test radio/variant/version evidence and current stock boot/receive observations.
- Settings backup location/hash/readability and explicit uncovered storage.
- PASS/FAIL/UNKNOWN evidence table, original versus modeled behavior, independent
  review findings, and potential inability to restore using existing equipment.
- Exact owner-operated installation procedure, expected indications, normal
  receive/UI checks, observation duration, and phase-specific stop response.
- Conditional stock restoration steps and what confirms successful restoration.
- Owner decision tied to candidate hash and procedure revision; date and outcome.

Raw firmware, backups, recordings, settings and detailed station data stay local.
Public PRs may contain original analysis, synthetic tests and sanitized evidence.
No ready-to-flash image or patching tool is published through this plan.

## Execution and completion

The recurring task prioritizes package 1, then parallel 2A–2C, then 3–5. It may
create, review and merge appropriate passing desktop PRs under existing authority.
It must never advance itself into package 6. Notify the owner when the decision
package is ready or a specific missing observation is needed, rather than asking
for broad permission before doing the preparatory work.

A successful first custom boot is not native FT8 readiness. After the visible
experiment, separately plan bounded target memory/timing measurement and native
receive interfaces. Host benchmarks remain useful regression evidence; actual
performance under radio load is unmeasured until observed. TX remains separate.
