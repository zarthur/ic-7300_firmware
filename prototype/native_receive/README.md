# Bounded receive diagnostic prototype

This directory contains original ARMv7-A diagnostic code and offline integration
tests. These sources are not an installable firmware image. An exact private
candidate was installed by the owner and produced validated
[target captures](../../research/native-receive-target-capture.md).

`capture.S` copies 36 signed 16-bit samples from each of the two native extracted
streams into fixed storage, preserving their bit patterns and halfword alignment.
It retains a sequence and seven raw observation words per record, stops at 512
records, and cannot wrap or overwrite an earlier record. Storage is 90,128 bytes:
16 control bytes plus 512 records of 176 bytes. The standalone core is 164 bytes
and takes 343 emulated instructions per copy, not measured CPU cycles.

`transport.S` carries the frozen storage through 470 recorder payloads of 216
bytes. It leaves original audio unchanged before capture completion and after
export. Each fragment has a magic identifier, total size, byte offset, payload
length and FNV-1a-32 checksum. Host recovery requires all fragments in order in
one file and rejects incomplete or corrupt input. The installed diagnostic replaces part of a recording with capture data.
That portion is not listenable audio.

`wrappers.S` integrates both cores at three exact original v1.42 call sites. It
arms once on the first nonzero recorder write submission, reads raw timer/pending
observations at the extracted sample boundary, preserves native queue publication,
and routes the recorder copy through the carrier only while needed. Automatic
recording could also trigger it; the ring watermark gate is not a recording-start
indicator. See the [wrapper qualification](../../research/native-receive-wrappers.md)
and [export boundary](../../research/native-receive-export.md).

The two standalone cores have no absolute device addresses or external calls.
The wrappers have explicit pinned addresses and restore the original queue/write
operations. They introduce no file requests, allocator calls, task creation,
timer configuration, interrupt acknowledgment or transmit operation. Tests bound
execution and memory accesses; this is not a substitute for target verification.

The caller must provide valid nonoverlapping storage and serialize producers.
Capture control is status/count/reserved/reserved. Status values are disabled=0,
armed=1, full=2, invalid=3 and busy=4; reserved words start at zero. BUSY is an
observation state, **not an atomic lock**. The consumer must wait for FULL with
appropriate ordering, or stop the producer before reading a partial buffer.
There is no in-session rearm. The wrapper requires capture status/count and both
transport control words to be zero; a radio off/on action alone is not proof that
this private state was reinitialized. The owner's follow-up off/on recording with
DC connected contained no diagnostic frames. DMB instructions order publication;
offline execution does not prove cache or interrupt behavior.

`tools/native_capture.py` assembles with clang's ARM target and rejects relocations
or extra allocated sections. The standalone tests require no firmware:

```sh
.venv/bin/python -m unittest discover -s tests -p test_native_capture.py -v
.venv/bin/python -m unittest discover -s tests -p test_native_transport.py -v
```

Exact-image wrapper tests also execute original native queue and publisher code
through the actual patched calls. Original ring-to-file batching and partial
buffers have [offline qualification](../../research/native-receive-recorder-batches.md),
and the installed candidate produced complete timestamped exports. Target stack
headroom and latency, control dependence, and restart/loss association remain
unresolved; these captures do not complete issues #14 or #15.

## Transport epoch prototype

`epoch.S` is an offline, independently assembled boundary counter for the next
diagnostic. It is not included in `wrappers.S` or the installed v1 bundle.
It takes a separate, initialized 16-byte live state (`epoch`, `last_reason`,
`exhausted`, `reserved`) and reasons 1= cold-start entry, 2= shared-restart entry,
3= stop entry, 4= start entry. Epoch zero means no observed boundary. Each accepted boundary increments
the epoch; even another cold-start notification never resets it within the same
state lifetime. Overflow or an invalid reason permanently sets `exhausted`.
Consumers must reject exhausted state, regardless of the retained last epoch.

`epoch_wrappers.S` provides separate offline wrappers for these exact entries:

| Boundary | Original entry | Replayed prologue |
| --- | --- | --- |
| Cold start | `0x200605fc` | `push {r4, lr}` |
| Shared restart | `0x200605e4` | `push {r4, lr}` |
| Stop | `0x200604c4` | `push {r4-r10, lr}` |
| Start | `0x2006003c` | `push {r4-r6, lr}` |

Stop also has direct callers at `0x20029d90` and `0x2002b6a0`, so observing only
shared restart misses known transport boundaries. Nested boundaries each advance
the epoch: a shared restart followed by stop and start produces three observations,
not a count of three hardware failures. The original start unconditionally enables
IRQ near its return; a wrapper around the entire restart must not assume that the
incoming interrupt mask persists throughout it.

Each wrapper replaces the entry PUSH with an ARM B preserving caller LR. It saves
32 bytes, masks IRQ and FIQ around the counter update, restores the caller's masks,
APSR and general registers, replays the original PUSH, and continues at entry+4.
The standalone core still requires serialized callers/readers: barriers are not a
lock. All future readers of the live state must likewise use a coherent snapshot
protocol; the wrappers alone do not implement record capture or export.

`tools/native_epoch.py` gates the exact original image and executes these
substitutions only in private emulator memory. Trial code/state addresses
`0x20363000`/`0x2037e080` are not qualified for installation. Tests check 384 cases
across all four boundaries, all IRQ/FIQ mask combinations, condition flags,
ordinary and terminal counter states. Every live-state access must occur with
both masks set; preserved caller state, original saved stack words, 32-byte stack
footprint and exact state writes are checked. Execution stops before the first
original instruction after the prologue. Actual interrupt delivery, stack
headroom, mask latency, initialization before the first hook, complete boundary
coverage and placement ownership remain integration/target requirements.

Live state must be separate from frozen capture/export storage. Records will
need their own epoch snapshot and discontinuity status; this counter alone
neither detects every reconfiguration nor proves successful hardware startup,
stable cadence or sample validity. It deliberately has no operation that declares
the transport ready. Epoch identity is scoped to one explicitly initialized
state lifetime, not persistent across firmware loads or resets.

`tests/test_native_epoch.py` executes the compiled ARM core with strict access
bounds, verifies preserved registers/stack and neighboring storage, and checks
repeated boundaries, terminal overflow and invalid input. It does not simulate
hardware or concurrent callers.

## Two-phase capture prototype (v2)

`capture_v2.S` is a separate offline core; the installed capture, transport and
wrappers remain v1. Every DMA handler entry must call `begin` before reading
status or selecting a bank, including when capture is disabled or already frozen.
A ready path pairs this with `finish` after extraction; an idle or restart path
uses `cancel`. Observing only immediately before extraction still misses changes
between the original status read and extraction. The handler hooks below now
integrate these paths offline; recorder arming and a v2 carrier remain separate
integration work.

Storage is 114,704 bytes: a 16-byte header (`status`, `count`, magic `0x3252434e`,
version 2) and 512 records of 224 bytes. Each record contains:

| Byte offset | Contents |
| --- | --- |
| 0 | Sequence |
| 4 | Flags: epoch changed=1, epoch unknown=2, epoch exhausted=4, nested extraction=8, SSI observations unavailable=16 |
| 8 | Three epoch words captured by `begin`: number, reason, exhaustion |
| 20 | Three epoch words captured after the copy |
| 32 | Twelve observation words: tick/counter/pending twice, source-end pointer, SSICR, SSIFCR, SSISR, SSIFSR, SSITDMR |
| 80 | 72 bytes of stream A, then 72 bytes of stream B |

A separate initialized 32-byte live monitor tracks callback depth, copy ownership,
faults, poison and the early epoch snapshot. `begin` and the control portions of
`finish` mask IRQ/FIQ, then restore the incoming masks. The observation/sample
copy uses the incoming masks, so the core does not extend its critical section
over the long copy. Epoch writers and readers must share this single-CPU masking
contract. Barriers do not make the design safe for other CPU/DMA writers.

Nested callbacks mark the outer record and unwind depth without copying or
publishing storage. Only the outer callback can publish, after its copy returns.
On nesting it freezes an explicitly aborted partial capture (status 5), retaining
the affected record with flag 8. Its samples may be mixed and must not be used as
valid audio. An outer cancellation with nesting freezes status 6 without adding a
record; this explicitly reports the possible gap even when zero records were
captured. Ordinary cancellation returns to armed state with the count unchanged.
Epoch changes without nesting retain flagged records and continue,
allowing the host to identify observed boundaries. No flags means only that these
checks found no event; it is not proof of DMA-bank ownership or acquisition-time
continuity. A poisoned monitor never publishes frozen storage. Missing hook pairs,
invalid controls and depth overflow require external diagnosis, not silent rearm.

Full status 2 and aborted statuses 5/6 are immutable. Later callback bookkeeping uses
only the separate live monitor. Status 4 is busy and cannot be exported; status 0
is disabled and status 1 is armed. Initialization and transport publication are
caller responsibilities. The decoder accepts only a frozen or otherwise quiescent
snapshot and rejects inconsistent sequence, version, status, count and flags.

`tools/native_capture_v2.py` executes the compiled core in bounded private memory.
Tests include 512-record completion, flagging boundaries during extraction/copy,
all IRQ/FIQ masks, late arming, nested callbacks at the first/middle/final sample,
frozen-storage preservation, idle/restart cancellation, empty aborted captures,
missing pairs and poisoned controls. The nested tests
pause actual ARM copying and run nested core calls with a separate stack before
resuming; this models controlled interleaving, not hardware interrupt delivery.

This larger capture overlaps the earlier epoch wrapper's trial state address if
placed at the v1 capture base. It must not be combined with those trial addresses.
Final runtime placement, arming, lifecycle-bundle combination, v2 carrier/host
recovery, stack headroom, execution timing and target acceptance remain required.

## V2 handler hooks and SSI observation

`capture_v2_hooks.S` integrates the standalone core and `ssif_observe.S` at four
exact original instruction sites. `tools/native_v2_hooks.py` checks the image,
original instruction bytes, identical embedded cores, all-FF padding and disjoint
storage before substituting instructions in emulator memory. It has no image or
card writer.

| Hook | Original site | Behavior preserved |
| --- | --- | --- |
| Entry | `0x20060614` | Observe before the status read, replay `push {r4-r6, lr}` |
| Idle | `0x200606e8` | Cancel observation, replay `pop {r4-r6, pc}` |
| Restart | `0x20060644` | Cancel observation, tail-branch to shared restart |
| Ready | `0x200606d8` | Capture extracted A/B, then call the original A-queue producer; the original B-queue path follows |

The ready hook skips all additional timer/SSI observations unless this callback
owns an active outer capture. It preserves the original call inputs and flags.
The trial layout uses code at `0x20362000`, capture at `0x20364000`, live monitor
at `0x2038f000` and epoch at `0x2038f080`. These epoch addresses differ from the
older standalone lifecycle-wrapper trial; do not combine the old trial unchanged.

Renesas R01UH0403EJ0700 sections 55.2.11 and 55.3.5 identify STBCR11 bit 5 as
SSI0's clock-stop control and prohibit module-register access in standby. The
observer therefore masks IRQ/FIQ across its byte read of `0xfcfe0440` and, only
when bit 5 is clear, the five approved SSI0 word reads. It never reads the FIFO
data register and never writes peripheral registers. If gated, it skips SSI,
sets flag 16 and fills those five observations with `0xffffffff`. The decoder
requires this sentinel when the flag is set. Actual observed all-one words with
flag 16 clear remain raw observations, not a claim that they are valid settings.

This protects against maskable single-CPU clock-state writers, not arbitrary DMA
writers. Hardware FIFO state can change between reads; masking interrupts does
not make these five words an atomic hardware snapshot. They cannot identify the
first serial word in an already completed DMA bank.

Tests compare 2,048 entry/idle/restart decisions with unmodified original code,
including registers, flags and the saved entry frame. Another 1,024 ready cases
cover every gate byte and IRQ/FIQ mask combination, both banks, original queue
output, signed sample preservation, raw timer/SSI observations and skipped reads.
Additional cases cover an epoch change after bank selection, frozen/inactive
passthrough, and combined nested/unavailable flags. The active path reaches
144 bytes below the original caller's stack in these fixtures; target headroom
and timing are not established by that measurement.

Ready decisions stop before acknowledgment/cache operations. Tests then supply
the documented post-cache register/bank state and execute original extraction
and queue routines. Neither the intermediate hardware effects nor successful
transport restart is fabricated. Reproduce with:

```sh
IC7300_TEST_IMAGE=artifacts/original/7300_142.dat \
  .venv/bin/python -m unittest discover -s tests -p 'test_native*v2*.py' -v
```

### Version 2 recorder carrier (offline)

`transport_v2.S` and `tools/native_transport_v2.py` export immutable v2 storage
in 598 recorder payloads using `IC73RX02`. Each payload is 216 bytes: a 24-byte
header followed by at most 192 storage bytes. The last carries 80 bytes and 112
zero padding bytes. The original v1 core and decoder remain separate.

The exporter accepts full captures (status 2, count 512), captures aborted with
a final flagged record (5, count 1–512), and captures aborted without a final
record (6, count 0–511). Header identity, count and frame index are checked before
reading storage. Inactive captures, completed exports and invalid exports copy
the original audio payload unchanged. A malformed frozen header latches export
status 3. The caller must serialize export and keep frozen storage immutable.

Recovery requires every frame in order from one file, with exact offsets,
lengths, FNV-1a checksums and zero padding, then validates the capture records.
Checksums detect accidental corruption; they do not authenticate data. Export
status 2 means all bytes were exported, including for an aborted or empty capture;
the recovered capture status and flags must still be examined. This does not
establish sample validity, DMA ownership, or uninterrupted acquisition.

Firmware-free tests execute the ARM core for full, aborted and empty captures,
verify exact recovery and ordinary audio after completion, and reject malformed,
missing, duplicate, reordered and truncated frames. Recorder hooks, arming,
combined placement and target validation remain separate work.

### Combined v2 recorder and lifecycle hooks (offline)

`tools/native_v2_recorder.py` checks one combined layout against the exact v1.42
application and executes the original bounded paths with all ten hook sites
installed in private emulated memory. It has no firmware or SD-card writer.

| Region | Start | Bytes |
| --- | --- | --- |
| Capture hooks and observation cores | `0x20362000` | 1,508 |
| Relocated lifecycle wrappers | `0x20362800` | 380 |
| Recorder wrappers and v2 carrier | `0x20363000` | 688 |
| Capture storage | `0x20364000` | 114,704 |
| Live callback monitor | `0x2038f000` | 32 |
| Export control | `0x2038f040` | 8 |
| Lifecycle counter | `0x2038f080` | 16 |

The builder rejects overlapping substitutions, mismatched original instructions,
non-FF padding and changed embedded cores. The lifecycle code is byte-identical
to the independently tested wrapper except for its state-address literal.
Static non-overlap does not establish runtime ownership or target timing.

At `0x200497f0`, a nonzero recorder write submission can arm the capture once.
The wrapper masks IRQ/FIQ while requiring disabled status, zero count, correct
v2 identity, idle/unpoisoned callback state and unused export control. It changes
only capture status to armed, then restores all input registers, masks and
NZCVQ/GE flags before the original submission routine. An active callback causes
this attempt to be skipped; a later submission can try again. No lifecycle hook
rearms or clears a capture. Arming marks a submission attempt, not successful
filesystem completion.

At `0x20066f80`, only a 216-byte copy with frozen capture status and active export
control enters the carrier core. Other cases retain the original Thumb memcpy.
The original publisher still handles the ring's metadata and wrap behavior.
The recorder must serialize calls; these tests do not simulate scheduler ownership.

Combined tests cover trigger guards across masks/flags, all four relocated
lifecycle prologues including exhausted counters, full capture/export with
lifecycle changes inside capture windows, flagged and empty nested-callback
aborts, original publisher behavior, and actual restart-tail continuation.
Explicit context switches supply intervening callbacks; they are not hardware
IRQ delivery. Ready-path tests retain the existing ACK/cache boundary, and
submission tests stop at the original OS entry. Target stack/timing, file output
and runtime memory ownership remain unverified for v2.

### V2 recording analysis

```sh
.venv/bin/python tools/native_capture_v2_report.py recording.wav --output report.json
```

This read-only command requires one complete mono PCM16/8k WAV containing all
598 v2 frames. It validates the file, carrier and capture records and refuses to
overwrite an existing report. It preserves the raw samples, observation words,
flags and lifecycle states with field names, input hashes and analysis provenance.
The separate v1 analyzer remains available for recordings from the installed v1
candidate.

`export_complete` means every byte was recovered. `capture_outcome` distinguishes
full, aborted-with-record and aborted-without-record captures, including an empty
abort. Raw statistics include flagged records; empty statistics are null rather
than invented zeros. Nested-callback samples can be mixed.

Timing is projected separately within segments. A segment excludes unknown or
exhausted lifecycle state, within-record epoch changes, nested callbacks and
ambiguous timer snapshots. It also ends at an epoch change between records,
repeated bank identifier or nonpositive/ambiguous timer interval. A full-capture
rate appears only when one eligible segment covers an entire full capture.
Partial segments can still carry nominal estimates. Unavailable SSI observations
alone do not invalidate the independent timer observations; their raw sentinel
words and flag remain explicit.

These are projections using the nominal 32 MHz clock and recovered timer period,
not calibrated acquisition timestamps or proof of continuous audio. Recorder
sample matches are limited to eligible segments and ordinary audio before the
first diagnostic frame; they never cross a recorded lifecycle boundary or fault.

Original-instruction batch tests additionally pass all three frozen capture
forms through partial 4 KiB batches and ring wrap. A 598-frame export bracketed
by two ordinary payloads takes 32 batches, and recovers byte-for-byte. Stable file
tags and producer state are supplied fixtures; actual asynchronous I/O completion
and target SD output still require hardware evidence.
