# DSP to SSIF0 lane and gain crosswalk

This note joins existing exact-image DSP and CPU source maps to the validated
v2 target capture. It narrows the lane question but does **not** identify a DSP
serializer slot as CPU stream A or B, and does not claim a calibrated gain path.

## Pinned evidence

The DSP image and CPU application reports were generated from clean commit
`119617ddb60bea1ce0f642ef111a68302b6228c6` and agree on original container
SHA-256 `8cf5324a126f105cd2307c30b191b9dd8183f86b2c8bf229e61bf9a6a8c32f32`.
The decoded DSP program is SHA-256
`3093818ec5716abb00c16dd686a980c00812c88e73d0753b3c19e9f1d15429a1`; the CPU
application is `4686728c9d1f7249b6278a29686a40b8fa5e527bd2428a76a33cd9395178c9a4`.
The v2 report is schema 3 for WAV SHA-256
`a3f071d17b67d3ee0bd2063f75a109e0c875c7222dd86f029789cfc2ce4c5783` and
recovered capture SHA-256
`41564ca5b439e37045a3f370bc2e4fcd87124a7ee6bef81fc22a1bd273c3e37f`.

The reproducible bridge command checks these report identities and capture
invariants, then writes a source-offset crosswalk. It does not disassemble or
execute DSP instructions:

```sh
artifacts/toolchains/python311/venv/bin/python tools/native_receive_lane_bridge.py \
  --dsp-report artifacts/current-epic-synthetic-py311-passed/dsp-image-report.json \
  --controls-report artifacts/current-epic-synthetic-py311-passed/native-dsp-controls-report.json \
  --capture-report artifacts/native-capture-v2-20261001/report-v2-schema3.json \
  --output artifacts/current-epic-synthetic-py311-passed/native-receive-lane-bridge-report-final.json
artifacts/toolchains/python311/venv/bin/python -m unittest discover \
  -s tests -p 'test_native_receive_lane_bridge.py' -v
```

The tests reject mixed firmware identities, altered A/B summaries, and an
incorrect matched-record endpoint. The capture parser's existing focused tests
cover raw SSI summaries and distinguish the 0–503 matched region from the
0–511 timing segment. The final full-profile aggregate is retained locally at
`artifacts/issue16-full-aggregate-20261001-final/report.json` (SHA-256
`3c722bba665c4738507b7c0125387049c1459cb02e01e863fbae465c39b67931`). It records
300 Python tests with zero skips and all aggregate steps passing. This remains
offline validation and does not supply runtime inputs or hardware observations.

## Address crosswalk

| Segment | Source locations / evidence | Bounded conclusion |
| --- | --- | --- |
| FPGA to DSP input | Service schematic PDF p.66: `DFR_MOD` to DSP pin 115. Pin 115 is `AXR0[3]`; original DSP initialization sets serializer 3 as receiver. Descriptor setup `0x11814954`, helper `0x11814c44`, extraction `0x11818bd0`, conversion output `0x11819de0`. | Under the documented active-serializer order and aligned initial FIFO phase, the first context group conditionally maps to serializer 3 slot 0. The actual phase/alignment is not measured. |
| DSP receive processing | Call chain through `0x118125e4`, `0x118104c0`, `0x118109a0` reaches `0x1180e918`; ordinary branch at `0x1180ed24`, coefficient call `0x1180c610`, replacement/bypass slice `0x1180cc44`. | Several original instruction slices are documented, but the entire caller, full coefficient calculation, and all source scalars are not connected in one execution. |
| DSP serializer-4 contexts | Receive-return interpolation `0x11810a00..0x11810aa0`; main/aux/mix publication `0x11811250..0x118112e0`; separate auxiliary path reaches context 416–447. | Context 384–415 and 416–447 each contain duplicated adjacent words and are statically associated with serializer 4. Neither region is identified as CPU A or B; FIFO phase remains unknown. |
| AF-controlled DSP path | Loop `0x11811520..0x118117c0`; command `0x11817b54`; target/smoothed state B14+464/+460; stores to context 352–383; follow-on helper `0x1180a2e4`. | The direct stores are mapped to serializer 2, separate from the serializer-4 context addresses. The common helper and other shared state prevent a global AF-independence conclusion. |
| DSP output wire to CPU | Service schematic p.66: `DX_REC` to DSP pin 116 through R924 and CPU pin 190/P2_10. Private DSP configuration places pin 116 on serializer 4. Renesas pin table maps CPU pin 190 to SSIRxD0. CPU setup `0x2005ff1c`, DMAC3 handler `0x20060614`, FIFO `0xe820b01c`. | The board connection reaches CPU SSIF0 receive DMA. The DSP frame/slot phase at that boundary has not been tied to CPU extraction offsets. |
| CPU extraction and queues | `0x20060690..0x200606d4` keeps upper 16 bits from each bank word at `16*i` and `16*i+4`, for `i=0..35`; arrays `0x203fc48a`/`0x203fc4d2`; queues `0x203fbdc0`/`0x203fc002`; recorder stage `0x20067254`. | The software positions A/B and every-sixth A recorder path are known. They must not be equated to DSP serializer slots without frame alignment. |

## Control and capture result

The CPU setter `0x200b2f60` and DSP handler `0x1180a00c` publish command
`0x11817b24`; bit 0 selects bounded input-ramp/zero branches. In the ordinary
path, `0x1180c610` writes a coefficient at B14+24, but its complete gain
calculation is not qualified. Command `0x11817b20` bit 14 controls replacement
of processed output at `0x1180cc44`; bit 10 controls the later serializer-4
output ramp at B14+400 and the `.45` scale. These controls do not yet map to a
physical radio UI setting.

The capture contains 512 records (18,432 samples in each extracted stream).
Stream A exactly matches 3,024 ordinary recorder samples at unity gain, stride
six, over capture sequences 0–503; the ordinary-audio region ends at the
diagnostic carrier. Stream B is all zero in this capture. Arthur reports the
radio was at 7.074 MHz USB-D and minimum AF volume, with other settings unknown
but unchanged, and normal operation without freezes or unexpected restarts.
Those setup and runtime statements are owner-reported. They do not establish
the DSP command values present during capture or explain stream B.

The capture's raw SSICR/SSIFCR/SSISR/SSIFSR/SSITDMR counts are retained in the
schema-3 report and bridge output. The snapshots are non-atomic and are kept as
raw words; no status-bit or DMA-phase meaning is inferred. Nominal 47,999.91 Hz
uses an assumed 32 MHz counter and 32,001-cycle period, not calibrated timing.

## Restored slice artifacts and remaining gap

The prior C674x slice bundle was found in ignored artifacts under the original
checkout and restored locally at
`artifacts/restored-dsp-lane-slices-20261001/`. Its
`restoration-manifest.json` records every copied hash and binds the decoded
program to the clean image report, section disassembly, disassembler, and GNU
Binutils source archive. The source checkout itself was dirty, so these
artifacts are retained as hash-verified local evidence, not treated as tracked
source.

The restored results show exactly where caller data stops:

- `dsp-rf-callpath` pins static edges into `0x1180e918`; it executes no DSP
  instructions.
- `dsp-output-ramp` and `dsp-output-interpolation` both take the
  `0x1180e918` return as a supplied fixture. The latter also supplies eight
  context addends.
- `dsp-output-publication` takes main, auxiliary and mix vectors as supplied
  fixtures. The routing-source trial uses synthetic receive-buffer contents
  and says the intervening caller chain is static only.

All these trial reports are `PASS`, and each report's program and script hashes
match the restored files. They were not rerun. A separate static caller map now
checks 31 exact words in the restored decoded image, including the saved/reloaded
`A4` argument, null gate, `B14+760` initialization branch, `B14+765` dispatch,
selector comparison at `0x11807b2c`, and ordinary-path pointer formation. It
records decoded-program byte offsets; it does not execute the caller or provide
the live values at those branches.

Reproduce the map and its local-bundle regression checks with:

```sh
report_dir=$(mktemp -d /tmp/native-receive-caller-map.XXXXXX)
python3 tools/native_receive_caller_map.py \
  --restored-program artifacts/restored-dsp-lane-slices-20261001/dsp_program.decoded.bin \
  --restoration-manifest artifacts/restored-dsp-lane-slices-20261001/restoration-manifest.json \
  --output "$report_dir/report.json"
python3 -m unittest discover -s tests -p 'test_native_receive_caller_map.py' -v
```

There is still no slice that produces caller values at `0x1180e918` and feeds
them into serializer-4 publication. The caller's actual `A4` pointee, the live
`B14` and selector values, and other runtime state are absent from the existing
fixtures and target capture. I stopped at verified branch predicates and source
offsets rather than inventing inputs or return values.

The v2 capture has CPU A/B samples after SSIF0 extraction but no paired DSP
context values or raw, frame-synchronized `DX_REC` words. Therefore candidate
serializer phases cannot be compared to the actual capture, even if synthetic
publication output is available. The irreducible missing facts for this path are
the live caller inputs/control state needed to produce DSP output for the
capture's receive state, and the physical serializer-to-CPU frame phase. Static
branch conditions are now qualified; current values, branch coverage and
resulting samples are not. A source-only model could address caller output only
after those live inputs are supplied, and it cannot establish the physical frame
phase.

For physical phase, the minimum useful observation is a receive-only,
high-impedance capture of `DX_REC` with its bit/word clocks and a frame reference,
then compare those decoded words with the already established CPU extraction
formula. No transmit or PTT is needed; this is a future owner-reviewed hardware
step, not performed here. For control dependence, a later owner-run comparison
could hold 7.074 MHz USB-D and other settings fixed while recording at minimum
AF and a marked mid AF setting. First review one-shot/rearm behavior offline;
repeat capture behavior is not established. A change in A supports dependence;
no change does not prove independence, and neither outcome assigns stream B's
purpose.

The software-only issue #16 slice has since advanced with the exact-image
playback queue map and host mock sequencer contract in
[native-playback-queues.md](native-playback-queues.md). It does not provide the
missing receive-side caller values or serializer phase described above. Native
worker ownership, real drain/abort/flush signals and PTT lifecycle also remain
unresolved before firmware integration.
