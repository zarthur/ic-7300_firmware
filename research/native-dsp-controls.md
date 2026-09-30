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

## ACC/USB output-level command

The same tool now executes the original menu-label selector for settings 76,
77 and 80. Their value pointers identify `ACC/USB Output Select` at
`0x203de518`, `ACC/USB AF Output Level` at `0x203de519`, and
`ACC/USB IF Output Level` at `0x203de51c`.

Original helper `0x2001fb98` chooses the AF level when Output Select is zero,
otherwise the IF level. It calls interpolation routine `0x2000621c`, including
the original Thumb integer division at `0x2017c618`. Its three table points are
`(0,0), (128,100), (255,150)`. Integer interpolation maps a level byte `x` to
`floor(100*x/128)` below 128, otherwise `100+floor(50*(x-128)/127)`.
These are internal setting bytes, not displayed percentages or measured gain.

The result is stored at `0x20390101`. A separate call to `0x2001fbe8` publishes
it at `0x203def36`; command packing at `0x200b2120..0x200b2144` places it in
bits 15..8 of tag `0x4a`. The command's other payload bytes are supplied
independently. Exact write footprints, source preservation and guards are
checked across these bounded calls; caller scheduling and transport are not
executed. The report adds 3,072 fixtures covering every level byte with
zero/nonzero selector values and varied unselected settings. Tests also vary
all selector bytes and the command's other payload bytes.

Private static DSP inspection connects the command field to a cached gain
calculation in producer `0x1180fdd8`, whose final conversion writes context
offsets 256..287. The public CPU probe does not execute that producer, establish
its full numerical gain, or identify it as native A/B. Changing an ACC/USB level
is therefore a possible discriminating experiment, not yet a qualified native
receive control contract.

## CPU status publication and a downstream request gate

Original receive-word slice `0x200b0dc4..0x200b0e00` reads a supplied word
from `0x203906b8+24`, uses its top nibble as an index into the 16-word table
at `0x20414c48`, and aliases nibble 9 to index 1. The word itself is stored
unchanged. The private `cpu-dsp-status-trial` executes 1,024 cases covering
all high bytes and four payload patterns. This establishes software dispatch
after a word is available, not the wire framing, physical transport or source
of that word.

The publication slice `0x200b50a8..0x200b50bc` copies bits 5 and 4 of the
first table byte into `0x203def54` and `0x203def55`, respectively. All 256
input bytes are checked, with exact writes and unchanged source memory. The
supplied source and destination bases match the enclosing caller's literals.
Consequently, a nibble-zero status word carrying the DSP's AF-derived bit 4
has a software path into shared byte `0x203def55`. Actual receipt of the DSP
word on this CPU path remains a transport qualification.

One consumer is the original slice `0x2006c704..0x2006c790`. It takes a prior
request in R4 and uses these states:

- `0x203903f1` bit 6 enables the gate.
- `0x203def55` nonzero sets gate bit 6 in `0x203904c8` and clears counter byte
  `0x203fc620` when enabled.
- With the input clear, an already-set gate remains until that counter reaches
  20. Disabling the gate clears its bit immediately.
- Final request bit 5 in `0x203904c8` is set only when the supplied R4 request
  is nonzero and gate bit 6 is clear. Other flag bits are preserved.

The original slice passes 8,192 fixtures spanning every initial flag byte,
enable/input combinations, counters 0/19/20/255 and both supplied requests.
Another 1,024 linked fixtures run dispatch, publication and gating sequentially
with a nibble-zero word; they use the preceding slice's actual memory output.
The intervening callers, prior-request calculation, timer advancement and
later request consumers are not executed. Twenty is a counter threshold,
not a measured duration. No physical RX/TX label or UI function is assigned
to these bytes by these checks.

This extends the [AF-status investigation](native-dsp-receive-input.md) beyond
a reporting-only interpretation: CPU software can use the received bit in
request gating. It does not establish that the gate changes native samples,
nor that the receive diagnostic introduces a route to PTT. All execution is
offline against synthetic memory, with no radio, serial or card operation.

### Request hold and connection to the state dispatcher

Original getter `0x2006c794` returns bit 5 of `0x203904c8`. The selected
caller path at `0x20065580..0x2006561c` executes this getter. When asserted,
it clears byte `0x203fc61f` and ORs bit 14 into the aggregate request being
built on the stack. If the getter is clear but the previous request had bit 14,
the path retains that bit while the counter at `0x203fc61f` is below a threshold.
Otherwise it leaves the current aggregate unchanged.

For settings base `0x203de4cc`, the threshold starts as
`(2 + 10 * byte[+0x27e]) & 255`. If halfword `0x203903fa` has bit 14 set,
it adds the original lookup entry selected by byte `+0x27f`, again retaining
the low byte. The four entries tested at `0x2019e53c` are 0, 5, 10 and 20.
The allowed UI settings and elapsed time represented by the counter are not
established by this arithmetic.

The private `cpu-af-request-trial` passes 4,584 original-instruction fixtures
covering assertion, release, threshold boundaries, unrelated aggregate bits and
byte wrapping. It then runs original publication at `0x20065790`, which writes
the changed aggregate halfword to `0x203903f4`, followed by the original request
load, snapshot bookkeeping and state-zero dispatcher path at `0x20065908`.
With state index zero, a resulting zero request preserves index zero; a nonzero
request selects index one and resets transition counter `0x203903c8`. Exact
state/history writes, input preservation and surrounding guards are checked.

This connects the gated request to the existing state machine under supplied
caller conditions. Earlier eligibility guards and intervening aggregate edits
are explicitly omitted; no helper is replaced by a fabricated success value.
Other state handlers, physical transition effects and the upstream wire mapping
are outside this connected fixture. The AF-derived status therefore cannot be
classified as UI-only, but neither state index one nor request bit 14 is assigned
a physical TX meaning here.

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
