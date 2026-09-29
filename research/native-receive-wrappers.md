# Native receive diagnostic wrapper bundle

The original ARM bundle now replaces the three exact original v1.42 calls in
an offline emulator. This advances the diagnostic beyond the modeled carrier
bridge. No firmware container or SD-card image is produced by this milestone.

| Call site | Original operation | Diagnostic behavior |
| --- | --- | --- |
| `0x200606d8` | First native queue push | While armed, read six ordered clock/pending observations and copy both extracted streams; restore original inputs/flags and tail-call the queue push. |
| `0x20066f80` | Recorder payload memcpy | Use original memcpy before capture completion and after export. During export, write one carrier fragment, then continue the original publisher. |
| `0x200497f0` | Recorder write submission | Arm once on the first nonzero write request, then execute the original submission. Zero-length requests and noninitial diagnostic state cannot rearm. |

The trigger is a **write submission**, not proof of successful file I/O or of a
physical button press. Automatic recording, if configured, could also trigger it.
The publisher's occupancy gate is not used as a trigger. A future owner-run test
must control recording state and collect the resulting complete carrier file.

## Bundle and placement

`prototype/native_receive/wrappers.S` is 876 bytes, including its 32-byte header
and literal pool. The capture and carrier core bytes inside it exactly match
the separately tested standalone cores; namespacing assembly labels changes no
instructions. It assembles as a single relocation-free ARM ELF text section.

The proposed placement is code at `0x20362000`, zero-initialized capture storage
at `0x20364000` (90,128 bytes), and carrier control at `0x2037a020` (8 bytes).
`tools/native_wrappers.py` requires the pinned original application, verifies the
three original call encodings, checks that all insertion bytes are FF, checks
bounds/non-overlap, and constructs only those six edits. Startup placement
qualification remains as documented earlier; this does not prove the absence
of every possible computed runtime alias.

## Raw observations

Each sample record retains, in order:

1. Native tick word at `0x20390a78` before the snapshot.
2. OSTM0 counter at `0xfcfec004` before the snapshot.
3. GIC pending word at `0xe8201210` before the snapshot.
4. Native tick after the snapshot.
5. OSTM0 counter after the snapshot.
6. GIC pending word after the snapshot.
7. Original extraction's final DMA pointer, identifying which bank was selected.

DMB instructions order the reads. The OSTM0 counter is read-only in the
[Renesas hardware manual](https://www.renesas.com/en/doc/products/mpumcu/doc/rz/r01uh0403ej0400_rz_a1h.pdf).
The pending read is from the distributor's pending-status register, not the
CPU interrupt-acknowledge register; the distinction is also explicit in
[Arm's CMSIS GIC accessors](https://raw.githubusercontent.com/ARM-software/CMSIS_5/5.9.0/CMSIS/Core_A/Include/core_ca.h).
For interrupt ID 134, the relevant pending bit is bit 6. The whole pending word
is retained. These raw observations do not establish UTC, actual clock frequency,
interrupt loss, or a coherent corrected timestamp by themselves.

The DMA source-end pointer is `0x203fb180` or `0x203fb3c0` after the original
36-iteration extraction. Keeping that existing register avoids rereading a DMA
bank-selector register after it might have changed.

## Verification and remaining work

Original-instruction tests execute the **actual patched call sites**. Both DMA
banks and inactive/armed/full/invalid/busy states preserve original queue-entry
registers, flags and both queue outputs. Recording submission preserves the
original global state and arguments up to the kernel semaphore boundary, where
execution deliberately stops. Inactive carrier paths match the original full
publisher at ring indices 0 and 1913.

The full fixture collects 512 records through the patched original extraction
and queue path, checks both signed sample streams and raw observation rollover,
then exports/reconstructs all bytes through 470 patched original publications.
It verifies final shutdown, original payload resumption, metadata, ring wrap,
fill reset and frozen storage. Access bounds reject any write to timer, pending
or tick state, and execution bounds reject new calls outside the reviewed paths.
No operating system, DMA engine, cache maintenance, filesystem or physical radio
is simulated. The DMA fixture starts after cache maintenance with the original
saved stack frame explicitly supplied.

Still required: qualify ring-to-file byte preservation and routing, including
initial/final partial buffers; assess stack headroom and target timing; prepare
and verify a concrete firmware candidate and its update footprint; obtain owner
review for the new installation; collect and analyze a timestamped target capture.
Issue #15 and the native receive goal remain open.

The subsequent [batch tests](native-receive-recorder-batches.md) establish byte
preservation through original selection/copy with explicit stable recorder
prestates. Single-file target output and live timing/stack behavior remain open.
