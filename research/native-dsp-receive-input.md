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
Processing after `0x1180d058` and association with the CPU receive lane remain
open.

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
parameter changes, the bit-5-clear processing branch, current radio selection
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
They retain firmware hashes and explicit boundaries. Firmware, decoded code,
manual crops and generated original-image reports remain private.

These findings narrow the source and control path; they do not complete the
[native receive plan](../docs/NATIVE_RECEIVE_PLAN.md). The complete downstream
processing path, active mode/gain semantics, physical phase, runtime storage
ownership, stack/timing margins and v2 target lifecycle capture remain required.
The [target capture](native-receive-target-capture.md) independently establishes
the tested CPU stream's relationship to recorder audio; it does not prove all
of the DSP source-side assumptions above.
