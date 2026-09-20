# Hardware test policy

## Phases

1. Desktop and synthetic-data tests only.
2. Receive-only hardware observation with no route to PTT.
3. Dummy-load transmission at the minimum practical power, with external
   frequency, power, and spectral monitoring.
4. Supervised low-power on-air interoperability testing after a documented
   review of the applicable operating rules.

Progression requires the preceding phase's acceptance criteria and a tested
rollback/recovery procedure. A test radio must not be the only operational
station. Back up settings before every image/update experiment.

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
