# Recovery and backup access review — 2026-09-20

**Decision:** no demonstrated application-independent recovery route. Modified
firmware testing remains blocked. A main-CPU debug connector is a concrete
investigation lead; it is not yet a qualified programmer interface. No radio
access, case opening, service-mode entry or hardware writes occurred in this review.

## Versioned sources

- Icom service manual S-15218XZ-C1, March 2016, manufacturer-authored
  [copy hosted by RigPix](https://www.rigpix.com/icom/ic7300_service.pdf).
  SHA-256 `223b21ee6566a143252eb8e5f92e15c277c7842732fde403f31cba389c74c171`.
  Relevant PDF pages: 16–17 (adjustment), 22 and 27 (parts), 53 (main board
  layout), 62 (front circuitry), 64 (main CPU circuitry, printed 10-3).
- Icom [full manual](https://icomuk.co.uk/files/icom/PDF/advancedManuals/IC-7300_ENG_FM_12a.pdf),
  SHA-256 `47c2d2035c268895ebe865b5e16610e1c419eb6e267f35519f55708c1c0f8874`.
  PDF page 147 / printed 15-5 describes failed-update repair through an Icom
  distributor. It does not supply an application-independent user recovery method.
- Renesas [R01AN5545EJ0100, Rev. 1.00](https://www.renesas.com/en/document/apn/rza1h-group-example-booting-serial-flash-memory),
  pages 3–4: ROM startup configures serial-flash access, then runs an external
  loader. This is a development-board example, not an IC-7300 recovery procedure
  or evidence of a USB download monitor. The document inconsistently calls the
  mode 1 in section 1.1 and 3 in its abstract/conditions; no strap setting is
  inferred from it.
- Exact official 1.42 image SHA-256
  `8cf5324a126f105cd2307c30b191b9dd8183f86b2c8bf229e61bf9a6a8c32f32`.
  See existing [updater execution evidence](updater-emulation.md).

Manuals and rendered schematic crops remain under ignored `artifacts/docs/`.
The March 2016 schematic is not confirmation of the owner's actual board revision.

## What the documentation establishes

The main-board schematic shows **J491**, a ten-position connector, connected to
IC301 CPU debug nets TCK, TMS, TDI, TDO, TRST and RESET, with H3R3V and ground.
The parts list identifies a 10FLT-SM2-TB connector; the board layout locates J491.
This is materially stronger evidence than guessing from an unlabeled test pad.
However, connector orientation, population, electrical access, debug enablement,
reset behavior and debugger initialization have not been verified on this radio.
No adapter pinout or attachment procedure is approved by this record.

The front-board page also contains a JTAG label beside a different interface with
TOOL0/reset signals. That label must not be mistaken for the main Cortex-A9
connector. Similarly, CP2102 serial communication is not JTAG access.

The service entry described on pages 16–17 opens an adjustment UI, including
calibration controls. Its documented purpose is adjustment, not firmware recovery.
A startup key sequence alone does not establish independence from application
code. Do not execute that procedure as a recovery experiment.

## Backup coverage that must be established

| Storage or data | Evidence | Remaining requirement |
| --- | --- | --- |
| Main CPU flash IC391 | Service parts list: EN25Q64-104HIP; loader selects two regions in its mapped address space | Qualify full-device read/restore, boot area, both application banks and all metadata; verify actual fitted part |
| Main EEPROM IC351 | GT24C128B-2ZLI-TR; separate SDA/SCL device in schematic | Establish contents and calibration/configuration ownership; do not assume settings exports cover it |
| DSP flash IC902 | EN25QH32A identified in prior hardware review | Determine read/restore access and component/configuration coverage |
| Front CPU and FPGA configuration | Distinct components and update paths | Resolve storage ownership and stock restoration dependencies; do not assume all persistent content lives in IC391 |
| SD settings exports | Two files previously observed | Validate parse/restore and covered fields; these are not complete device backups |

The official DAT is an update container, not a verified full-chip backup. It does
not establish preservation of owner-specific calibration or all unused/metadata
regions. Unknown storage ownership remains explicit.

## Bounded bootloader review

Rechecked ARM code at 0x20004334–0x20004373 (comparator) and
0x20004374–0x200043c3 (selector) with Capstone 5.0.3 and the existing reachability
walker. The selector's sole call is the 16-byte comparator. Both conditional
paths converge on a tail branch at 0x200043c0 to decoder 0x2000425c. The selected
bank supplies the decoded length and compressed input; the destination is
0x20005000. No alternate recovery branch or validity-based fallback is present
in these bounded routines. This does not rule out mechanisms elsewhere in the
boot chain, CPU ROM or external service equipment.

Local report: `artifacts/recovery-loader-review.json`, containing source/tool
hashes, both control-flow records and manual hashes. Reproduce the flow records
with `tools.control_flow.walk` on main payload bytes `[0x4000:0x4650]`, base
`0x20004000`, bounds `(0x20004334, 0x20004374)` and
`(0x20004374, 0x200043c4)`, ARM mode. Extract only through the existing exact-image
`tools/emulate_platform.py:inputs` gate. The existing selector emulation provides
independent execution evidence for the two bank choices and malformed records.

## Next decision and concrete service inquiry

First seek documented service capability for the original IC-7300, before
selecting equipment or proposing a physical connection. The following inquiry
is drafted for the owner; **it has not been sent**:

> I have an original IC-7300 running official Main CPU firmware 1.42. What service
> procedure restores official firmware when the main application cannot boot?
> Does it preserve calibration, configuration and bank-selection metadata, and
> what backup coverage is available before an experiment? Is there a supported
> readback procedure or documented service interface for the main-board J491
> connector? Please identify applicable board revisions, required tools and any
> limitations on restoring main, DSP and front-CPU firmware.

A service repair option alone does not meet this project's physically demonstrated
recovery requirement. It can establish the next concrete procedure and dependencies.
If service documentation is unavailable, the next hardware proposal must first
identify the owner's board/parts and connector, then specify electrical isolation,
reset/power ownership and tool initialization. Even debugger attachment can halt
or reset execution and is not equivalent to the authorized CI-V status reads.

Before a restore experiment, require repeated complete reads with matching hashes
for static storage (explain dynamic differences), independent saved copies,
coverage of calibration and selectors, and a reviewed official-content restore
procedure with verification. Entry must be demonstrated without deliberately
corrupting firmware or interrupting power. If these cannot be established, retain
the blocker and continue desktop research only. Issues #11 and #13 remain open.
