# Bounded receive capture core

This is original ARMv7-A diagnostic code, not a firmware image. It has no absolute
radio addresses, external calls, allocator, filesystem, timer-control or transmit
operations. Integration and installation are not yet implemented.

`capture.S` receives a control/storage pointer, a pointer to both native extracted
streams and a pointer to seven caller-supplied observation words. It copies 36
signed 16-bit samples from each stream into one record, retaining their bit
patterns. Halfword loads support the native arrays' two-byte alignment. There
are 512 slots; no wrap or overwrite occurs. The last publication marks FULL.
An out-of-range count marks INVALID without writing a record. Inactive states
leave storage untouched.

The storage is 90,128 bytes: 16 control bytes and 512 records of 176 bytes. Code
is currently 164 bytes. Each record contains a sequence word, seven raw words
and the two 72-byte streams. Raw words are deliberately uninterpreted until the
integration wrapper's observation contract is recovered and implemented. They
are not fabricated timestamps, UTC, or measured sample rates.

The caller must initialize status=1, count=0, reserved words=0, provide valid
non-overlapping pointers and serialize producers. BUSY is an observation state,
**not an atomic lock**; it cannot establish reentrancy safety. A consumer must
wait for FULL with the appropriate ordering, or stop the producer before reading
a partial buffer. There is no reset/rearm operation in the core. DMB instructions
order publication but the offline engine does not prove target cache behavior.
The routine follows the ARM procedure-call convention; it does not preserve
caller-saved registers or flags. An integration wrapper must preserve whatever
the original hook requires and continue the original queue publication.

`tools/native_capture.py` assembles with clang's ARM target and extracts the
standalone ELF text section. It rejects relocations and other allocated data;
no linker, external helper or proprietary bytes are needed. The test harness
bounds all code execution, input reads and storage writes, checks input and
canary preservation, and verifies the preserved registers and stack. A copied
record takes 343 emulated instructions, not 343 measured CPU cycles. The decoder
validates an immutable storage image and preserves raw observations for later
analysis.

Run the firmware-free tests:

```sh
.venv/bin/python -m unittest discover -s tests -p test_native_capture.py -v
```

Before integration: recover the post-boot trigger and task context, define and
implement timer snapshots, qualify the exact hook and storage placement together,
and qualify the recorder carrier through its actual file output. Native file
submission can block on an OS semaphore, and its completion path can wait
indefinitely; the carrier therefore adds no file calls to the audio ISR or normal
radio tasks. The existing recorder retains request lifetime and file cleanup.
Target latency, drop and channel/gain measurements remain required by issue #15.

## Recorder carrier prototype

`transport.S` now provides a second standalone core for the existing recorder's
216-byte copy boundary. It emits a completed capture in checksummed fragments,
then resumes copying normal recorded audio. It does not start recording or create
a task/file. The intended test would use an owner-started recording; part of that
recording would contain diagnostic data rather than listenable audio. This remains
an offline prototype with a modeled bridge, not an installed hook. See the
[export boundary](../../research/native-receive-export.md) for lifecycle tests,
protocol details and the remaining integration requirements.
