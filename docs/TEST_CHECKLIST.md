# Per-test checklist

Copy this section into the test record. Keep vendor artifacts and private station
data outside Git; reference hashes and local evidence instead.

- Issue, source revision (including dirty state), date and tester:
- Phase: desktop / receive-only / dummy load / on-air. TX authorized: **no** by default.
- Target: model, official version, exact image SHA-256, or synthetic fixture description:
- Purpose and expected pass/fail results:
- Prerequisites and evidence: dependencies; for hardware, identified test radio (the owner’s single radio is permitted),
  present operator, instruments and immediate stop control. Image/update experiments
  require a settings backup and the applicable recovery evidence under TEST_POLICY.md.
  Read-only stock observations may mark backup/recovery fields N/A with a reason.
  Mark all hardware fields N/A for desktop tests.
- Procedure: commands or numbered steps, with evidence destinations:
- Stop conditions and response: stop on unexpected results; for hardware,
  document phase-specific responses; do not interrupt an in-progress write.
  Modified boots require candidate-specific owner approval under TEST_POLICY.md,
  with recovery evidence or explicit acceptance of its unresolved limitations.
- For future TX only: approved phase-specific plan, operator authorization,
  per-session arm, interlocks, watchdog, cancel/flush and independent monitoring:
- Actual results, evidence, limitations and follow-up:
- Outcome and tester sign-off:

## Completed example: Epic 0 desktop target validation

- Issues: #7 and #9. Date: 2026-09-20. Tester: Codex automated desktop run.
- Revision: based on `1ab637b`, with the Epic 0 working-tree changes; dirty.
  The local firmware report records the full base revision and dirty flag.
- Phase: desktop. TX authorized: no. Radio, backup, recovery, operator presence,
  instruments, hardware stop control and TX prerequisites: N/A; no radio access.
- Targets: original synthetic containers from `tests/test_targets.py`, plus the
  three official image hashes listed in `research/targets.json`.
- Expected: known images accepted, unknown/tampered inputs rejected before output,
  v1.42 tracing inputs verified, and all official images reconstructed identically.
- Prerequisites: Python 3.9+, C compiler/Make, pinned codec dependency and existing
  user-acquired official images. No acquisition or firmware publication in this test.
- Procedure: run `make -j4 test`, then
  `python3 tools/verify_firmware.py --output artifacts/epic0-firmware-results.json`.
- Stop conditions: any failed assertion, unexpected acceptance, output after
  rejection, or roundtrip mismatch stops progression; fix and repeat affected tests.
- Results: 14 Python tests passed; C QSO/codec tests and simulation passed.
  All three official images passed integrity, extraction and byte-identical
  reconstruction. Evidence: local `artifacts/epic0-firmware-results.json`.
- Limitations: synthetic tracing validation is covered; no radio, recovery,
  regional qualification or real-time feasibility is established.
- Outcome: PASS for desktop acceptance, recorded by Codex. Human hardware approval
  is not implied. Issue #7 regional qualification and #8 qualified legal review
  remain outstanding.
