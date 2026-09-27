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

Progression through receive, dummy-load and on-air phases still requires the
preceding phase's acceptance criteria. The first custom-image recovery decision
is governed by the specific policy below; it does not waive TX prerequisites.

The owner permits planning around their single original IC-7300 using software
and the existing setup only. No additional hardware or internal connections are
part of this work. Read-only stock observations may precede recovery proof.
Back up settings before any image/update experiment and document actual backup
coverage for firmware, calibration, configuration and bank metadata.

For the first modified-image experiment, follow
[FIRST_CUSTOM_FIRMWARE.md](FIRST_CUSTOM_FIRMWARE.md). Build the exact candidate,
complete applicable offline validation and independent review, and present the
image hash, test procedure, restoration options and unresolved risks before
requesting the owner's specific decision. Passing tests are not a guarantee.

Owner clarification on 2026-09-27 supersedes the earlier unconditional requirement
for demonstrated application-independent recovery before considering a first test.
Prefer a proven software recovery route; if it remains unproven or unavailable,
the owner may explicitly accept that risk for the exact candidate after reviewing
the evidence. This policy does not itself authorize a firmware write, and an
approval/merge of desktop code is not installation authorization. Do not claim
recovery is proven or close its issue based on risk acceptance.

Never deliberately corrupt firmware or interrupt power to discover recovery.
Any physical recovery experiment requires its own concrete, reviewed procedure;
no unspecified device command or write is authorized by a research plan. Define
pre-write, in-progress and failed-boot responses before any installation.

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
