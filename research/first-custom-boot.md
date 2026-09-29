# First display-only custom boot — 2026-09-29

The owner reports successful installation of the approved exact candidate. A
privately retained photograph shows the intended `Informaiton` label in the
radio's Others menu. This establishes the visible change on the running radio;
the owner subsequently confirmed automatic restart, unchanged component versions
and about ten minutes of reception without issue. This completes the authorized
display-only observation test; it does not establish recovery or native FT8 feasibility.

## Preparation and identity

The owner confirmed the same original IC-7300, no intervening hardware/software
modifications, normal operation, and component versions Main 1.42 / Front 1.01 /
DSP Program 1.07 / DSP Data 1.00 / FPGA 1.13 before installation. Three readable
settings exports and the entire readable IC-7300 card folder were copied locally
and hash verified. Radio-generated year-2000 filenames do not independently date
the owner's reported fresh save. Settings semantics and restoration are untested;
these exports are not full flash/calibration/selector backups.

The owner explicitly approved preparation and owner-operated installation of the
candidate after disclosure of unproven recovery and possible loss of usability.
Approval applies to decision-package revision 3 and this candidate:

- Candidate SHA-256: `df2cb43ecc4abe86f7f5fc4be4f71f72e88d6b6d5946de45ebb143a344769daa`.
- Official base SHA-256: `8cf5324a126f105cd2307c30b191b9dd8183f86b2c8bf229e61bf9a6a8c32f32`.
- Procedure SHA-256: `3918e1e2bccbecef732c8352c029b709f6c3c1ea9a0983dcfb0f1d50fb16f655`.

The candidate replaced the card's stock update selection only after the stock
copy was verified on the computer. The copied candidate hash was checked, writes
flushed, settings verified unchanged, and the card safely ejected. macOS changed
the associated AppleDouble metadata; this is recorded separately from the exact
firmware payload. No installation command was issued by the agent.

## Observed outcome

| Item | Evidence / status |
| --- | --- |
| Visible custom label | PASS: owner reports success; photo shows `Informaiton` in Others |
| Application reaches menu | PASS: visible in the same photo |
| Exact installed flash contents | Not read back; attribution rests on verified prepared card and expected visible result |
| Automatic update completion/restart | PASS: owner confirms automatic restart completed; individual updater stages were not recorded |
| Post-install component versions | PASS: owner confirms unchanged 1.42 / 1.01 / 1.07 / 1.00 / 1.13 |
| Receive observation and UI | PASS for bounded observation: owner reports about ten minutes receiving without issue; photo and version check establish menu access. Not an instrumented duration/load test |
| Stock return | Not performed or authorized; would require a separate decision |
| Failed-boot recovery | Unproven |
| Native FT8 resource/interface feasibility | Not established by this test |

Earlier brief taps on the stock updater's YES button produced no subsequent
response. They did not exercise the documented continuous one-second hold and
are not evidence of a same-version rejection. The successful custom label now
provides evidence for this particular candidate installation, not a general
same-version restore guarantee.

## Evidence and disposition

The private `artifacts/display-test-20260929/completion-manifest.json` binds the
original observation manifest, approval, media record, original photo and final
owner report. Original evidence and reviewed decision packages are preserved.
Candidate bytes, settings, photo and detailed station evidence remain unpublished.

The authorized display-only test is complete. No additional write is authorized.
Stock-return disposition is explicitly **not performed / not authorized** for this
session; it remains a separate future test, so #13 retains its broader acceptance
gap and #11 remains open. Successful custom boot does not prove failed-boot recovery.

The next major desktop work is the native receive slice at `0x2006bfd4`, described
in [recorder findings](recorder-interface.md). No further first-test readiness
collection or repeat candidate construction is needed to begin that work.
