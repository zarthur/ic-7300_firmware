# First display-label investigation

The exact official v1.42 application contains the English `Information` label at
`0x2035a76c` (11 bytes followed by NUL). Menu descriptor 41 references it at
`0x20190208`. The adjacent descriptor fields, terminator, and separate version
identifiers must remain unchanged in any later proposal.

`tools/display_label.py` verifies the pinned image and decoded application, checks
these preimages, scans literal references to the label and its interior, and runs
a bounded original-code menu trace with synthetic state. The trace reaches the
renderer entry with the label pointer and length 11. A separate original subtype
load/switch takes the ordinary text path for subtype 0, excluding the known
subtype-1 first-byte icon consumer in that modeled state.

This is not patch qualification. The lower renderer/glyph parser has not been
executed, live menu row and caller text-offset invariants are unresolved, and
literal-pointer scans do not prove absence of computed or mixed-ISA consumers.
The report therefore sets `patch_qualified=false` and approves no byte interval.
No firmware is modified or emitted. Same byte length alone does not establish
safe rendering or bounded compressed-image changes.

Next investigate the lower renderer and normal caller construction, then decide
whether one same-length printable label can be qualified. Only then review the
local candidate builder and validate its exact output under the original loader,
updater and protected-byte rules in `docs/FIRST_CUSTOM_FIRMWARE.md`. Report
remaining uncertainty in the candidate decision package; do not convert desktop
trace success into installation approval.
