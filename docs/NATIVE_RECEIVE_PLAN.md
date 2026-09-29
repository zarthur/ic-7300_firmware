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
