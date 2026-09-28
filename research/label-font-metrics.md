# Static font metrics for the first label proposal

`tools/label_metrics.py` reads two length-prefixed font resources in the exact
pinned v1.42 main payload at offsets `0x210000` and `0x240000`. It emits original
metric analysis only, never extracted fonts or a modified application.

| Text | First font advance | Second font advance |
| --- | ---: | ---: |
| Information | 13,174 | 11,264 |
| Custom info | 13,263 | 11,264 |
| Informaiton | 13,174 | 11,264 |

Both resources use 2,048 units per em. Values above are unhinted font units,
not measured screen pixels. All required ASCII glyphs are present. `Custom info`
is 89 units wider in the first font. `Informaiton` swaps only character indices
7 and 8, preserving the glyph multiset, total advance and outer ink bounds in
both resources. Interior ink placement changes, as intended for a visible edit.

Prefer the two-character transposition for the proposed minimal experiment. It
removes the observed widening without adding glyphs or changing the string length
or NUL terminator. This is a proposal for later reviewed local construction, not
an already qualified patch or an installation decision.

The report checks bounded font tables, Unicode mapping, horizontal advances and
glyph outline bounds. It remains explicit that active font/cache selection,
hinting, rounding, clipping, final drawing and live menu-row construction are
unobserved. Equal static extents are not proof of identical raster bounds on the
radio. The report keeps `patch_qualified=false` and `candidate_emitted=false`.

Combine these metrics with the existing original wrapper/parser and descriptor
consumer evidence when reviewing an exact two-byte patch policy. The next label
question is live row/descriptor selection and any remaining known non-display
consumer, rather than requiring an exhaustive graphics-backend simulation. A
reviewer must distinguish evidence needed to justify the local edit from runtime
uncertainty to disclose in the exact-candidate decision package.
