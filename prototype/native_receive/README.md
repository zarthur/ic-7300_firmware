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
