# DSP image and AF command investigation

The pinned original v1.42 container includes a separately compressed DSP
program. `tools/dsp_image.py` verifies the original container, decodes that
component, and reports its load and initialization layout. It performs no DSP,
bootloader, peripheral, radio or firmware-write operation. Firmware contents and
generated reports remain private artifacts.

```sh
.venv/bin/python tools/dsp_image.py artifacts/original/7300_142.dat \
  --output artifacts/dsp-image-report.json
IC7300_TEST_IMAGE=artifacts/original/7300_142.dat \
  .venv/bin/python -m unittest discover -s tests -p test_dsp_image.py -v
```

## Loaded image

The decoded program is 163,592 bytes, SHA-256
`3093818ec5716abb00c16dd686a980c00812c88e73d0753b3c19e9f1d15429a1`.
It begins with an AIS script. The observed command formats are described in
TI's [C6747/45/43 bootloader guide](https://www.ti.com/lit/an/sprabb1c/sprabb1c.pdf),
sections 4.1, 4.6, 4.8 and 4.10. The parser supports only the observed sequential
read enable, function execute, section load, and Jump & Close commands. Other
commands are rejected, rather than guessed or executed.

| Load address | Bytes |
| --- | ---: |
| `0x11800000` | 97,056 |
| `0x1181ee30` | 25,800 |
| `0x1182f2f8` | 10,268 |
| `0x11832158` | 416 |
| `0x118322f8` | 152 |
| `0x11832390` | 44 |
| `0x11832400` | 416 |

The ranges do not overlap. Jump & Close specifies entry `0x118177a0`, within
the first range. The script ends at byte 134,272. Its 29,320-byte trailer is
29,312 bytes of `0xff` followed by ASCII `31101070`; the script does not load
that trailer. Section membership is not a code/data classification.

## Initialization and dispatch

Static inspection of the entry sequence shows a call to `0x11816f60` with
`0x1182f2f8`. That routine reads size/address records, calls copy helper
`0x11817420`, advances to the next eight-byte-aligned record, and stops at a zero
size. The structural parser covers that entire section: 463 records initialize
4,520 distinct destination bytes, with zero alignment padding and a final zero
word. This is not an emulation of startup or an observation of live DSP RAM.

One record initializes 1,024 bytes at `0x11818100`. Static dispatcher
`0x11812644` indexes this table by the high byte of its argument. Entry `0x42`
contains `0x11805ee4`; all 256 initial targets lie within loaded sections. This
provides a reproducible lead for following the CPU's AF command into the DSP.
It does not establish that the table is immutable after startup.

Private static inspection of the candidate handler finds command storage at
`0x11817b54`. A low-byte consumer at `0x11800300` derives a nonlinear target gain
and smooths it before multiplying an input sample. An inlined counterpart occurs
in the larger audio routine at `0x118104c0`. The serializer and board-output
association is still unresolved. Neither the structural report nor the derived
arithmetic model proves that the native receive stream is independent of AF gain.

## Validation and remaining boundary

Tests reject truncated words, sections and initialization records, unknown AIS
commands, nonzero padding, overlapping/wrapping destinations, missing terminators,
and an entry outside loaded sections. The original-image test checks the complete
layout and initialization counts and the command-table target. Report generation
checks input, tool and source-revision stability; output creation refuses an
existing path. The tool emits addresses and hashes, not original payload bytes.

The next DSP boundary is the routing from the AF-controlled buffer through the
packed DMA bank and serializers to the physical outputs. Parallel instruction
packets and delayed loads must be respected when following register values.
The board pin reading has not yet been reconciled with serializer configuration,
so pin names are not used here to assert which lane is native receive audio.
The [confirmed target capture](native-receive-target-capture.md) remains the
direct evidence that minimum AF did not mute native A in the tested USB-D setup.
