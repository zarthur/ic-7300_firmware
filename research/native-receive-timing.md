# Native receive timing boundaries, v1.42

The [receive map](native-receive-interface.md) now has an intended timer scale,
but not a proven acquisition clock. Three different counters must be kept
separate. The exact-image probe `tools/native_timing.py` executes their isolated
original code with synthetic register storage. It does not emulate progressing
timers, interrupts, cache effects or elapsed target time.

## Reproduction

```
.venv/bin/python tools/native_timing.py artifacts/original/7300_142.dat \
  --output artifacts/native-receive/timing.json
IC7300_TEST_IMAGE=artifacts/original/7300_142.dat \
  .venv/bin/python -m unittest discover -s tests -p test_native_timing.py -v
```

The same original application hash and source-mutation checks as the receive
probe apply. Reports include source/tool identities, bounded ARM/Thumb flows,
register-write sequences and boundary trials. The five timing tests cover
unknown inputs, source mutation, comparison thresholds, setup differences and
rollover. Register writes occur only in private emulator memory.

Register semantics below use the Renesas hardware manual pinned by hash in the
[receive map](native-receive-interface.md): chapters 10 and 11, especially
Table 10.9, Tables 11.6/11.8/11.10 and section 11.3.5.1. Nominal times are
calculations from these definitions and firmware constants, not measurements.

## Counter map

| Source | Original configuration/evidence | Timestamp limitation |
| --- | --- | --- |
| OSTM1 at `0xfcfec400` | `0x20005d2c` stops it and sets control=2 (count up). `0x20005d78` starts; `0x20005dc8` stops. `0x20005d88` compares counter `+4` to `floor(microseconds*32000000/1000000)` in the tested 0..1-second range. | The delay routine `0x20005dd8` starts, polls and stops this timer. It is not an uninterrupted system clock. |
| OSTM0 at `0xfcfec000` | `0x200b93b0` stops, sets control=1 (interval mode plus interrupt on start), writes compare=32000, starts, returns IRQ ID 134. | Counter runs down and reloads. Reading it alone does not identify an epoch. |
| Scheduler counter `0x20390a78` | Thumb block `0x2018809a..0x201880a4` increments a 32-bit word in tick processing `0x20188084`, called from the interrupt path at `0x200059e4`. | Wraps at 2^32; does not contain UTC or a fractional timestamp. Interrupt delays can make a read stale. |
| MTU2 channel 3 | Setup writes control=0 (`P0/1`), count=0, compare A=8000. Service advances the 16-bit compare at `0xfcff0218` by 8000 modulo 65536. | Compare schedule is not a delivered-interrupt counter. Several elapsed periods or wraps can be ambiguous after delayed service. |

Original VFP instructions in the delay comparison execute in the probe with the
emulated coprocessor enabled. Trials straddle thresholds from 1 microsecond to
1 second; they confirm **32 counter ticks per requested microsecond**, with no
register writes in that predicate. This supports the software's intended 32 MHz
clock scale. It does not identify physical drift or authorize use of OSTM1 as a
new capture timer.

The MTU3 clock selection then supports an intended service spacing of
`8000/32000000 = 250 microseconds`. Its 16-bit counter wraps every 2.048 ms at that
nominal rate. The compare advance is tested at the rollover boundary, including
57535 -> 65535 and 57536 -> 0. These results establish arithmetic, not guaranteed
interrupt latency. The earlier receive extraction implies a nominal 750-us DMA
block (36 samples at 48 kHz); that is a separate clock domain.

For OSTM interval mode, Renesas specifies **compare + 1** clock cycles per period.
Compare=32000 therefore means 32001 clocks, or 1.00003125 ms at exactly 32 MHz.
Multiplying the scheduler counter by an assumed exact millisecond loses this
nominal 31.25-ppm distinction. This is not a measured error of the radio's UTC
clock: the initial interrupt, oscillator behavior, RTC synchronization and later
clock-control changes have not been characterized.

## Acquisition-time contract

No recovered counter can simply be relabeled a sample timestamp:

- OSTM1 is actively used for finite delays. Reconfiguring it would affect the
  original firmware; copying its current value cannot establish continuity.
- OSTM0 needs its software epoch and a coherent fractional-counter observation.
  A double read of the software tick alone does not detect an interrupt that is
  pending but not yet serviced. A future interpolation must handle that case,
  reload, priority/preemption, start interrupts and wrap explicitly.
- MTU3 provides finer observations but wraps quickly. A software extension needs
  proven service bounds or an independently continuous reference, plus explicit
  discontinuity handling when those bounds are exceeded.
- SSIF0 uses an external audio clock. The service/observation time occurs after
  acquisition of a DMA block; first-sample time includes the block duration and
  unknown FIFO/interrupt latency. Sequence numbering alone cannot recover lost
  blocks or identify the absolute capture epoch.

A future diagnostic should preserve raw counter observations and validity/loss
flags rather than prematurely emitting UTC nanoseconds. Pair acquisition sample
indices with a verified monotonic clock and measure the delay distribution under
scope/UI/SD load; associate that clock with the RTC separately under #17.

The next offline work is to resolve the DSP stream/gain controls and identify
owned storage plus an insertion/export mechanism for a concrete diagnostic
candidate. Timestamped target capture remains required for #15. No timer, radio,
SD card or installed firmware was changed by this investigation.

## Host transmit time-quality gate

The portable FT8 sequencer now requires an explicit policy before
`qso_enable()` can arm a session. Each `qso_clock_sample` supplies current UTC
and monotonic milliseconds, the monotonic time of the last successful UTC
synchronization, a conservative current uncertainty bound, and a source-valid
flag. The sequencer rejects unknown/invalid source state, future or stale sync
epochs, uncertainty above the configured ceiling, backward UTC/monotonic values,
and UTC-versus-monotonic discontinuities above the existing 250 ms prototype
bound. TX validity is checked against current monotonic time at audio generation
and backend queue/drain reports; each receives a fresh UTC/monotonic quality
sample, so expiry or a newly observed clock fault cancels the reservation and
requests backend abort.

No default time-quality budget is selected. Unit tests use synthetic limits to
prove gate behavior; those values are not a radio recommendation. This is a
software contract only: the target RTC/monotonic association, conservative error
growth during holdover, physical clock accuracy, and safe time-setting procedure
remain unmeasured. The issue needs those measurements before an owner can choose
radio limits. No radio clock was changed.

## Passive clock measurement plan (not performed)

**State:** Phase 2 receive-only observation, TX unauthorized. The procedure has
not been run. It requires a separately authorized session and an operator
present. Do not connect a PTT control, set the radio clock, install firmware, use
the SD card, or add an internal connection.

**Capture fields:** For each host sample, record UTC milliseconds, monotonic
milliseconds, last successful UTC-sync monotonic milliseconds, current
conservative UTC uncertainty in milliseconds, source-valid state, source/provider
identity, and the observation sequence number. Compute synchronization age as
`monotonic_ms - last_sync_monotonic_ms` and offset change as
`(UTC_i - UTC_0) - (monotonic_i - monotonic_0)`. Also record the radio's
read-only displayed time, date, timezone/UTC offset and display resolution if
available. Missing or unbounded fields must be recorded as unknown, never
inferred from a displayed clock.

**Steps and instrumentation:** The foreground scaffolding is
`tools/clock_sample_logger.py`. A one-sample local check is:

```sh
python3 tools/clock_sample_logger.py --output /tmp/clock-sample.jsonl --count 1
python3 tools/clock_sample_logger.py --verify /tmp/clock-sample.jsonl
```

The standard-library provider brackets `time.time_ns()` with
`time.monotonic_ns()` reads and records the pairing span, source identity and
clock implementation/resolution. It explicitly marks last-sync time and a
conservative UTC uncertainty as unavailable, and synchronization validity as
unknown. It therefore emits an **unqualified** host record and refuses to map it
to the C `qso_clock_sample`; it does not infer quality from a successful clock
read. `--provider fixture --fixture FILE` injects deterministic samples for
offline gate scenarios. Optional age/uncertainty limits have no defaults. The
JSONL log has contiguous sequence numbers and a SHA-256 hash chain; this detects
record edits but does not attest the source clock. No background service is
installed. Actual observation would still use the host logger once per second
for one hour and note any radio display at the start and every five minutes.
Use only the host and radio already in the setup; no external timing instrument
is specified or assumed.

**Interpretation:** A missing radio display or unknown timezone/resolution allows
host-clock observation only, not a radio comparison. Complete host fields with
valid source and forward UTC/monotonic progression allow a progression report;
they do not qualify accuracy or establish a policy limit. Invalid source,
backward time, an observed step, or unbounded uncertainty is an adverse result:
preserve the log and do not arm. A UTC/monotonic difference over 250 ms may be
reported as crossing the current software heuristic, but it is not a radio
acceptance threshold. Maximum sample-age and uncertainty limits remain unset.

The selected Python standard-library backend has no API for last successful UTC
sync, source-valid state or conservative UTC uncertainty. A verified host OS
provider for those fields remains a specific implementation gap. The existing
firmware evidence likewise does not expose a coherent externally readable
UTC/monotonic sample with last-sync time, source validity and uncertainty; its
mapped hardware counters have different epochs, wraps and service limitations.
No new flash is needed for a coarse, read-only display observation, but the
current host backend and existing firmware do not provide enough data to
qualify the radio time-quality gate. There is no executable target-clock
qualification procedure until a read-only telemetry provider supplies those
fields, and no hardware/TX test is ready.
