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

## Scope of the evidence

Private exact-image models and reports include `dsp-rx-param-trial`,
`dsp-rx-lane-model`, `dsp-rx-format-audit`, `dsp-routing-source-trial`,
`dsp-source-conversion-trial`, `dsp-input-ramp-trial`,
`dsp-input-ramp-gate-trial`, and `dsp-mute-command-bridge-trial`.
They retain firmware hashes and explicit boundaries. Firmware, decoded code,
manual crops and generated original-image reports remain private.

These findings narrow the source and control path; they do not complete the
[native receive plan](../docs/NATIVE_RECEIVE_PLAN.md). The complete downstream
processing path, active mode/gain semantics, physical phase, runtime storage
ownership, stack/timing margins and v2 target lifecycle capture remain required.
The [target capture](native-receive-target-capture.md) independently establishes
the tested CPU stream's relationship to recorder audio; it does not prove all
of the DSP source-side assumptions above.
