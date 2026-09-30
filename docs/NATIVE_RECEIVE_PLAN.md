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

The original offline investigation opened no radio, audio, serial, or firmware-write
interface. The subsequent exact receive diagnostic was separately approved and
installed by the owner; the first target result is linked below. Further changes
require a concrete scope appropriate to their effects. Hardware observations cannot be
fabricated by emulation. Keep the goal active if required interface properties
remain unresolved and continue from the next evidence-backed boundary.

## Milestones (each records the evidence available at that stage)

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

The [first target capture](../research/native-receive-target-capture.md) now passes
complete WAV and carrier validation: 512 blocks, alternating banks, timer-relative
48 kHz cadence and 3,024 exact recorder samples identifying stream A at unity gain
in USB-D. Owner reports normal restart/reception at 7.074 MHz with no settings
changes. Continue with gain/control dependence and lifecycle/discontinuity
semantics; do not mistake this bounded success for all-mode/runtime qualification.

The [lifecycle follow-up](../research/native-receive-lifecycle.md) tests all three
native DMA handlers at their decision boundaries and separates common transport
restart from A-queue backlog discard. An adapter epoch must cover the shared
restart, including requests from other channels; the first installed diagnostic
does not yet carry this epoch. The second target capture confirms that minimum
AF volume does not mute native A in USB-D after a full DC-off restart; calibrated
gain, other controls and lifecycle continuity remain open.

The [recorder-control follow-up](../research/native-recorder-controls.md) resolves
settings record boundaries and tests the original downstream mute/copy/gain stage
for 1,536 control combinations. This separates CPU recorder effects from the
still-open DSP and physical-control dependence of the native input.

The [DSP image follow-up](../research/native-receive-dsp-image.md) makes the
original DSP load layout and initialized command-table location reproducible.
The AF command has a candidate DSP handler and gain consumer; mapping that gain
stage to the native receive lane remains open.

The [CPU-to-DSP gate follow-up](../research/native-dsp-controls.md) executes
shared-state publication, pending flag refresh and command-prefix construction.
It distinguishes cached gates from current state and tests the no-refresh path.
Physical channel identity and the state machine's radio semantics remain open.

The [v2 diagnostic follow-up](../prototype/native_receive/README.md) adds a
pre/post lifecycle counter, nested-callback abort reporting, clock-gated read-only
SSI observations and explicit full/aborted recorder exports. Combined offline
hooks now connect capture, lifecycle tracking, the recorder trigger and publisher
in a checked disjoint layout. This is not an installed candidate: runtime storage
ownership, target timing, single-file v2 recovery and hardware lifecycle evidence
remain open. Continue those qualifications alongside DSP producer/gain tracing;
keep issue #15 open until the interface requirements above are supported.

The [DSP receive-input map](../research/native-dsp-receive-input.md) connects
original receive descriptors, bank extraction, signed-word conversion and input
ramp controls. Schematic review identifies serializer 3 at the FPGA's `DFR_MOD`
connection. The slot association remains conditional on FIFO/frame alignment;
complete downstream processing, live ownership and target lifecycle acceptance
remain open. This source-side milestone does not complete the adapter contract.
