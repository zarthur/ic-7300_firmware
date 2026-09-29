# First display-only custom boot — 2026-09-29

The owner reports successful installation of the approved exact candidate. A
privately retained photograph shows the intended `Informaiton` label in the
radio's Others menu. This establishes the visible change on the running radio;
it does not establish every updater stage or full post-installation acceptance.

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

## Observed outcome and remaining checks

| Item | Evidence / status |
| --- | --- |
| Visible custom label | PASS: owner reports success; photo shows `Informaiton` in Others |
| Application reaches menu | PASS: visible in the same photo |
| Exact installed flash contents | Not read back; attribution rests on verified prepared card and expected visible result |
| Automatic update completion/restart | Owner's overall success report; specific sequence still unconfirmed |
| Post-install component versions | Pending owner observation |
| Ten-minute receive/audio/UI behavior | Pending owner observation |
| Stock return | Not performed or authorized; would require a separate decision |
| Failed-boot recovery | Unproven |
| Native FT8 resource/interface feasibility | Not established by this test |

Earlier brief taps on the stock updater's YES button produced no subsequent
response. They did not exercise the documented continuous one-second hold and
are not evidence of a same-version rejection. The successful custom label now
provides evidence for this particular candidate installation, not a general
same-version restore guarantee.

## Evidence and disposition

The private `artifacts/display-test-20260929/observation-manifest.json` binds the
approval, media-preparation record, installation observation and original photo.
All referenced hashes were rechecked when preparing this note. Candidate bytes,
settings, photo and detailed station evidence remain unpublished. Historical
reviewed decision packages remain unchanged.

Keep #13 open until remaining post-install checks and the stock-return disposition
are recorded. No additional write is authorized by this note. Recovery #11 and
native receive integration remain separate. Continue the next desktop slice at
`0x2006bfd4` described in [recorder findings](recorder-interface.md) while waiting
for physical observations; do not restart completed candidate construction.
