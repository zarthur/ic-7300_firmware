# Native receive lifecycle and discontinuity boundaries

The original receive interface has a **shared transport restart**, distinct from
native consumer queue flushing. A direct receive tap needs to distinguish them.
`tools/native_lifecycle.py` executes bounded original v1.42 branch and cursor-store
paths and complete start/stop routines in private memory; it never starts, stops
or configures physical hardware.

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

Two additional direct stop calls occur outside shared restart: `0x20029d90` and
`0x2002b6a0`. Both reviewed caller paths test the service gate and disable IRQ
before calling `0x200604c4`. A cold/shared-entry-only epoch would miss these
known stops. The [offline epoch wrappers](../prototype/native_receive/README.md#transport-epoch-prototype)
therefore observe stop and start entries too. Nested entry observations advance
the epoch independently; they are not independent failure counts. Those tests
qualify entry ABI and mask preservation, not completion of stop/start hardware
operations or a comprehensive reconfiguration inventory.

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

## FIFO configuration boundaries

The tool also executes four separate original store slices against private
memory at the peripheral addresses. This records configuration writes without
inventing hardware completion, FIFO contents or successful synchronization:

| Slice | Original writes relevant to SSIF0 |
| --- | --- |
| `0x2005fe54..0x2005fe64` | SSICR=`0x002b0030`, SSIFCR=`0xc3`: receive/transmit disabled, both FIFO resets asserted |
| `0x2005fefc..0x2005ff14` | Clear SSISR (`+4`) and SSIFSR (`+0x14`) for SSIF0 and SSIF1 |
| `0x20060044..0x2006005c` | SSIFCR=`0xcc`, SSICR=`0x3c2b0033`, SSIFTDR=0: release FIFO reset, enable receive/transmit and FIFO requests |
| `0x2006050c..0x20060524` | SSIFCR=`0xc0`, SSICR=`0x022b0030`: disable requests and receive/transmit, without asserting FIFO reset in this prefix |

Renesas register table 19.2 places **SSIFSR at `+0x14` and SSITDMR at `+0x20`**.
The earlier interface-map description of `+0x14` as a mode register was wrong.
Tests seed both channels' SSITDMR with zero, nonzero mode bits and all-one data;
all four slices preserve these words. Clearing FIFO status therefore does not
establish normal two-channel mode. Module-reset behavior or other initialization
must qualify that mode separately.

The status-clear slice receives the base registers established earlier in setup.
Intervening pin configuration, helpers and hardware waits are not executed.
Exact writes and preservation of surrounding bytes are checked. The start
prefix precedes delay and sync-input polling before DMA enable; neither these
stores nor the FIFO reset alone prove which channel occupies the first DMA word.

## Complete start routine and timeout behavior

The probe also executes the **complete** original start routine at `0x2006003c`,
including its original timer setup/clear and register bit helpers. Input pin
levels and the timer-expired bit are scripted private-memory observations; no
hardware peripheral, elapsed time, synchronization success or DMA transfer is
simulated. The preceding SSI/DMA setup routines are outside this execution.

The routine first enables SSIF0 and arms a compare at the supplied timer count
plus 32,000, wrapping to 16 bits. It then checks ten alternating low/high levels
of bit 9 at `0xfcfe3208`, enables DMA channel 4 then channel 3, enables SSIF1,
checks ten alternating levels of bit 5 at `0xfcfe320c`, and enables channel 5.
These GPIO observations do not establish FIFO channel order or sample phase.

Each wait can exit because its desired pin level was observed, the shared timer
flag became zero, or the timer-expired bit became one. The new fixtures exercise
immediate matches, two unsuccessful polls before each match, and persistent
expiry beginning at every one of the twenty waits or at the final check.
All called helpers run their original instructions; none has a substituted
successful return.

**A timeout does not suppress the DMA-enable writes.** At the end, the routine
writes service gate `0x2039038c = 1` only if timer flag `0x203903ac` is still
nonzero and timer bit 0 at `0xfcff0305` is clear. Otherwise it leaves the old
service gate unchanged. A supplied old value of one therefore remains one after
a timeout. This does not show that the normal restart passes a stale one: the
shared restart calls stop first, whose reviewed suffix clears the service gate.
It establishes that the start function alone does not provide a fresh success
value or clear the gate on failure. Original start always clears the timer flag
and enables IRQ on return, including when entered with IRQ already masked.

The 352 fixtures cover all timeout positions above, both initial gate values,
zero/two retries, timer counts zero/65535 and both initial IRQ masks. They verify
exact ordered non-stack writes, unchanged surrounding register/input bytes,
callee-saved registers, stack restoration and a 32-byte maximum stack write
footprint within this bounded call chain. The stack result excludes callers,
interrupt entry and preemption; it is not available target stack headroom.
The separate software-flag cancellation branch is not exercised here.

A successful return or nonzero service gate must therefore remain an observation,
not an adapter continuity certificate. The existing epoch contract still requires
fresh post-start block/cadence evidence and must reject a segment crossing a
restart. The tests do not qualify actual clock timing, bank reuse margins,
peripheral completion or physical restart acceptance.

## Stop return is not a DMA ownership handoff

The complete original stop routine `0x200604c4` and its callees now execute in
72 fixtures. They cover both SSI status waits, immediate readiness/two retries,
expiry at either wait, prior gate values 0/1/255, timer counts 0/65535 and both
IRQ masks. Ordered writes, register/input preservation, callee-saved registers,
stack restoration and a 48-byte bounded stack write footprint are checked.
The routine restores the incoming IRQ mask and always clears the service gate
and timer flag in these fixtures, including the timeout cases.

The three initial DMA control updates use the original bit helper with mask 2
and replacement zero. CHCTRL command bits read as zero, so these calls write
**zero**, not CLREN=1, to channel 3, 4 and 5 control registers. Both start and
stop probes supply the documented zero read values, rather than modeling these
command registers as retained state. The
[Renesas hardware manual](https://www.renesas.com/en/doc/products/mpumcu/doc/rz/r01uh0403ej0400_rz_a1h.pdf),
section 9.4.8 (PDF pages 331–332, printed 9-18–9-19), identifies CLREN as bit 1:
a zero write has no effect; a one requests disable. Section 9.7.11(2)(c–d)
(PDF page 379, printed 9-66) requires EN and TACT to be clear to establish a
completely stopped channel.

The executed stop code instead disables SSI requests/receive/transmit, waits on
SSI status bit 25 at `0xe820b004` and `0xe820b804` (or leaves those waits on
expiry), clears those statuses, and updates module-stop bits 4/5 at
`0xfcfe0440`. It never reads any DMA channel status register in these paths;
the exact access bounds reject such a read. This does not prove that ongoing
DMA continues after SSI is stopped, or that the stock restart is defective.
Withdrawal of requests and outstanding bus transactions are physical effects
outside these fixtures. It does mean that **returning from this stop function
is not a verified transfer of DMA-buffer ownership to a new consumer**.

A separate private `cpu-shared-restart-trial` executes the entire original
`0x200605e4` chain: stop, SSI/pin setup, DMA setup and the tail call to start.
Its 396 fixtures combine all 22 start-expiry positions, all three stop-expiry
choices, three old gate values and both initial IRQ masks. No callee is stubbed.
With CHCTRL reads supplied as zero, the checked command sequence is zero for
channels 3/4/5 during stop, software reset (8) for 3/4/5 during setup, then
enable (1) for 4/3/5 during start. No DMA status read occurs in these paths.
Stop clears the old gate before start: the final gate is zero on start expiry,
and one on the supplied successful start, regardless of the previous gate or
stop-wait expiry. Thus the standalone stale-gate observation does not describe
the gate after this normal shared-restart call chain.

The combined fixtures check gate/control writes independently, compare other
writes with the original successful trace, and enforce access bounds, preserved
callee-saved registers and stack guards. Other register semantics and peripheral
side effects are not thereby independently verified. In particular, a successful
start after a supplied stop timeout still does not establish that an outstanding
DMA transaction completed before reconfiguration.

An adapter may invalidate its private continuity epoch at stop entry. It must
not use the stop return, service flag or SSI status alone as permission to reuse
or rewrite a native DMA bank. Physical inactivity/reuse timing remains a
separate requirement. No new hardware operation or firmware patch is involved.

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
