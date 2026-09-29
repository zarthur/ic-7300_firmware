# CPU state publication and DSP command gates

`tools/native_dsp_controls.py` executes bounded original v1.42 ARM slices against
synthetic RAM. It connects shared CPU state to two command bits used by the DSP
output paths. It does not identify the physical native audio lane or establish
control-independent receive gain.

```sh
.venv/bin/python tools/native_dsp_controls.py artifacts/original/7300_142.dat \
  --output artifacts/native-dsp-controls.json
IC7300_TEST_IMAGE=artifacts/original/7300_142.dat \
  .venv/bin/python -m unittest discover -s tests -p test_native_dsp_controls.py -v
```

## State and command boundaries

| Boundary | Original behavior | Qualification |
| --- | --- | --- |
| `0x200523f8..0x20052400` | Copies byte `0x203903f0` into `0x203def59` | All 256 byte values tested; no enum validation. The supplied R4 base is the original caller's literal `0x203def28`. Intervening caller helpers are not executed. |
| `0x200b232c` | Tests pending byte `0x2039071c`; zero returns without refreshing flags | Tests deliberately supply cached flags that disagree with current state. |
| `0x200b233c..0x200b2370` | Consumes pending, extracts `0x2039077e` bits 4/6 into `0x203906c8/c9`, and inverted `0x2039071f` bit 5 into `0x203906ca` | Exact write sequence and neighboring guards checked. |
| `0x200b1a1c..0x200b1a6c` | Starts a zero command word; nonzero cached c8/c9 set bits 23/22. Current `0x2039077e` bit 2 sets command bit 4. | Nonzero means any nonzero byte, including `0x80`; it is not a low-bit test. |

Refresh and command-prefix construction are separate bounded calls. The actual
refresh tail branches to the larger command packer at `0x200b18c0`; the tool does
not execute that intervening code, subsequent command fields, queue submission,
serial transport or DSP execution. A zero pending flag preserves cached c8/c9
while bit 4 still comes from the current state byte. Treating all three bits as
an atomic snapshot of current state would therefore be incorrect.

The report includes 4,608 refresh/packing fixtures and 256 publication fixtures.
The tests additionally check all 256 possible cached first-flag values with
zero/nonzero second flags. Image identity, declared access ranges, writes and
guards are enforced by the original-instruction harness. Reports bind the input,
tools and source revision and reject changes during generation. Existing output
paths are refused. No firmware payload or disassembly is emitted.

## Relation to receive audio

Private inspection of the separately decoded DSP program connects tag 0 to
handler `0x1180a030`, storing its argument at `0x11817b20`. In the audio routine,
bit 23 of that storage selects between a cleared source and a processed source
for context offsets 320..351. Bit 22 gates another processing routine. This is a
static lead; the public tool above does not execute those DSP instructions.

The shared state index comes from an eight-state CPU dispatcher with delayed
transitions. Its request word has multiple writers, including a full-word
publisher and a separate single-bit update. Neither the numerical states nor
command bits are assigned physical RX/TX labels here. The request must not be
simplified to a PTT boolean without qualifying those writers and their callers.

Next work remains the association of the DSP output buffers with native A/B,
mode and control dependence, and lifecycle continuity. The
[interface contract](native-receive-interface.md) and
[confirmed target captures](native-receive-target-capture.md) retain their
existing limitations. These offline CPU checks add no radio or card operation.
