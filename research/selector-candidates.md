# Bounded selector-candidate follow-up

Reviewed 2026-09-27 using the pinned offline tools, with no source edits or radio I/O. Input was the registry-validated official v1.42 image, SHA-256 `8cf5324a126f105cd2307c30b191b9dd8183f86b2c8bf229e61bf9a6a8c32f32`, loaded with `emulate_platform.inputs`. Tools were the existing pinned Capstone and Unicorn environment.

## New bounded finding

Five of the 48 aligned-word selector-block candidates have a specific alternate explanation: their four bytes encode a single Thumb-2 register bitmask operation. They do not, when executed at that boundary in Thumb mode, access the selector block or any data memory.

| Candidate address | Independently summarized instruction effect |
| --- | --- |
| 0x2015cc4c | R0 becomes R0 bitwise-AND 0x00ff0000 |
| 0x2015d600 | R0 becomes R0 bitwise-OR 0x00ff0000 |
| 0x2015daa8 | Same register OR operation |
| 0x2015e110 | Same register OR operation |
| 0x2015e504 | Same register OR operation |

Validation: disassembled exactly four original bytes at each address in Thumb mode; each decoded instruction length was four. Executed each instruction with R0 initialized to 0, 0x12345678, and 0xffffffff using a fresh Unicorn Thumb machine, one-instruction limit and data-memory read/write hooks. All 15 trials produced the independently calculated register result and zero data-memory accesses. These are instruction semantics under explicitly selected mode, not evidence of normal runtime reachability or ownership. Small surrounding windows at the first two locations also decode into coherent mask/shift arithmetic, but no startup-to-site path was established.

This narrows interpretation of the scan: numeric coincidence alone cannot justify treating these five values as flash pointers. Retain them as probable instruction-encoding matches pending mode/reachability evidence; do not subtract them from a supposedly complete ownership inventory.

## Exact next bounded experiment

Add a synthetic-testable classification helper that checks candidate overlap with *known reachable Thumb instruction boundaries*, rather than disassembling every candidate as if it were code. Start only with these five addresses. Recover a routine entry and an ARM/Thumb inbound call or mode-qualified predecessor for each; walk at most 512 bytes per routine, record unresolved exits, and refuse a definitive instruction classification if reachability cannot be established. Independently compute the bitmask result and run at most three one-instruction trials per candidate as above. The report should retain raw scan values, ISA justification, semantic classification, and uncertainty. No vendor instruction listing needs publication.

Separately, 0x2018a82c (raw value 0x007f0000) sits among aligned words with high halves progressing 0x7a, 0x7b, 0x7c, 0x7d, 0x7e, 0x7f, 0x80. This is a useful data-table lead, not a proven nonpointer classification. Its consumers must be identified before dismissing it.

## Preserved gates

No complete selector-block reader/writer inventory, remaining-64-KiB ownership, DSP/FPGA update behavior, physical completion, MMU/cache coherency, runtime workspace or recovery evidence follows. Real-image packing remains disabled; modified boots and TX remain outside this experiment. No firmware payload, extracted listing, recording or artifact was added to Git.

## Reproduction

Run `.venv/bin/python tools/probe_selector.py` with the locally acquired pinned
image at `artifacts/original/7300_142.dat`, or provide `--image PATH`. The probe
prints hashes, tool versions, 15 bounded trial outcomes and uncertainty. It
exits nonzero on unexpected semantics or memory access; no device is opened.
