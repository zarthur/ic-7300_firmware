# Native receive interface investigation

Starting baseline: `7853426`; exact pinned original v1.42 application.
Objective: recover an evidence-backed receive sample interface, beginning at
`0x2006bfd4`, with format/rate, buffers, producer/consumer ownership, lifecycle,
task/DSP boundaries and timestamp relationships sufficient to design a bounded
receive-only adapter. An unresolved boundary is progress, not completion of the
whole objective.

1. Classify `0x2006bfd4` and its callers/callees using bounded ARM/Thumb analysis.
   Separate stored-file work from live sample production; follow evidence rather
   than adjacency or string names.
2. Trace data and state from the identified path to the sample producer/consumer.
   Record addresses, lengths, transformations, synchronization, setup/teardown,
   and any external DSP/controller interface. Investigate indirect callbacks.
3. Execute isolated original routines against synthetic stimuli where inputs and
   memory bounds can be justified. Fail at unknown effects, avoid invented helper
   success, and test ownership/wrap/error behavior rather than only happy paths.
4. Implement reproducible exact-image-gated evidence tooling and meaningful
   synthetic/original-image tests. Keep firmware/disassembly/generated evidence
   private; publish original analysis and test code only.
5. Produce the interface map and adapter contract, including timestamp limitations,
   bounded storage requirements and any measurements necessary on target. Do not
   label unknown memory as free or host/stored-audio rate as live PCM rate.
6. Validate affected tests and the full desktop profile, review evidence against
   each required property, and integrate documented results with passing CI.

This work opens no radio, audio, serial, or firmware-write interface. Existing
approval covered the completed display-only test; any new target instrumentation
requires a concrete separately reviewed scope. Hardware observations cannot be
fabricated by emulation. Keep the goal active if required interface properties
remain unresolved and continue from the next evidence-backed boundary.

## First milestone

The [interface map](../research/native-receive-interface.md) completes initial
classification and establishes a reproducible live DMA-to-recorder chain. The
probe suite executes original queue, sample selection, DMA extraction, record
publication and format-writing routines against synthetic memory. Channel/gain,
absolute acquisition timing, owned storage and target diagnostic acceptance
remain open. Continue through the numbered requirements in the map; do not
restart at the file reader or mistake this milestone for the whole goal.

The [timing follow-up](../research/native-receive-timing.md) recovers intended
clock scale and rollover semantics. Delay-timer reuse and pending interrupts
prevent treating the recovered raw values as a continuous acquisition clock.

The [memory/cursor follow-up](../research/native-receive-memory.md) identifies
the shared allocator and occupied framebuffer, tests allocation failure/reuse,
and verifies both second-queue cursors have consumers. Qualify diagnostic
placement and export next; no native capture has been collected yet.

The [placement follow-up](../research/native-receive-placement.md) executes full
startup table construction before CP15 writes and tests the scatter zero helper.
Padding retains application descriptor attributes and is outside scatter
destinations; runtime ownership, final hooks and asynchronous export remain open.

The [bounded capture core](../prototype/native_receive/README.md) now has original
ARM code and firmware-free execution tests. It retains both streams and stops
after 512 records. It is not hooked into firmware: trigger, raw observations,
export and target measurement remain required.

The [export boundary](../research/native-receive-export.md) now includes original
file-worker result and task-ID exhaustion probes plus a bounded recorder-carrier
core. A modeled bridge preserves original publisher metadata and wrap behavior.
Qualify the actual wrapper, recording trigger, timer observations and single-file
output next; no target capture exists yet.

The [wrapper bundle](../research/native-receive-wrappers.md) now executes actual
patched call sites in offline tests, including a full 512-record capture and
470-fragment reconstruction. Triggering is the first nonzero native write
submission, not the ring watermark gate. Ring-to-file routing, candidate update
validation, target stack/timing checks and owner-run capture remain outstanding.

The [recorder batch follow-up](../research/native-receive-recorder-batches.md)
qualifies original selection and byte copying across partial 4 KiB writes, ring
wrap and file-tag changes. All 470 synthetic fragments reconstruct exactly after
batching. Submission/completion and actual SD output remain target observations;
this is not a whole-recorder simulation.
