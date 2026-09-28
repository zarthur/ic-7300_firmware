# Main-only change: offline updater write footprint

Input: official v1.42 SHA-256 `8cf5324a126f105cd2307c30b191b9dd8183f86b2c8bf229e61bf9a6a8c32f32`; reviewed checkout c1e787b948c5b02d412b371d1800cef5c8a7f134. Reproduce with `tools/update_footprint.py` and the locally retained official image. Reports contain original analysis only; no device access or modified images occurred.

## Decision-relevant findings

A same-length display-string edit is not a same-length *flash write*. The stored application is compressed. No candidate exists here, so neither compressed byte differences nor affected application erase units are established.

The original transfer routine compares complete 65,536-byte units. Equal units skip erase/program. Unequal units erase and program all 65,536 bytes, including unchanged bytes within the same unit. A final partial unit is padded with FF and still compared/programmed at full-unit width. Therefore matching payload bytes alone do not establish a skipped final unit unless the existing padding also matches.

Executed evidence: official boot bytes with modeled equal initial content skip all writes; the same bytes against erased initial flash cause a full boot-unit erase/program. The same equal/unequal distinction holds for the first stored-application unit. A two-unit synthetic payload differing from erased initial flash at exactly one byte triggers one full-unit erase/program and skips the adjacent equal unit. A one-byte payload also triggers full-unit erase/program. All six transfer cases returned zero with expected modeled payload equality. Actual flash content is not read or inferred.

The main caller always requests a boot transfer of 65,536 bytes to offset zero, followed by 2,370,544 bytes of stored application remainder to offset 0x10000 (selector 0) or 0x400000 (selector 1). These application lengths span 37 erase units if all units differ, but that is a modeled maximum for this official stored length, not the footprint of a future candidate or a known installed bank. Destination contents can differ from the active source bank even when candidate edits are tiny.

Boot preservation is conditional on comparison with physical destination content, not merely preservation of boot bytes in the candidate. With a modeled unchanged-boot flag, activation follows main MD5 comparison. With modeled changed boot, activation precedes main MD5 finalization/comparison. These caller traces substitute transfer outcomes; the independently executed transfer cases support the per-unit semantics but do not form one coherent machine simulation.

For either selector, the separately executed persistent-record writer requests erasure of the entire 64 KiB block at offset 0x7f0000, then programs 16 marker bytes. Thus 65,520 additional erased bytes lie outside the programmed marker. Their ownership/preservation remains unresolved. A one-byte application diff does not avoid this selector-block exposure.

Follow-up correction: the formerly stubbed routine is a component-change flag getter, not the component handler. The harness now executes this getter with modeled zero RAM flags, allowing the main caller to skip component dispatch. Nonzero flags reach an unresolved handshake. Matching identifiers can produce zero flags in the separate header precheck, but live installed identifiers and normal command progression remain unverified. Unchanged supplied component bytes alone do not establish a physical no-touch claim.

## Candidate decision

Proceed only with offline candidate research. A candidate record must distinguish (1) uncompressed semantic edit, (2) compressed stored-byte diff, (3) whole erase-unit write footprint against a specified destination state, and (4) selector-block exposure. Unchanged boot must be verified against destination contents before claiming boot avoidance. Main-only intent cannot currently guarantee DSP/FPGA inactivity.

Remaining uncertainties for candidate validation and the later owner decision: actual current/inactive bank bytes and padding; full selector-block ownership; physical controller/cache/mapping effects and readback; other-component update paths; exact candidate bounded decode/integrity evidence; application-independent software recovery (unproven, to be disclosed for the owner decision). Real-image packing, flashing and TX remain outside this work.
