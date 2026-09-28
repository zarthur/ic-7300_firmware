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

## Wrapper and parser follow-up

The original ordinary wrapper at `0x20086510` explicitly supplies text offset
zero before reaching the prior renderer sink; the probe initializes scratch
nonzero so zero does not arise accidentally from empty modeled RAM. Original
parser routines at `0x200ae0b8` and `0x200bcb40` process both `Information` and
the hypothetical same-length `Custom info` as 11 ordinary ASCII codepoints.
The replacement is supplied in separate scratch memory; application bytes are
never patched. Reports record the NUL lookahead and output guard.

This narrows the caller-offset and character interpretation questions. Font/cache
state, glyph widths and full rendering remain unexecuted, as does normal live row
construction. The tool continues to return `patch_qualified=false`; these results
do not approve an edit interval or establish successful on-screen layout.

## Preferred smaller proposal

[Static embedded-font metrics](label-font-metrics.md) favor `Informaiton`, a
two-character transposition, over `Custom info`: it preserves glyph multiset,
advance and outer ink bounds in both retained fonts. The isolated original ASCII
parser evidence and existing label descriptor remain relevant. No application
bytes have been changed and the patch policy still awaits qualification review.

## Exact local construction policy review

Independent review supports local construction of only `Information` to
`Informaiton`: decoded half-open interval `[0x355773, 0x355775)`, bytes `ti` to
`it`. Require the exact base/application hashes, full original label and NUL,
unchanged descriptor, terminator and every other decoded byte. The generic probes
remain non-authorizing; this narrow reviewed policy is distinct from their
`patch_qualified=false` fields and grants no installation permission.

A further bounded original-code producer probe translates numeric type 1/list ID
`0x3c` to descriptor 41 in an 84-byte row. Producer and renderer refer to the same
context. Its list contents are explicit synthetic inputs, not observed live RAM.
Together with known metadata-based dispatch, ordinary ASCII parsing, and equal
font extents, this supports the local edit while leaving live visibility, final
raster behavior and residual indirect references disclosed.
