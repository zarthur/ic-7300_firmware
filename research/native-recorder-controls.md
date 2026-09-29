# Recorder controls after the native receive tap

The native extraction hook precedes a CPU recorder mute/gain stage. Original
v1.42 instructions now tie that stage to the settings table, without assuming
that similarly placed strings identify nearby values. This is an offline
boundary analysis, not proof that the DSP input ignores physical controls.

## Verified settings association

Original menu selector `0x20086000` uses settings table `0x20190ecc`, with
64-byte records selected by the row's index. The record starts at its value
pointer; the English label is at offset `0x28`, and the option table pointer at
`0x3c`. Starting at the intervening header would associate each value with the
wrong label. The probes execute both language branches for these five records:

| Index | English label | Value pointer |
| --- | --- | --- |
| 35 | RF/SQL Control | `0x203de4ef` |
| 287 | REC Mode | `0x203de70a` |
| 288 | TX REC Audio | `0x203de70b` |
| 289 | RX REC Condition | `0x203de70c` |
| 290 | File Split | `0x203de70d` |

The original UI reads the record's first word at `0x2008b880` before accessing
setting state. Label selection is executed; this separate value-pointer use is
static evidence. The tests do not execute menu changes or option-index rendering.
No transmitted stimulus is involved in investigating the TX REC Audio setting.

## Original post-selection stage

The probe enters at `0x20067328`, after the original six-of-36 sample selection
and earlier recorder suppression gates. It executes the original routing helper
`0x20049044`, gate getter `0x20020318`, signed gain loop, and copy/zero helper
`0x20066ed0`, stopping at `0x200673e4` before fill accounting or publication.
Private fixtures supply the six samples, route tag at `0x20390282`, TX REC Audio
byte, and gate byte at `0x20390104`. Output writes are limited to twelve scratch
bytes and the original metadata byte at `0x2039041e`; guards remain unchanged.

| Numerical tag | TX REC Audio byte | Gate byte | Output |
| --- | --- | --- | --- |
| 2 | either | any tested value | Zero |
| 6 or 7 | either | any tested value | Signed input × 181/256, truncated toward zero |
| 3, 4 or 5 | 1 | any tested value | Unchanged input |
| 3, 4 or 5 | 0 | zero / nonzero | Zero / unchanged input |
| Other tags | either | zero / nonzero | Zero / unchanged input |

Tests cover all 256 tags, both setting values, and gate values 0, 1 and 255:
1,536 combinations. Samples include both PCM16 rails and small signed values
that distinguish truncation from rounding down. The original helper's mode 3
zeros output; mode 5 copies. Numerical tags remain numerical: this experiment
does not independently identify their physical RX/TX meanings.

After publication, the consumer reads RX REC Condition at `0x203de70c` into its
next-block metadata policy. This is distinct from changing native sample values.
The gate byte's upstream writer `0x2002024c` combines an override predicate with
`0x203902d9` and two additional predicates. The base flag is produced by
level/threshold routine `0x2004424c`; control conversion `0x200443cc` depends on
RF/SQL Control and the byte at `0x203dcab5`. Those upstream routines are static
leads, not part of the executed recorder-stage probe. Their complete operating
mode, DSP and physical squelch semantics still need qualification.

## Consequence for the receive interface

A capture before the native queue push bypasses these CPU recorder operations.
A normal recorder WAV alone cannot show whether zeros or attenuation originated
in the DSP, in this stage, or in earlier suppression gates. Compare diagnostic
native samples against ordinary recording only for the confirmed configuration.
The first target capture's unity match is consistent with a copy branch here;
it does not establish every control setting or route.

AF volume, RF gain, DSP AGC and upstream squelch dependence remain separate
questions. No firmware, radio state, DMA register, native cursor, file request or
PTT operation is changed by this tooling.

Reproduce with the pinned original image:

```sh
.venv/bin/python tools/native_recorder_controls.py artifacts/original/7300_142.dat \
  --output artifacts/native-recorder-controls.json
IC7300_TEST_IMAGE=artifacts/original/7300_142.dat \
  .venv/bin/python -m unittest discover -s tests -p test_native_recorder_controls.py -v
```

Reports pin input/application/source hashes and reject changes during analysis.
Original firmware, disassembly and generated detailed evidence remain private.
