# Receive diagnostic export boundary

Exact original v1.42 only. The goal still requires an actual timestamped target
capture. No diagnostic image or device write is produced by these probes.

## Native file and task constraints

The command worker dispatch table at `0x20336090` maps open/read/write commands
15/17/18 to `0x200bb8d4`, `0x200bb958` and `0x200bb98c`. Workers receive a
52-byte queued request, rather than the public wrapper's four-argument ABI.
The open worker forwards filename, flags, mode `0x180` and the extra argument to
`0x200cac48`, then stores the returned handle through the caller's output pointer.
Read/write workers forward handle, buffer and requested byte count to
`0x200c9bec` / `0x200c9d0c`, then store the returned count through the output
pointer. Negative results propagate as completion errors; every nonnegative
result becomes completion status zero. A short write therefore has success
status but a smaller actual count. Submission tickets are not completion results.

`tools/native_export.py` executes these workers up to the underlying operation,
records forwarded arguments, injects explicit signed result fixtures and executes
the original result translation. It does not execute or simulate the filesystem.
The completion and semaphore waits discussed in the placement report remain
unsuitable for an ISR or a new blocking call in a normal radio task.

Original task-ID finder `0x2018763c` reads a configured limit of 11 from
`0x2033602c`. Tests cover all occupied prefixes, every individual hole, and full
exhaustion without modifying the table. Exhaustion returns zero, not another ID.
These fixtures establish no free slot on the radio. Thread creation also requires
stack/TCB resources and scheduler qualification; a spare task cannot be assumed.

## Existing recorder as the carrier

The recorder publisher at `0x20066f18` copies its 216-byte audio payload when its
native ring gate is enabled. That gate is **not proof of user recording**:
`0x20048afc` enables publication at occupancy <=1879, disables it at >=1909,
and preserves the previous state between those thresholds. Original-instruction
tests cover both prior states and consumer wrap. A trigger based on first
publication could capture prebuffer or boot activity and is unsuitable.

Its copy call at `0x20066f80` is a candidate boundary for
carrying diagnostic bytes through the recorder's existing file path. This avoids
adding another task, submitting new file requests or changing native wait policy.
It would intentionally replace part of the recorded audio during the diagnostic;
it is not a normal audio-recording feature.

Original ARM `prototype/native_receive/transport.S` implements the payload
transformation with caller-supplied pointers and no device addresses. It copies
original audio unchanged until the capture core is FULL with count 512. It then
emits the frozen 90,128-byte storage in 470 fragments, each exactly 216 bytes,
and resumes normal payload copies after completion. Invalid control values stop
diagnostic output and preserve the original payload. The final fragment contains
80 data bytes and 112 zero padding bytes.

Each fragment has magic `IC73RX01`, total size, byte offset, payload length and
FNV-1a-32 checksum, followed by up to 192 payload bytes. The checksum detects
ordinary corruption; it is not authentication. The host recovery routine requires
all fragments in sequence from one carrier file and rejects missing, reordered,
duplicate, truncated or corrupt fragments. It never silently combines partial
captures from different files. This makes dropped recorder data visible as an
incomplete capture. It does not prove a lossless target recorder or card.

The compiled carrier is 308 bytes. Full fragments take 1,209 emulated instructions;
this is not measured target latency. The capture and carrier require serialized
producers, stable frozen storage and qualified publication ordering.

The exact-image publication probe executes the original publisher on either side
of its payload-copy call, using an explicitly modeled argument/return bridge into
the carrier core. At ring indices 0 and 1913 it preserves original slot metadata,
producer increment/wrap, next-slot clearing and fill reset. Scratch and frozen
capture inputs remain unchanged. This tests the core's call contract and original
publisher continuation, **not a patched firmware wrapper**, cache coherency,
interrupt scheduling, or end-to-end SD output.

The [wrapper follow-up](native-receive-wrappers.md) implements the exact hooks
and raw observations in an offline emulator. Ring-to-file byte preservation,
single-file routing and target cost remain to be qualified before preparing an
owner-reviewed installation candidate. A target capture is still required before
issue #15 can close.
