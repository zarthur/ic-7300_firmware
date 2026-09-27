# Hardware test policy

Use the [per-test checklist and completed desktop example](TEST_CHECKLIST.md)
to record prerequisites, steps, stop conditions and results.

## Phases

1. Desktop and synthetic-data tests only.
2. Receive-only hardware observation with no route to PTT.
3. Dummy-load transmission at the minimum practical power, with external
   frequency, power, and spectral monitoring.
4. Supervised low-power on-air interoperability testing after a documented
   review of the applicable operating rules.

Progression requires the preceding phase's acceptance criteria and a tested
rollback/recovery procedure for image changes. Read-only stock observations may
precede recovery proof. The owner has authorized planning around their single
original IC-7300; a spare radio is not a prerequisite for this project. This
exception does not authorize an unspecified firmware write. Back up settings
before every image/update experiment and establish recovery coverage for
firmware, calibration, configuration and bank metadata.

Before the first modified-image boot, demonstrate a recovery route that does
not depend on the main application booting. Local emulation and a successful
menu reinstall do not establish this. Present the exact image hash, offline
validation, recovery evidence and procedure for the owner's specific hardware
review before a write. If independent recovery cannot be demonstrated, stop
before flashing; do not discover it by corruption or interrupted power.

The initial experiment to establish recovery must have its own reviewed hardware
plan and stop conditions, using an unmodified radio and official images. It cannot
claim recovery is proven in advance or authorize a modified-image boot. No such
hardware experiment is part of the current desktop phase.

## Mandatory controls for any future TX test

- A present, licensed control operator and an explicit per-session TX arm.
- Default TX-off after boot, reset, mode/band change, clock fault, cancellation,
  or any software error.
- A visible TX indication, bounded transmit duration, watchdog, and immediate
  cancel path that flushes queued audio and releases PTT.
- A dummy load and independent instruments before any antenna-connected test.
- Recorded test plan, firmware hash, configuration, measurements, and outcome.

This policy does not authorize a transmission. Operators must comply with their
own license privileges, local regulations, band plans, station-identification
requirements, and automatic-control restrictions.
