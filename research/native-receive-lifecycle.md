# Native receive lifecycle and discontinuity boundaries

The original receive interface has a **shared transport restart**, distinct from
native consumer queue flushing. A direct receive tap needs to distinguish them.
`tools/native_lifecycle.py` executes bounded original v1.42 branch and cursor-store
paths in private memory; it never starts, stops or configures physical hardware.

## Shared service and restart

The audio service reads gate byte `0x2039038c` once at `0x20005bd4`. If nonzero,
its original call order is:

| Order | Handler | Status word | Role established by original buffer operations |
| --- | --- | --- | --- |
| 1 | `0x20060614` | `0xe82000e4` | Channel 3, split receive input into A/B queues |
| 2 | `0x20060778` | `0xe8200124` | Channel 4, fill output banks from software queues |
| 3 | `0x20060888` | `0xe8200164` | Channel 5, extract another input bank into its queue |

Every handler uses the same decision:

- Status bit 0 clear: restore its saved stack and tail-branch to shared restart
  `0x200605e4`, regardless of the other tested bits.
- Bit 0 set and bit 6 clear: restore its saved stack and return without processing.
- Bits 0 and 6 set: select bank 0 when bit 7 is set, otherwise bank 1, then begin
  the original acknowledgment/data path.

Tests execute 512 status fixtures for each of the three handlers (all low-byte
values with bit 31 clear/set), check the decision/bank, reject unexpected register
accesses and require original caller stack restoration for idle/restart exits.
Execution stops before the first acknowledgment operation or at restart entry.
Only the supplied status word is read; there is no hardware status progression,
cache-operation simulation or substituted successful restart.

The service does not re-read its gate between these calls. Thus a receive-only
observer of channel 3's failure branch is insufficient: either later handler
can request a transport-wide restart. Channel 4's output direction does not mean
these read-only probes activate a transmitter; they do not execute its data path.

The bounded original call-flow walk distinguishes:

| Entry | Ordered callees | Final tail branch |
| --- | --- | --- |
| Cold start `0x200605fc` | Bank initialization `0x2005f880`, SSI/pin setup `0x2005fdb4`, DMA setup `0x2005ff1c` | Start `0x2006003c` |
| Shared restart `0x200605e4` | Stop `0x200604c4`, SSI/pin setup `0x2005fdb4`, DMA setup `0x2005ff1c` | Start `0x2006003c` |

Cold start explicitly invokes bank initialization; shared restart does not invoke
that initializer. This is not proof that every nested helper leaves all buffers
or queue state unchanged. Callee effects and physical stop/start completion are
outside the bounded call-flow walk. Aligned direct cross-reference candidates
identify the three handler branches into restart; indirect callers remain possible.

## Queue lifecycle is different

Original initialization `0x2005fac4` sets the A queue's producer and consumer
bytes to zero. Original flush `0x2005fad8` copies producer to consumer. Neither
routine clears its 576-byte payload. Tests execute both operations for all 64
valid producer/consumer pairs and verify their exact byte-write footprints.

The A-queue flush is tail-called by `0x200671f4` for nonzero input; caller
`0x20067204` passes one. This is consumer backlog discard, not evidence of a
DMA stop. A future adapter that copies at the extraction boundary **before the
native queue push** has its own sequence and ownership. It must not advance the
native cursor or claim that flushing this unrelated consumer loses its own data.
An adapter attached after that queue would instead need explicit flush accounting.

## Required adapter contract

The installed first diagnostic does not implement the following lifecycle
instrumentation. Its successful capture does not prove all-mode continuity.
These requirements define the next bounded adapter design, not an instruction
to modify the radio now:

1. Maintain a private capture epoch. Cold start, entry to shared restart, and any
   other verified transport reconfiguration invalidate continuity. Observing
   only bank alternation, channel 3 status or native queue cursors is insufficient.
2. While transport validity is unknown, retain raw observations but mark the
   epoch invalid. A successful start-return/gate observation alone is not proof
   of stable sample cadence; establish fresh post-start observations before
   accepting a new segment. Do not join segments across the invalid interval.
3. Record explicit overflow/gap/configuration flags in the adapter's own bounded
   queue. Never borrow a native read cursor. A full adapter queue must report
   a gap or stop the capture, not overwrite unread data silently.
4. Preserve original acknowledgment/cache/extraction order and callback ABI.
   Lifecycle observation must not add blocking waits, allocation, file I/O,
   PTT operations or changes to original DMA/queue state.
5. Associate timestamps with the private epoch and observed sample index. The
   timer-relative projection from the first target capture is not UTC or proof
   of an acquisition epoch through a transport restart.

This resolves where the known common restart boundary lies and why queue flushing
cannot be its substitute. Physical restart behavior, complete reconfiguration
callers, live execution budgets and AF/squelch/AGC dependence remain open.

Reproduce:

```sh
.venv/bin/python tools/native_lifecycle.py artifacts/original/7300_142.dat \
  --output artifacts/native-lifecycle.json
IC7300_TEST_IMAGE=artifacts/original/7300_142.dat \
  .venv/bin/python -m unittest discover -s tests -p test_native_lifecycle.py -v
```

The report pins the original image, application, tools and revision; input/source
changes invalidate it. Generated evidence and original firmware remain private.
