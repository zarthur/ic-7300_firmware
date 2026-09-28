# Software-only restoration and target baseline assessment

Assessment date: 2026-09-27. Repository baseline: `c1e787b948c5b02d412b371d1800cef5c8a7f134`. Scope: existing repository records and existing ignored evidence only; no device interfaces opened, no media written, no third-party contact, read-only research tools and evidence summaries only. This is package 2C under `docs/FIRST_CUSTOM_FIRMWARE.md`, not an installation procedure or authorization.

## Supported conclusion

The owner's radio successfully followed the ordinary official SD update path from Main CPU 1.41 to 1.42. The exact official 1.42 image on the card matched SHA-256 `8cf5324a126f105cd2307c30b191b9dd8183f86b2c8bf229e61bf9a6a8c32f32`. A working-menu return to official firmware is therefore a concrete candidate restoration path, but **same-version reinstall and return from a custom image have not been demonstrated**. It is inaccurate to promote the successful upgrade into a tested rollback procedure.

No existing evidence establishes a software restoration route after failure of the main application to boot. This is an unresolved risk for the later exact-candidate owner decision, not an absolute prerequisite for continuing preparation or presenting that decision. The current plan does not accept that risk on the owner's behalf.

Sources: `research/stock-update.md`; `docs/SUPPORTED_TARGETS.md`; `docs/FIRST_CUSTOM_FIRMWARE.md`; `research/recovery-access.md` (current policy update supersedes its historical unconditional prohibition).

## Failure-class matrix

| Observed or modeled state | Existing evidence | Available software action and limitation | Decision-package status |
| --- | --- | --- | --- |
| Stock application and update menu work | Official 1.41 to 1.42 upgrade and post-update version photo recorded | Ordinary official SD update mechanism is observed. Exact same-version reinstall acceptance/selection and settings effects need confirmation before calling it return-to-stock. No new update is authorized by this assessment. | Upgrade mechanism OBSERVED; same-version restore NOT TESTED |
| Custom application boots; normal menu remains available | No custom image has been installed | Propose the manufacturer-documented ordinary SD mechanism using the pinned original image, conditional on same-version acceptance and the actual menu state. Confirm exact prompts/procedure before owner approval; do not invent a downgrade or force option. | Conditional return-to-stock path; NOT TESTED |
| Custom application boots but updater/UI is unavailable or malfunctioning | No supported alternate software entry established | A normal menu path cannot be assumed accessible. Existing CI-V status reads do not provide a flash read/write or recovery facility. Stop further action unless an already reviewed software procedure applies. | Recovery UNKNOWN; radio may be unusable with present setup |
| Main application fails to boot | Bounded loader routines select one source and decode it; no validity-based alternate fallback in the reviewed bounds | Neither second-bank presence, USB enumeration nor an SD stock file establishes recovery entry. No supported application-independent software procedure in existing evidence. Do not infer that a reboot or bank toggle repairs it. | Recovery UNKNOWN; explicitly disclose possible inability to restore |
| Updater rejects candidate before flash operations | Covered short-read/read-error/cancel tests return without erase/program in those specific modeled paths | This only establishes those traces. A real rejection elsewhere cannot be assumed side-effect-free. Follow a candidate-specific documented pre-write response. | Conditional model evidence; physical behavior NOT TESTED |
| Update interrupted during erase/program or activation | Prefix-write and controller-stall desktop models exist | Some modeled incomplete selector records choose the first source; actual flash interruption need not produce a prefix. Physical selector/flash state and available recovery remain unknown. No power interruption or corruption experiment is proposed. | Model-specific results; physical recovery UNKNOWN |
| Update completes but receive/settings behavior regresses | No custom test yet; no validated settings restoration record | If the menu and approved stock return path remain usable, use only that exact reviewed procedure. Test boot, receive and settings restoration separately; successful stock identification alone is insufficient. | Conditional procedure to prepare; NOT TESTED |

Model evidence: `research/updater-emulation.md`, sections “Main-update caller ordering,” “Persistent-record interruptions,” and “Caller composition and its limits”; historical `artifacts/recovery-loader-review.json`. That existing local loader report has image/manual/tool hashes but no source revision field, so it is historical supporting evidence, not a current-revision validation result. Existing controller results explicitly mark physical equality/selector outcomes unknown on unresolved stalls. The reviewed main updater can activate before final digest comparison when boot bytes are modeled changed; candidate construction must preserve protected boot bytes and still enumerate actual write effects.

## Backup coverage

| Item | What is actually known | What is not established |
| --- | --- | --- |
| Official 1.42 DAT | Exact pinned image hash and successful official upgrade observed | Not a full-device dump; not proof of owner-specific calibration or all persistent metadata coverage |
| SD settings exports | Two 8,224-byte files observed before the September 20 update | Currentness, file hashes, readable contents/covered fields and actual restoration not validated in the cited records; files should not be represented as complete backups |
| Main flash / both application regions / boot area | Addresses and behavior investigated offline | Actual device contents/readback and whole-device software restoration not established |
| Selector metadata and remainder of its block | Bounded marker/activation models | Complete block ownership, current contents and backup/restore coverage unknown |
| Main EEPROM / calibration / configuration | Separate storage identified in historical schematic review | Owner-specific data ownership and inclusion in settings export unknown |
| DSP, front CPU, FPGA-related storage | Separate components and reported installed versions known | Complete backup/restore coverage and interrupted-update dependencies not established |

Sources: `research/stock-update.md`; backup table and bounded review in `research/recovery-access.md`; inventory in `docs/PLATFORM_VALIDATION.md`. No proposed hardware purchases, internal access or service contact are needed to record these limitations.

## Identity and region observations still needed

Existing evidence already supports original-model IC-7300 use and a photographed version screen: Main CPU 1.42, Front CPU 1.01, DSP Program 1.07, DSP Data 1.00, FPGA 1.13. The successful official upgrade is stronger evidence of compatibility with this exact official image than the USB interface name. CI-V frequency/mode requests in `artifacts/radio-status-first-read.json` do not independently identify region or firmware version. Exact frames, operating settings and device identifiers remain local.

Material owner observations to collect when needed, without opening the radio or conducting a firmware write:

1. Confirm the same radio is being prepared and that no firmware/component changes occurred since the recorded version photograph. If uncertain, a current version-screen observation resolves this; do not request a serial number merely to reconfirm a fact already recorded.
2. Identify the market/region variant from existing purchase records or externally visible model/regulatory labeling, redacting serial/private data in public summaries. Separate market-of-sale evidence from present operating location and operator license. Record exactly what the label/record establishes; do not infer a regional variant from a call sign, USB name or current frequency.
3. Confirm the provenance of the official image used on this radio (existing September 20 image hash already recorded) and whether the owner has any knowledge of nonstandard firmware, regional conversion or hardware modification material to compatibility. Do not assume such changes exist or require intrusive board identification without evidence it affects the chosen image/patch.
4. Before the later installation decision, obtain current stock boot/receive observations, current readable settings-backup evidence and the observed availability of the ordinary update menu. These are readiness observations, not proof of failed-boot recovery. Menu observation must not become an unapproved installation.

Region qualification remains open under #7. An unknown board/flash revision alone is not a reason to require disassembly or new hardware; package 2A must explain whether any unresolved identity fact is material to the actual candidate before construction.

## Next bounded action

Combine this matrix with package 2A's candidate-specific updater trace and package 2B's qualified display site. For a same-version return-to-stock proposal, inspect the existing version/component-identifier acceptance evidence and retained manufacturer instructions; report any unresolved same-version behavior rather than guessing a force/recovery sequence. No additional broad scan is needed for package 2C now.

The owner decision package must say plainly: a failed boot could leave the radio unusable with the available computer/radio setup, and no tested independent software restoration is presently demonstrated. A later explicit decision may accept that exact-candidate risk; neither this assessment nor passing/merged desktop PRs does so. During any subsequently authorized update, follow the reviewed updater procedure without power interruption or improvised retries. After failed boot, stop unless a previously reviewed applicable software procedure exists.

## Component equality follow-up

[Bounded original-code checks](same-version-acceptance.md) accept matching
component identifiers and still validate the main payload. Header, payload and
update are separately dispatched commands; the normal UI command producer is
unresolved. This narrows the uncertainty without demonstrating same-version
reinstallation or changing the failure-class matrix above.

## Exact-candidate procedure review

The retained manufacturer full manual (printed 15-5/15-6) documents the normal
SD update path, final one-second YES confirmation, progress and automatic restart.
Printed 8-4 documents settings export; 8-6 documents selective loading and the
CI-V/REF Adjust effects of ALL. These pages were visually reviewed for the local
conditional decision package. They do not endorse custom images or establish
same-version acceptance. No media or radio operation was performed.

The proposed procedure distinguishes pre-write cancellation, maintaining power
and media during the write, and no improvised recovery after abnormal completion.
There is no documented software-only response to a hung update or failed boot
within the reviewed evidence. This limitation must be accepted or declined by the
owner before an exact-candidate test, not discovered through an intentional
interruption. Settings-load actions require their own scope review; no blind ALL
restore is proposed.

[Further bounded handshake inspection](update-handshake-boundaries.md) resolves
six flags and a byte threshold without identifying a direct same-version
rejection. It stops before interrupt/device effects; normal UI completion remains
untested and no bypass is proposed.
