# DSP receive input: source map and qualification limits

The original v1.42 DSP image connects a serial input from the FPGA to the
sample context consumed by `0x1180e918`. This is a source-side map. It does not
by itself establish the complete transformation to the CPU's native receive
queues or qualify a production capture adapter.

## Board connection and configured format

Visual review of the IC-7300 service manual, PDF pages 66 and 68, identifies
`DFR_MOD` between FPGA IC1351 (EP4CE55F23I7N), pin A9, and DSP pin 115 through
R925 (100 ohms). The TMS320C6745 data sheet, PDF page 27, identifies DSP pin 115
as `AXR0[3]`; adjacent pin 114 is DVDD. Original McASP initialization configures
serializer 3 as a receiver. The net label alone does not establish sample
content, modulation semantics, or rate.

The original initialization model writes `RFMT=0x180f0`, `RMASK=0xffffffff`,
`AFSRCTL=0x111`, and `RTDM=3`. TI SPRUH91D, pages 1061–1063, decodes these as
32-bit slots, MSB first, one-bit delay, no rotation, DMA-port access, and two
active slots with externally generated word-wide frame sync. The configured
frame-start edge is falling. These are initialization values, not live register
measurements. Receiver clock polarity cannot be inferred from ACLKRCTL alone
without accounting for ACLKXCTL.ASYNC.

## Memory path

| Stage | Evidence-backed layout |
| --- | --- |
| RX descriptors | Original constructor `0x11814954` and helper `0x11814c44` build active slot 0 and linked slots 34/35. |
| DMA source | Initialized pointer `0x11832120` contains `0x01d02000`. |
| Destination banks | `0x1181e550` and `0x1181e610`, 192 bytes each. |
| Transfer layout | A-synchronized, ACNT 12, BCNT 2, CCNT 8; destination BIDX 96 and CIDX −84; source indices zero. |
| Context extraction | Original routing slice writes context `0x11818bd0 + 4*i` from `RX_base + bank*192 + i*12`, for `i=0..7`, masking with `0xffffff00`. |
| Conversion | Original scheduled loop converts each word as signed 32-bit, rounds to float32, then multiplies by `2^-31` with another float32 rounding. Output starts at `0x11819de0`. |

The constructor fixtures verify exact descriptor words, null-pointer rejection,
untouched neighbors and stack preservation. An independent descriptor walk
covers every word in each bank once. Under ascending active-serializer order
and an aligned initial FIFO phase, the context groups map as follows:

| Serializer | Slot 0 context offset | Slot 1 context offset |
| --- | ---: | ---: |
| 3 | 0 | 32 |
| 5 | 64 | 96 |
| 7 | 128 | 160 |

The first converted context group therefore conditionally maps to `DFR_MOD`,
slot 0. Initial FIFO phase, physical frame alignment, EDMA ownership, cache
behavior, and interrupt ordering remain unverified. The two slots must not be
labeled I/Q or left/right without further evidence.

Routing and conversion were executed as separate original-code slices with
actual fixture values connected. The call chain through `0x118125e4`,
`0x118104c0`, and `0x118109a0` is pinned statically: it passes the context to
`0x1180e918`. This does not execute the entire intervening routine or exclude
other writers.

## Input ramp and mute command

The scheduled ramp adds float32 `1/960` to its state per sample and caps it at
one. It multiplies the input only when the updated state is positive; otherwise
it writes zero. Negative state is retained. Float rounding matters: in the
qualified eight-sample sequences, the first block ending at unity was block
121 from zero and block 241 from minus one. These are model block counts,
not measured radio time.

The original branch selector reads command `0x11817b24` bit 0, a signed halfword
at B14+2, and prior ramp state at B14+752. A set command bit selects `0x1180eb4c`;
otherwise a positive halfword and nonnegative prior state select `0x1180eb30`;
other cases enter ramp preparation. The zeroing paths remain static evidence.

The original CPU setter at `0x200b2f60` constructs command 01 bit 0 as:

```
(0x203906f0 != 0) ? 1 : (0x203906d4 & 1)
```

It preserves other bits, refreshes the cache, and enqueues only changed words.
The original DSP handler at `0x1180a00c` stores that command at `0x11817b24`,
saving its predecessor at `0x11818504`. Connected fixtures verify publication,
handler storage and branch selection. Physical transport, live flag meaning,
and complete transition semantics remain outside these fixtures.

### Transition request and release

The original request helper `0x200b3718` acts only while `0x2039077e` bit 6 is
set. It computes `(100 - 2*argument) & 255`. If the pending byte `0x203906d4` is
zero, or counter `0x2039076e` exceeds this threshold, it writes the threshold,
sets pending to one, and calls the command setter. An equal counter does not
refresh the request. The previously traced RXS-state mismatch supplies argument
2, hence threshold 96; this does not itself identify physical signal settling.

Release helper `0x200b376c` clears a nonzero pending byte when state bit 6 clears
or the counter reaches at least 100. Independently, it mirrors forced-mute byte
`0x203906f0` into `0x20390718`. Either change invokes the setter. Clearing pending
therefore leaves command bit 0 asserted when forced mute remains nonzero.

The counter prefix at `0x200b7910` increments four adjacent bytes independently,
including `0x2039076e`, with modulo-256 wrapping and no carry between bytes.
The timer-service parity gate at `0x20005bb4` reaches the call at `0x20005bd0`
on every second service. Combined with the [timer configuration](native-receive-timing.md),
this gives an intended counter cadence of 500 microseconds. Four increments
from 96 to 100 span two milliseconds of nominal scheduled cadence, **not a
guaranteed request-to-unmute duration**. Initial phase, interrupt delivery,
release polling, other writers, forced mute, and DSP delivery remain relevant.

Original-code fixtures cover 720 requests, 648 releases, 2,048 counter-prefix
cases, and all 256 parity-gate values. Twelve composed sequences execute request,
counter increments and release against shared synthetic state, verifying the
four-increment threshold and forced-mute retention. The parity probe stops
before the intervening call at `0x20005bcc`; the full interrupt routine and its
ordering relative to release polling are not executed by these fixtures.

## Ordinary receive processing: qualified slices

On the ordinary branch at `0x1180ed24`, the caller first invokes `0x1180c610`.
That routine writes the coefficient at B14+24; its complete gain calculation
remains unqualified. The scheduled loop at `0x1180ed44` then multiplies eight
float32 samples at stack+40 by that coefficient in place. This is a separate
gain stage from the input ramp.

The next call, `0x1180cc44`, takes stack+40 as input and stack+104 as output.
Its final command-bit-14 test controls replacement of the processed output
with the original eight inputs. Both replacement-copy schedules preserve all
eight words in the tested disjoint buffers. This does not imply that internal
filter state remains unchanged while output is bypassed. The following loop
selects output indices 0, 2, 4 and 6 into stack+88..100. Scheduled-loop fixtures
verify these transformations for 120 input/gain combinations; the filter body
and branch selection are outside those fixtures.

The call chain then passes those four samples through `0x1180cfa0`, writing
stack+72..84, and `0x1180d058`, writing stack+136..148. The latter wrapper and
its original filter helper `0x118007cc` were interpreted together: each input
is multiplied by float32 0.1, processed through descriptor `0x11818798`, then
multiplied by 10. Each multiply rounds separately, so these factors must not
simply be cancelled. Tests with a supplied two-section filter cover 128 cases
and 32 consecutive groups, checking output, state updates, bounded writes and
interrupt-enable restoration. They do not identify the descriptor's actual
runtime coefficients or qualify the preceding `0x1180cfa0` stage. The table-path
follow-up below supplies original coefficients for one selection range.
Complete processing after `0x1180d058` and association with the CPU receive
lane remain open; subsequent qualified slices are described below.

### Original six-section coefficient tables

Static review of `0x11807ea0` identifies a table path controlled by the low six
bits of command `0x11817b34`. Values 11–23 select table 2, 24–29 select table 1,
and 30–63 select table 0. Each table contains 24 float32 coefficients starting
at `0x11823428 + 96*selector`; its gain comes from
`0x11825290 + 4*selector`. The copy loop writes six sections through the pointer
in template `0x118188a0`, then that template is passed to setup for descriptor
`0x11818798`. Subsequent coefficient-generation guards in this routine require
a low-six-bit value below 11, so their bodies are bypassed for this range.

The template's initialization record contains pointer `0x118187c0`, gain zero,
and count 14. These are mutable startup values; treating them as the active
filter configuration would be incorrect. The three original table gains are
approximately 0.05668712, 0.01758705 and 0.003909986. Their UI meaning and the
other coefficient-generation paths remain unresolved.

Using the exact table bytes, twelve original preallocated-setup cases verify
coefficient copying and descriptor publication. The original wrapper/filter
model then passes 192 four-sample groups (768 filter calls), checking output
and retained state against an independent recurrence. Selection and template
publication remain static evidence; setup and processing were executed as
separate slices with the same table data. This does not establish current radio
selection, allocation behavior, or the other handler at `0x11808bb0`.

### Zero output with continuing envelope updates

The next call, `0x1180d638`, receives the four samples at stack+136 and writes
stack+8. In its initialized, unchanged-parameter path, bit 5 of command
`0x11817b20` selects a loop that filters each input's absolute value through
descriptor `0x11818700`, while writing four zero words to the output. Filter
state therefore continues to change during this zero-output branch. The
remaining metering tail is outside the executed slice.

The initialized template at `0x118186f0` specifies one section with gain
approximately 0.001023218. Separate original setup and processing slices using
its exact coefficients pass four setup cases and 512 filter calls with retained
state, matching an independent recurrence. Another 128 cases cover supplied
filter state, unrelated command bits and interrupt-enable restoration. Reset,
parameter changes, the complete bit-5-clear processing branch, current radio selection
and subsequent output routing remain unqualified.

### History processing with bit 5 clear

The slice `0x1180d778..0x1180d868` qualifies the next branch's four-sample
history operation. It uses a 24-word ring at `0x11818728`, a four-word working
buffer at `0x11818788`, and a cursor read from B14+544. Starting with prior
gain `g`, it computes `step = float32(float32(target - g) * 0.25)`. For each
sample, in order:

1. Write `float32(input * g)` to the working buffer.
2. Write `float32(float32(old_ring_sample * g) * scale)` to the output, where
   `scale` has float32 bits `0x3f71dbea` (approximately 0.944761872).
3. Replace that ring entry with the raw input, advance the cursor modulo 24,
   and update `g = float32(g + step)`.

The instruction pipeline matters: successive operations using the same
register name can consume different outstanding load/multiply results.
Treating the text as sequential scalar operations incorrectly suggests a
squared-gain path. Scheduled original-code interpretation instead matches the
recurrence above across all 24 cursor positions, four gain trajectories and
both initial interrupt-enable states (192 cases). A further 24-group sequence
places an impulse at the output six four-sample groups later, including ring
wrap. This establishes a 24-sample history delay in the model, not a duration
in seconds or an end-to-end radio latency.

The slice stores the final gain at B14+552 and leaves the next cursor in B7.
It stops before the call to `0x1180d190` and the parallel cursor publication at
`0x1180d86c`. Those effects, the surrounding parameter lifecycle and remaining
output routing are still open.

### Energy measurement for gain feedback

The enabled-processing prefix of `0x1180d190` consumes the four current samples
from the working buffer. For each sample it forms a float32 sum of its square
and the previous sample's square, then updates a smoothed value as
`float32(e + float32(float32(sum - e) * coefficient))`. It uses the rise
coefficient when `e < sum`, otherwise the fall coefficient. Original tables
at `0x11825180` and `0x11825190` contain, respectively, `[1, 0.02, 0.5, 0.5]`
and `[1, 0.02, 0.1, 0.1]` rounded to float32. The qualified selector is
`B14+72 + 2*command_bit7`, with B14+72 supplied as zero or one.

The routine retains the final square at B14+184, the smoothed sum at B14+168,
and half that sum at B14+152. Original-code fixtures pass 192 cases and four
32-group sequences using those table values. Four further 32-group sequences
feed actual modeled history-stage working-buffer values into this prefix.
They preserve the cross-group sample-square state; they do not close the
feedback loop because the upstream target gain is still supplied.

This execution uses command bit 8 set, command 01 bit 0 clear, and a zero
holdoff halfword at B14+2. It stops at `0x1180d39c`, before the threshold,
hold/release, metering and nonlinear mapping that produces the return factor.
The threshold stage is qualified below. The later metering and nonlinear
effects, and the final gain applied to subsequent groups, remain unqualified;
the table selector is not yet assigned a radio UI meaning.

### Threshold and hold/release updates

The next slice, `0x1180d39c..0x1180d50c`, subtracts the original float32
threshold 0.14 from the half-energy measurement and floors the result at zero.
It compares this target with the prior value at B14+164. With command bit 7
clear, a rise limits the difference to 2 or 1 and multiplies it by 0.004 or
0.0003, respectively, for the qualified B14+72 values zero or one. It adds that
increment to the prior value and clears the counter at B14+4.

On a fall or equality, the signed counter is compared with the limit at B14+36.
Below the limit it increments and uses the original pair approximately
`(4.1e-6, 1.5e-7)`. At or above the limit it is set to the limit and uses the
pair stored at `0x11817be0`. The update subtracts both a coefficient times the
difference and an additive decrement, with separate float32 roundings, then
floors the result at zero. Bit 7 instead selects a 0.003 rise coefficient and
a mixed single/double-precision 0.03 fall calculation; its falling path leaves
the counter unchanged. Both paths publish the result at B14+160 and B14+164.

Original instruction execution passes 300 cases spanning threshold equality,
counter boundaries, wrap-adjacent signed values and both command-bit states,
plus four 64-group sequences. The release pair's writer at `0x11806aa4` selects
two words from `0x11824088 + 8*(command & 15)`. Its supplied command register is
statically associated with the preceding load of `0x11817b3c`. All 16 original
table entries pass 64 publication cases and 384 connected threshold cases.
These tests qualify coefficient use without assigning UI meanings or physical
hold times. The subsequent RF-dependent floor, meter aggregation and nonlinear
mapping still separate this state update from the returned feedback factor.

### Smoothed lower bound, meter fields and nonlinear call

The original caller from `0x1180d50c` through its transfer to `0x11816be0`
updates B14+180 as the float32 sum of `0.005 * B14+44` and `0.995 * prior`.
It chooses the larger of this smoothed lower bound and the preceding attenuation
state, and publishes the selected value at B14+156. All multiplications and
additions round separately.

It also accumulates the selected value at B14+172 while incrementing B14+176.
For nonnegative counters starting at zero, the ninth call updates the low ten
bits of two halfwords at `0x11817ba8+10` and `+34`, preserving their upper bits,
then clears the accumulator and counter. The encoded integer is derived by
separate float32 multiplies by 0.3375 and 4096, truncation, and an upper clamp
of 1023. This is a call-count relationship, not a measured update interval.

The nonlinear helper receives A4=10 and
`B4 = float32(30 * negate(selected_value))`, with return address `0x1180d618`.
The caller qualification passes 180 boundary cases and a 64-group sequence,
stopping at the helper entry without supplying an invented return value.

The helper's nonzero-exponent path uses `RCPDP` in the routine at
`0x11816a80`. TI SPRUFE8B page 409 specifies an approximation error bound, not
an exact result bit pattern. Clearing part of that result's high word at
`0x11816a90` does not clear its low word. A host logarithm or power calculation
therefore cannot be presented as verified original-helper execution. Its
numerical result and the final returned gain factor remain open.

## Mode-selected output callback

The ordinary caller at `0x1180ee50` dispatches through B14+748 with the
context in A4 and a four-sample buffer at SP+24 in B4. It retains the returned
float, writes `float32(returned_value * 7.5)` to context+684, and passes the
unscaled return to `0x1180de18`. This is static dataflow; it does not yet tie
that value to a particular physical output lane.

The mode handler indexes the original table at `0x11832270` with command
bits 15..8. All 17 entries have audited straight-line setup constants:

| Command mode byte | Processor stored at B14+484 |
| --- | --- |
| 0–9, 14 | `0x1180a140` |
| 10 | `0x11802b84` |
| 11–13, 16 | `0x11803128` |
| 15 | `0x11802e30` |

Bytes greater than 16 branch to the same setup as entries 6–9 and 14.
Modes 4 and 5 additionally select secondary callback `0x1180282c` at
B14+204; the other table entries select `0x1180a12c`. Mode 10 sets B14+72
to one; all other entries set it to zero. These are command encodings,
not independently established UI labels.

Each setup writes countdown 60 at B14+756 and transition callback
`0x11804350` at B14+748. That callback compares the signed countdown with
zero: positive values decrement; nonpositive values install B14+484 as
the next callback and clear the countdown. Both paths return zero. Thus,
with no intervening setter or concurrent change, starting at 60 gives 60
decrementing calls, then one call that installs the processor while still
returning zero. The processor can run on the following dispatch. This is
a call-count inference from the instructions, not a measured mute interval.

`dsp-output-callback-audit` pins the original table and instruction bytes and
checks the setup constants. It is a static audit, not execution of the
complete mode handler or the selected processors. Their numerical behavior,
subsequent routing and runtime transition timing remain open.

## Common output processor

A restricted instruction model covers the stable processing body
`0x1180a224..0x1180a2d0` of callback `0x1180a140`, including the original
`0x118007cc` filters and secondary callback `0x1180a12c`. Initialized filter
descriptors are supplied from the original cinit templates; allocation and
reset branches preceding the body are not executed.

For each four-sample group, the processor multiplies each input by float32
0.7, then by the corresponding entry of `[1, 0, -1, 0]` from
`0x11825110`, starting at the phase index B14+988. Each multiplication rounds
separately. Every result passes through the two-section filter at descriptor
`0x1181a8a8`, using template `0x1181a890` and gain
`0.09832599759101868`. The phase advances modulo four per input, so its value
is unchanged after a complete group.

Only the first of the four filtered results feeds the next stage. The remaining
three still advance filter state. That selected result is multiplied, with
separate float32 roundings, by 0.8 and 4, by 0.25 in callback `0x1180a12c`,
and by 0.5 afterward. It then passes through the one-section filter at
`0x1181a8d0`, using template `0x1181a89c` and gain
`0.9636527895927429`; this filter's return is the processor's return value.

`dsp-common-output-trial` passes 128 cases across all four phase indices and
both initial interrupt-enable states, plus four 32-group stateful sequences.
It compares filter inputs, intermediate outputs, final outputs and both filter
states with an independent arithmetic reference. Incorrect load or floating-point
latencies are rejected. These checks cover the secondary callback selected by
mode bytes 0–3, 6–9 and 14, not the alternate callback for modes 4 and 5.
They do not exclude runtime coefficient changes or establish physical sample
rate, lane identity, or complete downstream gain.

## Publication into serializer-4 context words

The outer caller saves the receive routine's return in B10 at `0x118109a8`.
Static tracing reaches an eight-iteration loop at `0x11810a00..0x11810aa0`:
it repeatedly supplies that value to filter descriptor `0x11817e78`, adds
context words 704 through 732, applies a controlled gain and float32 0.45,
and writes eight results to SP+56 through SP+84. The context words are cleared
as they are consumed. The body `0x118109b8..0x11810aa4` is now qualified with
an initialized descriptor supplied from original template `0x11817d7c`, a
supplied receive return, and the original filter instructions.

With command `0x11817b20` bit 10 set, the nonnegative counter at B14+400
increments per output sample and caps at 960. With that bit clear, it decreases
by two per sample and floors at zero. The gain is the float32 product of this
counter and float32 `1/960`, clamped to [0, 1]. Each of the eight outputs is
`float32(float32(float32(addend + filtered_return) * gain) * float32(0.45))`.
The same receive return is supplied to the filter eight times, while its state
advances between samples. This is a count relationship, not a measured ramp time
or an established UI-control mapping.

`dsp-output-interpolation-trial` passes 144 cases, two 125-group sequences
covering full rise/fall trajectories, and 32 groups feeding its actual modeled
outputs into the separately qualified publication loop. The connected fixture
uses zero auxiliary/mix inputs; it is not uninterrupted execution of the full
caller. Filter state, gain-counter publication, all outputs and clearing of the
eight context addends are checked. Incorrect load/FP latencies are rejected.
Startup/reset paths and runtime coefficient changes remain unqualified.

The original publication loop `0x11811250..0x118112e0` is qualified separately
with supplied buffers and the original filter. For output index `i = 0..3`,
its filter input is:

```
main_term = float32(15 * main[2*i])
combined  = float32(auxiliary[i] + main_term)
mix_term  = float32(8.392573356628418 * mix[i])
input     = float32(mix_term + combined)
```

Here `main` is SP+56, `auxiliary` is SP+88, and `mix` is SP+248. The five-section
filter descriptor is `0x11818030`; its setup call at `0x118108f4` selects
original template `0x11817d88`. The model supplies that initialized descriptor
and does not execute the setup or prove that runtime coefficients remain unchanged.

Each filter result is clipped to ±`0.9999899864196777`, multiplied by
`2126008832.0` with float32 rounding, and truncated toward zero to a signed
integer. The loop stores the word at context `384 + 8*i`, then copies it to
`388 + 8*i`. Thus it produces four identical adjacent word pairs in context
384–415. This reaches the context region independently mapped to TX serializer 4;
it does not resolve physical FIFO phase or the CPU's retained frame alignment.

`dsp-output-publication-trial` passes 128 cases and three 32-group stateful
sequences, including both clipping limits. It verifies filter arguments,
filter state, duplicated stores and unchanged surrounding memory against an
independent reference; incorrect load/FP latencies are rejected. The auxiliary producer and the other serializer-4 context region are qualified
below. Generation of the source scalars and mix buffer, preceding mode/control
processing, DMA ownership and physical gain calibration remain separate
qualifications.


## Auxiliary input and the second serializer-4 context region

The contiguous original body `0x11810aa4..0x11810c70`, including calls to the
original filter at `0x118007cc`, now qualifies the auxiliary buffer producer and
publication into context 416–447. The model supplies initialized descriptors
from original cinit templates, two floating-point context scalars, and two groups
of signed context words. It executes twelve original filter calls per group;
no filter result is stubbed. Original allocation/setup and the producers of those
supplied context values are outside the boundary.

The first two filters each receive one scaled scalar followed by three zeros:

| Context input | Initial multiplier, rounded float32 | Descriptor / template | Filter sections | Destination |
| --- | --- | --- | ---: | --- |
| +576 | `42.375999450683594` | `0x11818008` / `0x11817d58` | 4 | Four floats at SP+88..100 |
| +628 | `93.19309997558594` | `0x11817fe0` / `0x11817d88` | 5 | Four floats at SP+104..116 |

The corresponding template gains are `0.0005997947882860899` and
`0.00004217493915348314`. Each zero input still advances its filter state; these
are not four independent copies of the scalar. The descriptor/template associations
are statically bound to the original setup call sites by
`dsp-auxiliary-bindings-audit`. That audit does not execute setup or prove runtime
coefficient immutability.

SP+88..100 supplies the auxiliary term of the previously qualified publication
loop, which adds main and mix contributions before another five-section filter
and conversion into context 384–415. SP+104..116 follows a different path:
`0x11810c24..0x11810c68` clips each value to ±`0.9999899864196777`, writes a
clipped value back to its scratch slot when needed, multiplies by float32
`2126008832.0`, truncates toward zero, and writes an identical pair at
context `416+8*i` and `420+8*i`. This region is the other eight-word region for
serializer 4 in the routing map. These address relationships do not identify
physical left/right slots or equate either region unconditionally with CPU A/B.

The same executed body also stages two signed-word inputs for later processing.
For `i=0..3`, it converts context word `64+8*i` to float32, scales by `2^-31`
and `0.13790999352931976` with separate roundings, and writes SP+120+4*i.
SP+136+8*i receives the float32 sum of that result with itself; the following
word is zero. Context word `96+8*i` is converted and scaled by `2^-31`, passed
through descriptor `0x11817f68` using template `0x11817d88`, multiplied by
`1.472499966621399`, and stored at SP+168+4*i. Their later routing/mixing and
physical source identity remain separate work.

`dsp-auxiliary-output-trial` passes 196 fixtures with both interrupt-enable
states, positive/negative/zero scalars, zero/nonzero filter state and signed-word
extremes. Both conversion clipping limits are reached. Three 32-group sequences
check stateful impulse, step and alternating inputs. Filter arguments, state,
all scratch outputs, duplicated context stores and unchanged surrounding memory
match an independent arithmetic reference. Incorrect load and floating-point
latencies are rejected.

`dsp-auxiliary-publication-linked-trial` connects actual outputs from the original
receive interpolation, auxiliary producer and publication models across 384
groups. Separate arithmetic/state references check the combined outputs. The
fixtures include main-only, auxiliary-only, second-region-only and combined
inputs, plus clipping. With main and mix zero, a nonzero +576 input can reach
context 384–415; a +628-only fixture reaches 416–447 while 384–415 stays zero.
Mix is supplied zero and the signed-word banks are zero in these linked cases.
Intervening caller instructions and source generation are not executed, so this
is a connected-slice qualification, not a whole audio-task simulation.

The source scalars must not be treated as invariant zeros or independent taps.
Static bindings show that the later call to `0x1180a2e4` receives the same context
pointer and contains stores clearing offsets 576 and 628, followed by further
processing. Its complete contribution and other producers remain unqualified.
This finding preserves the need to trace shared state before claiming global
AF independence or an all-mode gain contract.

## AF-controlled output and the native publication boundary

Static tracing identifies a separate AF-controlled output loop at
`0x11811520..0x118117c0`. It reads the low byte of command word `0x11817b54`,
compares it with the cached byte at B14+456, and updates the target gain at
B14+464 when it changes. The smoothed gain at B14+460 multiplies the filtered
sample at `0x11811708`, before further scaling, limiting and integer conversion.
This is an instruction-level trace, not execution of the complete AF loop or
qualification of its numerical gain law.

The loop initializes its destination to context+352 and its count to eight.
The store at `0x118117b4` advances by four bytes per iteration, covering context
352–383. Under the separately qualified routing layout, these are the second
half's eight words for TX serializer 2. They do not overlap the native
serializer-4 publication at context 384–415 described above. Thus the direct
AF-controlled stores identified here target a different serializer lane.

This does not establish global AF independence. Immediately afterward,
`0x118117e4` calls `0x1180a2e4` with the context pointer in A4 and a scaled
post-AF value in B4. That helper's complete effects and other possible shared
state dependencies remain unqualified. The target observation that AF minimum
left native stream A present in the tested USB-D capture is consistent with
separate direct output lanes, but neither observation proves independence for
every mode, transition or control setting.

### AF-derived peak and shared status publication

Within `0x1180a2e4`, the incoming AF-processed value is retained in B10.
The nonzero-counter path at `0x1180ab64..0x1180abb4` and
`0x1180acb8..0x1180acd4` accumulates
`abs(float32(float32(0.3) * B10))` into the maximum at B14+1412. A companion
peak at B14+1408 accumulates the absolute value supplied at SP+40. The counter
at B14+1420 decrements once. The private `dsp-af-peak-trial` executes these
original instructions in 567 finite-input fixtures, including both signs,
zero, peak replacement/retention and counters 1, 2 and 96. It checks complete
memory against an independent reference; the counter-zero path is excluded.

A separate original slice, `0x1180ac6c..0x1180acac`, compares the saved
AF-derived peak at B14+1412 against the threshold at B14+1380. If the peak is
strictly greater, it sets bit 4 of the byte at `0x11817ba8`; a nonzero byte at
B14+1389 additionally clears bit 5. Otherwise it clears bit 4 and preserves
the other supplied status bits. `dsp-af-status-trial` executes 6,912 fixtures
covering all 256 status bytes, threshold equality and both gate states,
including signed-byte value 255. Complete memory is checked, and both trials
reject an incorrect load latency.

These are separate slices with supplied state, not uninterrupted execution of
the helper. The static intervening path evaluates the accumulated state when
the counter is zero, reloads the counter to 96, then clears both peaks. Its
complete execution and cadence remain unqualified. The evidence establishes
an AF-derived shared-status dependency, so separate direct output lanes are
insufficient to prove independence. Consumers of this status, indirect callbacks,
and any resulting effect on native samples still require qualification; no UI
function or transmit-control meaning is assigned to the status bits here.

### Status-change staging and the separate control-data DMA path

One consumer of the status containing the AF-derived bit is interrupt handler
`0x11811e78`. Its static setup loads the first eight bytes at `0x11817ba8` and
the previous snapshot at `0x11818588`. On the non-receive branch, the comparison
at `0x11811f94` gives any difference in those eight bytes priority over the
later status checks. The changed path at `0x11812082` reloads the first word
from `0x11817ba8`, stores it at B14+1572 (`0x1183213c`), and copies the loaded
eight-byte snapshot into `0x11818588`. An unchanged snapshot proceeds to the
next comparison at `0x11811fa2`.

The private `dsp-status-stage-trial` executes these comparison and changed-path
instructions in 520 fixtures. Every single-bit difference in the 64-bit
snapshot, equal snapshots and two memory poisons are covered. Exact memory
checks establish the staged word and snapshot update; incorrect load latency
is rejected. The register snapshots and pointers are supplied. Interrupt
entry/MMIO, later priority branches and concurrent updates are not executed.
In particular, updating the snapshot here does not prove delivery to the CPU,
and changes can be coalesced before this path observes them.

Static caller `0x11814770..0x11814788` supplies this staging address to original
constructor `0x11814ae8`, with destination loaded from B14+1548. The original
initialized value is `0x01d06000`, McASP1's data port (SPRS377F, pages 22 and
123). `dsp-status-param-trial` executes that constructor and its original
PaRAM-writing helper in eight fixtures, including relocated arguments and two
memory poisons. For the actual caller arguments, both PaRAM indexes 3 and 36
contain these eight words:

```
OPT       SRC         A_B_CNT   DST         BIDX  LINK_BCNTRLD  CIDX  CCNT
00106000  1183213c    00010004  01d06000    0     00010480      0     1
```

This describes a four-byte, single-array transfer with zero address strides,
link to PaRAM 36 and TCC 6. Both descriptors use the same staging word; the
PaRAM-36 link points back to itself. It is a separate control-data path from
the native McASP0 audio banks. Descriptor construction does not establish
event enablement, successful bus transfers, wire timing, CPU interpretation or
alignment with a particular native sample. The reporting consumer therefore
narrows the shared-status investigation without proving that other consumers
cannot affect receive processing.

## DSP completion dispatch and ordering

The original service prefix `0x11812680..0x118126d8` reads the EDMA3 global
interrupt-pending register at `0x01c01068`. The base `0x01c00000` is present
in the parsed cinit data. Completion bits 1 and 2 gate the routing call:

| Pending bits 2:1 | Routing action |
| --- | --- |
| 00 | Skip this routing call |
| 01 | Select bank 0 |
| 10 | Select bank 1 |
| 11 | Select bank 1 once |

On the selected path, `0x11812324..0x11812340` writes `0x66` to
`0x01c01070` before entering the routing slice. TI SPRUH91D pages 508,
538–539 identify these registers as IPR and ICR and specify that writing a
one to ICR clears the corresponding pending bit. Thus the write acknowledges
bits 1, 2, 5 and 6, rather than acknowledging only the selected bank's bit.
The restricted `dsp-dma-dispatch-trial` passes all 256 low-byte pending-status
values with a stable supplied snapshot. It records the actual clear write;
concurrent completions and peripheral side effects are not simulated.

Within the routing routine, the already-qualified context-to-output-bank copy
precedes the processing call at `0x118125e4` to `0x118104c0`. The output copy
therefore uses the context contents from before that processing call, while
newly extracted receive input is available to the call. The arithmetic output
produced during the call is not the data already copied by that invocation.
This ordering must be included in any end-to-end latency model; no physical
latency is assigned here.

The simultaneous-bit case is a concrete qualification limit: this dispatch
prefix does not separately process both pending banks. It neither proves that
an overrun occurs on target nor excludes detection elsewhere. Safe ownership
and continuity still require the transfer-completion configuration, service
latency, concurrent DMA behavior and discontinuity evidence; a bank index alone
is insufficient proof of those properties.

## DMA descriptors and completion meaning

The original TX PaRAM constructor at `0x118147d0`, including helper
`0x11814c44`, passes 24 fixtures covering both address placements, poisoned
initial memory and each null pointer guard. It writes three complete PaRAM
sets, preserves the caller's stack/A10, and leaves other parameter memory
unchanged. The RX constructor has the corresponding independently checked
24-fixture result.

| Direction | Initial / linked PaRAM indices | Bank 0 / bank 1 completion codes | Bank addresses |
| --- | --- | --- | --- |
| RX | 0 / 34, 35 | 1 / 2 | `0x1181e550`, `0x1181e610` |
| TX | 1 / 32, 33 | 3 / 4 | `0x1181e6d0`, `0x1181e7d0` |

TX sets use ACNT=16, BCNT=2, CCNT=8, source BIDX=128 and CIDX=-112,
with destination `0x01d02000` and zero destination indices. The initial TX set
and linked set 32 describe bank 0 and link to set 33; set 33 describes bank 1
and links back to set 32. The link field's reload count is two. This is a
256-byte bank layout, separate from the 192-byte RX banks.

The generated option words are `0x00101000`/`0x00102000` for RX and
`0x00103000`/`0x00104000` for TX. All set final-completion interrupt enable,
clear intermediate-completion interrupt enable and chaining enables, and have
TCCMODE=0. TI SPRUH91D pages 461 and 501–502 define that as normal completion:
the completion follows the data transfer, rather than merely submission of a
transfer request. The sets use A synchronization and increment address modes;
zero peripheral indices produce repeated access to the transfer port.

This narrows the ownership boundary but does not close it. The dispatch gate
above observes RX completion codes 1/2, while TX completion uses 3/4. Its
`0x66` clear mask does not clear TX completion bits 3/4, and the qualified
prefix does not check them before entering the copy routine. RX completion
alone therefore cannot prove that the selected TX bank is available for writes.
The relationship between the two DMA streams, the deadline before bank reuse,
cache behavior and any checks outside this prefix remain required evidence.

Private `dsp-tx-param-trial` and `dsp-param-completion-audit` retain the original
constructor results and decoded option fields. These are constructor and manual
semantics checks, not measured peripheral execution or runtime PaRAM ownership.

## Service-loop scheduling boundary

Static call tracing distinguishes initialization from repeated servicing. Entry
`0x118160b0` calls initialization at `0x11813560`, then enters service routine
`0x11812668`. The initialization contains context clearing, peripheral setup and
the descriptor-construction call. Within the service routine, five backward
branches return directly to the pending-register poll at `0x11812680`; they do
not return through that initialization call.

Between polls, three indirect call sites (`0x11812816`, `0x1181284e`,
`0x11812922`) dispatch command words through table `0x11818100`. Their byte
offset calculation `(command >> 22) & ~3` selects the high-byte command index
multiplied by four. The full set of handlers and their worst-case durations are
not qualified here. Consequently, instruction counts for the buffer-copy slice
cannot be used as an upper bound on the interval between completion polls.

A separate helper at `0x11815128` forms `1 << requested_code`, polls IPR until
that bit is set, then calls `0x11814fd8` to acknowledge the requested bit.
There is no direct call to this helper or the standalone IPR reader
`0x11815008` in the inspected service loop. That bounded static observation
does not exclude indirect calls, other synchronization or runtime resets.
In particular, the existence of the wait helper is not evidence that this
receive-driven copy path waits for TX completion.

`dsp-service-order-audit` pins the reviewed instruction bytes, startup calls,
five poll backedges and three indirect dispatch sites, and checks 768 command
index examples. It is a static audit, not a full-service execution or a timing
measurement. A bounded adapter still needs explicit service-latency and buffer
reuse evidence, including the effect of command work and asynchronous activity.

## DSP buffer memory and coherency scope

The C6745 memory map identifies `0x11800000..0x1183ffff` as the 256 KiB L2
RAM window (SPRS377F, page 25). Both RX banks, both TX banks and the 736-byte
processing context are disjoint and fit entirely within its lower 128 KiB.
`dsp-buffer-memory-audit` checks these address bounds; it does not classify any
unmapped space as available storage.

For CPU data accesses and DMA transfers through L2 SRAM, TI describes hardware
snoop writes that update cached input data and snoop reads that forward dirty
output data to DMA. These rules differ from external-memory coherency rules.
See [SPRUG82A, sections 2.4.1–2.4.2 and Appendix A](https://www.ti.com/lit/ug/sprug82a/sprug82a.pdf).
The guide also distinguishes memory assigned to SRAM from memory assigned to
cache. Address placement alone does not establish the active partition; the
runtime L2CFG value at `0x01840000` remains unmeasured.

The recovered bank boundaries are not 64-byte aligned. Manual cache operations
must not be added on the assumption that a whole line belongs to one bank.
Hardware coherency, where its documented conditions apply, still does not
establish exclusive ownership, an atomic whole-bank snapshot, correct frame
phase, or completion before reuse. Those remain separate acceptance properties.
The private audit records manual hashes and labels its result as geometry and
manual semantics, not hardware execution.

## Boot callbacks and cache-configuration boundary

The AIS entry at `0x118177a0` establishes an aligned stack at `0x1182f2f0`
and B14 at `0x11831b18`, then invokes `0x11816f60` with the cinit table at
`0x1182f2f8`. That initialization routine also walks the null-terminated
callback table at `0x11832390` before the main trampoline at `0x118179a0`
transfers control to `0x118160b0`.

The table contains ten callbacks. The private `dsp-boot-callback-trial`
interprets their original instructions in table order, including the nonnull
object constructor at `0x118003f0` and list-registration helper at
`0x11817960`. Two BSS/stack poison fixtures give 20 callback executions.
Every non-stack write is compared with an independently enumerated destination,
size and value; untouched memory, stack restoration and saved registers are
checked. Original loaded/cinit bytes supply initialized globals. Explicitly
identified object destinations supply otherwise-unloaded BSS storage; this does
not establish ownership of arbitrary unused memory. The allocation path is
unmapped and would fail the model if reached.

These callbacks initialize filter descriptors and other audio state, and register
two list nodes. Their checked writes remain in DSP RAM and the synthetic stack;
none writes the cache-control register window. The separate boot-data audit
also finds no direct cinit destination in `0x01840000..0x0184ffff`.
This narrows the cache investigation but does not establish the active L2
partition: the AIS ROM function, later initialization and runtime paths remain
outside this callback check. No physical boot, cache behavior or timing is
simulated.

## DSP interrupt routing and the separate McASP1 boundary

Main initialization calls `0x118136ec`, which writes `0x3d060504` to INTMUX1
at `0x01800104`, selects vector base `0x11832400`, writes `0xfff0` to the
CPU interrupt-clear register, and ORs `0x82` into IER. The restricted
`dsp-interrupt-setup-trial` checks these original instructions for 34 initial
IER values and two memory poisons (68 cases). All unrelated IER bits survive;
this is not an assignment that disables other previously enabled interrupts.
The model records control-register and passive MMIO writes without simulating
interrupt delivery or peripheral side effects.

INTMUX1 maps events 4, 5, 6 and 61 to CPU interrupts 4, 5, 6 and 7 respectively.
TI identifies event 61 as the combined McASP0/1/2 RX/TX interrupt, rather than
an EDMA bank-completion event (SPRS377F, pages 76 and 78; SPRUFK5A, page 178).
Exact original vector bytes at `0x118324e0` identify interrupt 7's target as
`0x11811e78`.

The handler's initial peripheral base comes from `0x11832100` and is
`0x01d04000`: McASP1. Its status read is at `0x01d04080` (RSTAT), and the
conditional data path at `0x11812090` reads `0x01d04288` (RBUF2), per the
register map in SPRS377F pages 120 and 122. These addresses and instruction
bytes are statically pinned; the handler itself is not executed by this setup
model. The combined interrupt identity therefore must not be mistaken for
proof that this handler recovers McASP0 native-audio DMA overruns. Its work is
also a separate possible contributor to service latency. Actual interrupt
frequency, execution time, complete handler effects and recovery behavior remain
unqualified. This initialization check does not establish the cache partition.

## McASP1 command enqueue and continuity limits

Original cinit data initializes the object at `0x11819300` with a buffer
pointer of `0x11818f00`, capacity 256 words, and zero producer/consumer
counts and indexes. In the generic interrupt enqueue body
`0x118120e4..0x11812190`, the fields are:

| Offset | Enqueue use |
| --- | --- |
| `+0` | Word-buffer pointer |
| `+4` | Capacity in words |
| `+8`, `+12` | Producer and consumer counters |
| `+16`, `+20` | Producer and consumer indexes |
| `+24`, `+25` | Space/nonempty flags computed from pre-increment counters |

The restricted `dsp-command-push-trial` executes this original body in 504
fixtures, including the cinit capacity, index wrap, full/overfull occupancy and
signed counter boundaries. It compares every memory byte with a separate
reference. The body writes the supplied command at the producer index,
increments the producer counter, advances the index modulo capacity, and writes
`0xdeaddead` into the following slot. Neither a full count nor the space flag
suppresses these writes in this slice. Thus existing slots can be overwritten
when service falls behind; the following-slot sentinel also needs to be included
in any capacity argument. No target overflow is claimed.

The flag comparisons use signed 32-bit values. Both flags describe the counters
before this insertion, and the consumer recomputes queue state in its own path;
they must not be treated as a post-insertion continuity guarantee. The static
service trace at `0x11812864` reads this same object, advances its consumer
counter/index, and selects a command handler or a pending-command field.

This is the generic enqueue body only: earlier special command handling, the
consumer's complete execution, interrupt interleavings, subsequent object
reconfiguration and backpressure elsewhere are not modeled. It identifies a
concrete command-loss boundary relevant to gain/control history; it does not
prove that a control transition occurred on the target or that the complete
firmware has no recovery mechanism. Audio continuity and command continuity
remain separate properties to qualify.

## Command consumer: immediate and deferred application

The original selected-consumer body `0x11812864..0x1181293c` advances the
consumer counter/index before deciding how to apply the fetched word. The
restricted `dsp-command-pop-trial` checks all 256 command high bytes at both
ends of the 256-word ring and three counter positions, including signed and
unsigned rollover (1,536 cases). Every memory byte is compared with a separate
reference. The original initialized handler table supplies indirect targets;
execution stops at the handler entry rather than inventing a successful return.

| Command high byte | Consumer action |
| --- | --- |
| `0x20`, `0x21` | Store the complete word at `B14+620`, then return to the DMA poll |
| `0x25` | Store the complete word at `B14+628`, then return to the DMA poll |
| All others | Pass the word in A4 and dispatch through `0x11818100 + 4*high_byte` |

The two commands sharing `B14+620` can replace one another before deferred
application. Consuming a queue entry therefore does not by itself prove that
its handler ran. The earlier service branch reaches the deferred-application
path when its queue-state check finds no pending entry: it compares `+620`
with the last-applied word at `+624`, and separately compares `+628` with
`+632`. These later calls remain a static trace, not part of the consumer-body
execution test. No application-time or latency bound follows from this result.

Fixtures supply the register snapshot at the selected-consumer boundary. They
do not execute the preceding nonempty gate or establish that every supplied
counter-wrap state is reachable in the complete service loop. Interrupt
interleavings, whole-loop backpressure and command-handler effects remain
separate qualifications. An audio diagnostic must not infer a complete control
history merely from queue consumption or a nominal audio sample cadence.

## Deferred handler state and downstream update boundaries

The original handlers for command types `0x20`, `0x21` and `0x25` each copy
the old command to a history word and store the new command before comparing
for equality. Identical words return without the downstream update. Changed
words reach these boundaries:

| Type | Current / previous command | Downstream entry and arguments |
| --- | --- | --- |
| `0x20` | `0x11817b30` / `0x11818510` | `0x11808bb0`: A4 is 1 when the old word is `0xffffffff` or bit 22/23 changed, otherwise 0 |
| `0x21` | `0x11817b34` / `0x11818514` | `0x11807ea0`: A4 is 1 when any bit in mask `0x63f` changed; B4 is new bit 10 |
| `0x25` | `0x11817b44` / `0x11818524` | `0x11806004`: A4 retains the complete new command |

The private `dsp-deferred-handler-trial` executes 630 original-wrapper fixtures:
six payload patterns per type, equal words, the `0xffffffff` invalidation value,
and every individual bit difference. It verifies the ordered current/history
writes, unchanged returns, stack state and changed-path call arguments. Changed
paths stop at the actual downstream entry; no helper return or successful
coefficient update is synthesized.

Consequently, reading a current-command word proves that this wrapper stored it,
but does not prove that the downstream update completed, that filter state is
settled, or that the corresponding behavior has reached the audio wire. The
bit masks above describe original software decisions; physical UI-control and
calibrated-gain meanings require the CPU packing and downstream processing
chains. The first two paths also have later static stores invalidating the other
current-command word after their helper returns; those stores are outside the
changed-path execution check described here.

## CPU packing for deferred command types 0x20 and 0x21

The original CPU slice `0x200b1d14..0x200b1e04` constructs these words in
command-array slot `+8`. The private `band-command-trial` executes 1,372
fixtures together with the original Thumb unsigned and signed division routines
at `0x2017c618` and `0x2017c644`. No division result is stubbed. Input records
and adjacent output words remain unchanged; each fixture writes exactly one
command word outside its private stack.

For type `0x20`, let L and U be the signed halfwords at selected-record offsets
`+0x24` and `+0x26`. The encoded fields are:

- Bits 17:9: `trunc((max(L, -8000) + 8000) / 25) & 511`.
- Bits 8:0: `trunc(min(U, 8000) / 25) & 511`.
- Bits 23 and 22: the supplied normalized flag and selection flag respectively.

The clamps are one-sided in this slice. Values outside the ordinary field range
can therefore wrap through the final bit-field masks; these fixtures are not a
claim that the UI permits such settings.

For type `0x21`, let W be the unsigned halfword at `+0x28` and S the signed
halfword at `+0x2a`. Bits 23:11 contain `trunc(S / 5) & 8191`. When supplied
path bit 1 is set, bits 5:0 contain `(W / 50) & 63`, and bits 10/9 carry the
flag/selection values. Otherwise, supplied path bit 2 selects
`(trunc((W - 500) / 500) + 10) & 63` for bits 5:0, leaving bits 10/9 zero.
The bit-1 path takes precedence when both are supplied. Signed division
truncates toward zero, including negative boundary fixtures.

These fields connect directly to the deferred-handler decisions above: type
`0x20`'s two flags drive its bit-22/23 update argument; type `0x21`'s low six
bits and two flags drive mask `0x63f`. The latter low-six-bit selector also
feeds the previously mapped ordinary-filter table selection. This establishes
field-level software relationships, not calibrated gain or physical UI units.
Earlier record selection, command delivery, downstream coefficient updates and
target behavior remain outside this CPU packing test.

## Selected-record and mode provenance for filter commands

The command packer's original entry selects R5 as
`0x203def00 + 0x30c + 56 * byte[0x20390730]`. The associated raw mode comes
from `0x204159c0 + 16*index + 8`. For supplied raw modes 0–7, original helper
`0x200130a0` produces `[0, 0, 1, 1, 2, 2, 3, 4]`. Table `0x20335f60` then
selects descriptor indexes `[0, 2, 4, 6, 7]`. A nonzero record byte at `+0x1e`
advances the descriptor index by one only for the first three normalized modes.
The three-byte descriptors reside at `0x20335f6d`.

| Raw mode | Record `+0x1e` zero | Record `+0x1e` nonzero |
| --- | --- | --- |
| 0–5 | Type `0x20`, signed endpoint fields | Type `0x21`, W/50 path |
| 6 | Type `0x20` | Type `0x20` |
| 7 | Type `0x21`, `(W-500)/500 + 10` path | Same path |

The flag passed into the packing formulas comes from record byte `+0x2e`:
0 and 1 survive, while values greater than 1 become zero. The selection flag
is equality between the descriptor's first byte and the raw mode. In these
fixtures it is one for modes 0, 2 and 4, and zero for modes 1, 3, 5, 6 and 7.
The cached gate at `0x203906ca` clears descriptor flag bits 4–6 when zero;
it does not change the format-selecting low three bits.

The private `band-selection-trial` passes 384 original-code fixtures spanning
modes 0–7, record indexes 0/1, selector zero/nonzero values, flag normalization
and the cached gate. Selection, descriptor and packing slices connect through
checked register values, and execute the original mode/division helpers. The
intervening unrelated packing is omitted, with the output-array pointer supplied
at its known boundary; this is not uninterrupted execution of the whole packer.
Selected records remain unchanged and only the expected output word is written
outside private stack storage. Numeric mode identities and field provenance
are established here; UI labels, field setters/units and actual signal response
remain separate evidence requirements.

## Endpoint geometry and publication into the selected record

Original helper `0x20027aa8` derives the fields used above. It reads an unsigned
step byte at `0x203deec8+4` and signed bias byte at `+6`. With supplied offset
arguments P and Q, width B and center C, its arithmetic is:

```text
D1 = (P + bias) * step
D2 = (Q + bias) * step
L  = C + max(D1, D2) - floor(B / 2)
U  = C + min(D1, D2) + floor(B / 2)
W  = U - L
S  = trunc((L + U) / 2)
```

It also calculates `trunc((D1 + D2) / 2)`. Results are stored as halfwords in
the working structure beginning at `0x203deec8+0x0c`. The caller's static tail
copies 16 bytes to `+0x1c`; original publication slice
`0x200529cc..0x20052a10` copies these fields into the selected 56-byte record:
D1/D2 at `+0x20/+0x22`, L/U at `+0x24/+0x26`, W/S at `+0x28/+0x2a`, and
the mean displacement at `+0x2c`. The selector byte maps to record `+0x1e`.

The private `filter-geometry-trial` executes the original arithmetic, original
ARM-to-Thumb copy routine and publication slice sequentially in 972 fixtures.
It checks complete source/destination memory against an independent reference,
including negative offsets, odd widths and crossed endpoints. Odd B loses one
unit through the two half-width truncations. The helper does not clamp crossed
endpoints in these fixtures, and its stores retain the low 16 bits. This does
not establish that the UI admits every supplied combination.

This connects the packed endpoint/width/center fields to their generating
arithmetic. The full callers, sources of B/C/P/Q, physical units, permitted UI
ranges, update atomicity and actual filter response are not inferred from the
isolated chain. In particular, the structure publication is distinct from both
command dispatch and downstream DSP update completion.

## Scope of the evidence

Private exact-image models and reports include `dsp-rx-param-trial`,
`dsp-rx-lane-model`, `dsp-rx-format-audit`, `dsp-routing-source-trial`,
`dsp-source-conversion-trial`, `dsp-input-ramp-trial`,
`dsp-input-ramp-gate-trial`, and `dsp-mute-command-bridge-trial`.
Transition evidence is retained in `input-mute-request-trial`,
`input-mute-release-trial`, `input-mute-counter-trial`, and
`input-mute-cadence-trial`.
Ordinary-path evidence is retained in `dsp-ordinary-sample-layout-trial` and
`dsp-ordinary-filter-wrapper-trial`, with original table data qualified by
`dsp-ordinary-table-filter-trial`.
The following zero-output branch is covered by `dsp-ordinary-zero-output-trial`
and `dsp-envelope-table-trial`.
The history branch is covered by `dsp-ordinary-history-trial`.
Its energy-feedback prefix is covered by `dsp-feedback-energy-trial`.
Threshold and release-table evidence is retained in `dsp-feedback-threshold-trial`
and `dsp-feedback-release-table-trial`.
The remaining caller is covered by `dsp-feedback-floor-trial`; the reciprocal
instruction limit is recorded in `dsp-log-reciprocal-bound-audit.json`.
They retain firmware hashes and explicit boundaries. Firmware, decoded code,
manual crops and generated original-image reports remain private.

These findings narrow the source and control path; they do not complete the
[native receive plan](../docs/NATIVE_RECEIVE_PLAN.md). The complete downstream
processing path, active mode/gain semantics, physical phase, runtime storage
ownership, stack/timing margins and v2 target lifecycle capture remain required.
The [target capture](native-receive-target-capture.md) independently establishes
the tested CPU stream's relationship to recorder audio; it does not prove all
of the DSP source-side assumptions above.

## Compact-register decoding caveat at the remaining mix selector

A byte-level audit found a GNU binutils 2.44 operand-decoding discrepancy in
three compact formats when the fetch header selects the high register set.
TI SPRUFE8B section 3.10.2.2 (page 93) applies that selection to three-bit data
register fields. Figure D-9 (page 738) explicitly restricts the one-bit `Lx3c`
comparison destination to A0/A1 or B0/B1. Figures G-1/G-2 (page 759) encode one
side of compact `MV` with a full five-bit register number. Applying an extra
16 to those destinations or full-width operands changes the instruction.

At `0x11810f68`, opcode `0x004f` under header `0xe0880010` therefore moves
B16 to **B0**, rather than B16 to B16. The parallel `0x2827` at `0x11810f6a`
compares B16 with 1 and writes **B1**, rather than B17. These two results
explain the following conditional branches: an incoming B16 of zero selects
`0x1181116c`; one selects `0x11811024`; other values fall through to
`0x11810f74`. This is local selector decoding, not execution of the preceding
producer, the selected processing bodies, or proof of the reachable counter
values. The numerical and stateful checks of these bodies are documented below.

The private audit preserves the original disassembly and reports 60 differing
operand decodes in the linear listing for these three formats. That listing
may include data, so this is not a count of executed instructions. None falls
within the selected filter, main interpolation, auxiliary producer, native
publication, common-output/wrapper, or input-mixer ranges used by the recent
bounded models. This only clears those ranges of these three discrepancies;
it does not validate all decoder formats, earlier source-map models, or their
complete callers. New interpretation must check compact register fields
against the manual rather than treating the raw listing as authoritative.

## Mix staging and its native-publication gate

With the two compact operands corrected as above, a restricted model now runs
`0x11810f68..0x11811250` and the original filter at `0x118007cc`. Let `s` be
B16 at entry and let `j` select a word within each two-word scalar pair:

| Entry selector | Four scalar indices `j` | Stored next selector |
| --- | --- | --- |
| `s = 0` | `0, 0, 0, 0` | `1` |
| `s = 1` | `0, 0, 1, 1` | `2` |
| Other values | `1, 1, 1, 1` | `s - 2`, modulo 32 bits |

The body stores that next value at B14+404. Reachability and the preceding
scalar producer are not established by supplying these entry values.
For each of four iterations, it performs these separate operations:

- Add scalar `0x11818058 + 4*j` to stack input `SP+120+4*i`, using float32
  arithmetic. Filter through descriptor `0x11817ea0` and duplicate the result
  into `SP+184+8*i` and the next word. Its initialization template is
  `0x11817d88`, with five sections and gain `4.217493915348314e-5`.
- Add scalar `0x11818060 + 4*j` to each of the two words at `SP+136+8*i`.
  Filter those two sums consecutively through descriptor `0x11817ec8` and
  store them at `SP+216+8*i` and the next word. Its initialization template is
  `0x11817d94`, with five sections and gain `1.5692590750404634e-5`.
- Copy scalar `0x11818068 + 4*j` directly to `SP+248+4*i`. This third path
  supplies the mix input of the native publication formula documented above.

After all twelve filter calls, command word `0x11817b20` bit 23 determines
whether the four mix slots are retained or zeroed. Both neighboring filters
have already advanced their states regardless of this bit. The gate does not
remove the main or auxiliary contributions to native publication, and it does
not clear the publication filter's history. It is therefore not evidence of
an instantaneous stream mute or a physical RX/TX/PTT control.

Validation covers 320 supplied-input cases, including both interrupt states,
zero/nonzero filter history, all three selector branches and unrelated command
bits; three 48-group sequences check carried state. Independent arithmetic
references check all filter inputs, outputs, states, mix slots and counter
updates. Memory guards and callee preservation pass, and deliberately wrong
load/FP latencies are rejected. Sixteen static byte bindings connect the
supplied descriptor templates and zero registers to original initialization.

Another 288 connected groups pass actual auxiliary staging through this mix
model and then actual mix slots through original native publication. They
exercise mix enabled/disabled/toggled and main/auxiliary contributions while
the mix gate is off. The toggled case retains a nonzero filter tail after the
mix slots are cleared. These are connected bounded slices: six global scalar
values and main staging remain supplied, and the preceding producer and full
caller are not executed. Physical source identity, calibrated gain, buffer
ownership and hardware acceptance remain open.
