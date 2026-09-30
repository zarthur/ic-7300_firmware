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
independent reference; incorrect load/FP latencies are rejected. Preceding
mode/control processing, the two additional buffer producers, DMA ownership,
and physical gain calibration remain separate qualifications.

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
