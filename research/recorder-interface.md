# Stored-audio boundary before native receive integration

Investigation date: 2026-09-29. Exact original v1.42 application SHA-256:
`4686728c9d1f7249b6278a29686a40b8fa5e527bd2428a76a33cd9395178c9a4`.
The read-only probe uses the pinned official image gate; unknown images and
applications are rejected before original routine execution.

## Finding

The old receive-recording lead at `0x20068840` belongs to stored-file metadata
parsing, not an established live PCM producer. The nearby format checker accepts
an 8 kHz mono PCM16 **stored-WAV format** in the tested cases. Neither this fact
nor the host's 48 kHz USB stream establishes the radio's internal live PCM rate.

The investigation narrows the boundary for #15/#19. It does not supply an audio
capture API, DMA ownership, task schedule, live timestamps or free workspace.

## Static caller evidence

`tools/recorder_interface.py` emits bounded control-flow records rather than
vendor instruction listings. Calls are recorded, not executed by the static walk.

- `0x20068788..0x200688ac` is the metadata parser containing the original lead.
  Its reviewed path tests INFO metadata, compares the recorder-data identification
  string and invokes field-copy routines `0x200686cc` and `0x20068744`. These
  copy fixed text fields; their addresses are not PCM buffer entry points.
- `0x20068bb4..0x20068c50` obtains a LIST chunk through `0x20068a94`, reads via
  `0x20068920`, then calls the metadata parser. The scratch pointer is
  `0x203fcbc6`. The requested chunk data is capped at 0xf0 bytes plus a four-byte
  size prefix. This is file-parser scratch, not demonstrated live audio storage.
- `0x20068dfc..0x20068e90` selects the fmt chunk, uses the same file-read wrapper
  and scratch pointer, then invokes `0x20068d04`. Both file wrappers access the
  object at `0x20390444 + 0x2c` around calls to `0x20186f60` / `0x20186f08`.
  Their apparent synchronization role is a hypothesis; their effects, ownership
  and scheduling are not modeled by this probe.
- `0x20068920..0x2006898c` composes previously identified seek/read calls
  (`0x200bc754`, `0x200bc6a4`) and checks the returned byte count. The chunk
  selector/reader use fmt, data and LIST tags. This supports the file-path
  classification without fabricating live stream or DMA effects.
- `0x20068e90..0x20068f54` combines envelope/format/data/metadata checks into a
  caller-supplied result structure. The format output byte is at result +0x30;
  the format return value contributes to result +1. A data length is divided by
  16,000 and stored at +0x34. This is not a recovered live timestamp source.

The wrapper limits and relationships above are static findings, not claims that
all file operations or synchronization helpers have executed successfully.

## Original-instruction format trials

The probe executes `0x20068d04..0x20068dfc` plus its actual little-endian readers
at `0x20068768..0x20068788` and `0x20068cf0..0x20068d04`. No helper return is
stubbed. Synthetic input, one output byte initially 0xa5, private stack and a
return sentinel are the only modeled state. Execution is limited to 500
instructions / one second. Every data access is checked against exact input,
output or stack bounds; unreviewed control flow fails closed.

Inputs are 20 bytes: a four-byte declared fmt size followed by the basic WAV
fields. All changes below are isolated single-field mutations of the first row.

| Stimulus | Return | Output byte |
| --- | --- | --- |
| size 16, PCM 1, mono, 8,000 Hz, 16,000 bytes/s, block align 2, 16 bits | 1 | 0 |
| declared size 15 | 0 | 0xa5 |
| declared size 18, same supplied basic fields | 1 | 0 |
| format tag 3 | 0 | 0xa5 |
| channels 2 | 0 | 0xa5 |
| sample rate 12,000 | 0 | 0xa5 |
| bytes/s 16,001 | 0 | 0 |
| block align 4 | 0 | 0 |
| bits/sample 8 | 0 | 0 |

All nine returned within 32–100 original instructions in the initial run.
The declared-size-18 case is accepted with only the basic fields supplied;
therefore this routine alone does not validate the complete chunk length or file.
The 12 kHz row deliberately leaves all other fields unchanged to isolate the
rate check; it is not a complete alternate-file compatibility survey.

The last three rejected cases still set the output byte to zero. The store occurs
after the sample-rate check and before later byte-rate/alignment/bit-depth checks.
Consequently, output-byte state alone cannot be interpreted as successful format
validation. Callers must honor the return value. This is an observed routine
behavior, not a demonstrated radio vulnerability or firmware defect.

## Interface status and next boundary

| Needed property | Current evidence | Status |
| --- | --- | --- |
| Stored-file format | Bounded original checker and static fmt caller | Supported for the tested basic fields |
| Metadata/scratch | Static LIST/fmt paths share 0x203fcbc6 and capped reads | File-parser storage only |
| Live sample rate/format | Neither file format nor host USB rate qualifies it | Unknown |
| PCM buffer address/length and DMA ownership | No producer/consumer pair established | Unknown |
| Task/lifecycle and concurrent ownership | Unexecuted helper pair/object identified | Unknown |
| Live timestamps/UTC relationship | File-length division is not a live clock | Unknown |
| Available codec workspace | Existing estimated 393,216 bytes plus adapter/DMA/stack overhead | Availability unmeasured |

The bounded enclosing callers are `0x20023ca4..0x20023d08` and
`0x2006bf64..0x2006bfd4`. The first opens a file through `0x200bc5f4`, passes
the returned handle to `0x20068e90`, then closes through `0x200bc64c`. The
second uses wrappers `0x2006990c` / `0x20069854` around the same summary call;
those wrapper effects remain unexecuted. This further supports the file-path
classification. Direct ARM scanning does not enumerate Thumb, indirect or all
possible callers.

The next exact entry to classify is `0x2006bfd4`, adjacent to the second caller:
identify its work/state ownership and determine whether it consumes stored audio
or connects to a receive sample producer. Do not assign it a recorder/DMA API
from adjacency alone. Stop at unknown task/DSP ownership rather than treating
metadata scratch as a capture ring. The known voice-file path remains separate
from any native receive adapter.

## Reproduction and validation

```sh
.venv/bin/python tools/recorder_interface.py artifacts/original/7300_142.dat --output artifacts/recorder-interface.json
IC7300_TEST_IMAGE=artifacts/original/7300_142.dat .venv/bin/python -m unittest discover -s tests -p test_recorder_interface.py -v
```

Use a new output path. Reports bind image/application, tool hashes, source state,
package versions, trials and bounded flows; changed evidence prevents a successful
report. Synthetic tests cover unknown-image refusal, malformed stimuli, source
mutation, execution limits and out-of-bounds accesses. Firmware-opt-in tests check
the matrix, early output side effects and the wrapper/scratch relationships.
Generated flows/disassembly remain under ignored artifacts. No radio command,
audio output, firmware image generation or device write is part of this tool.
