# Receive diagnostic placement qualification

Exact original v1.42 only. This is offline evidence toward issue #15, not an
installable candidate or proof of unused runtime memory.

`tools/native_placement.py` executes the complete original startup translation
table construction from `0x200b8d2c` to `0x200b8fe8` (41,189 instructions). It
stops before the TTBR0 and domain-control writes. Synthetic RAM includes the
16 KiB first-level table, descriptor attributes and the 1 KiB second-level table.
Unknown execution or accesses outside the reviewed ranges fail the probe.

The final descriptor for `0x20300000` is `0x20385c06`. Padding
`0x2036166c..0x20390000` lies entirely in this section; its low descriptor bits
match the section containing application code at `0x20000000`. The descriptor
has XN clear, AP=3 and domain=0. A scan of regular section descriptors finds only
one mapping to that physical section. It does not exclude small-page aliases,
later changes or computed accesses. These fields follow the short-descriptor
layout used by [Arm CMSIS Core-A](https://raw.githubusercontent.com/ARM-software/CMSIS_5/5.9.0/CMSIS/Core_A/Include/core_ca.h).

The later startup sequence at `0x200b9440..0x200b9470` enables the MMU and caches
but preserves inherited WXN/UWXN bits. Therefore XN=0 alone is not evidence of
actual executable permission. No CP15 effects, cache coherency or hardware
execution are simulated. Matching the existing application mapping is useful
placement evidence, not a substitute for validating the final hook and payload.

None of the three startup scatter destinations overlaps the padding. The zero
entry has `0x2036166c` as its source argument; original Thumb helper
`0x20186488` overwrites that argument with zero. Four bounded fixture sizes
(4, 16, 72 and 4096 bytes) execute the original helper, preserve surrounding
canaries, clear exactly the destination and make no reads from the padding.
This tests the source-ignore behavior without pretending to execute all startup.

## Remaining diagnostic work

Reserve a precise code/state/record footprint only after checking the insertion
and hook together. Preserve original queue publication and register/stack state;
never borrow native read cursors. The candidate should capture both extracted
streams into bounded storage, stop copying when full, and export in task context.
A post-boot trigger, coherent raw timer observations and measured interrupt cost
remain necessary.

File calls at `0x200bc5f4` (open), `0x200bc64c` (close), `0x200bc6a4` (read) and
`0x200bc6fc` (write) submit requests via `0x200bc048`. Successful submission
returns a request ticket, not completed I/O. Queue submission can instead return
2. Request buffers and output pointers must survive completion. The original
completion routine `0x200b9af8(ticket, 1)` can wait indefinitely: it selects an
infinite event wait and loops while no matching completion is found. Calling it
from an ISR, or assuming it is a bounded poll, is unsuitable. Recover open flags,
worker result semantics, bounded polling and cleanup before writing an exporter.
The recorder wait wrapper's `0x46` argument is passed to error translation; it
has not been established as a timeout.

No new firmware or SD-card content is produced by this probe. Timestamped target
capture, channel/gain identification and installation scope remain open.
