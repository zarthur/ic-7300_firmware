# Platform recovery and measurement procedures

Status: official 1.41 → 1.42 update observed; recovery and custom-image tests not executed. Issues #11, #13 and #14 remain open. This document
contains no invented recovery key sequence or flashing recipe. Use a separate
[per-test record](TEST_CHECKLIST.md) for each experiment and follow
[TEST_POLICY.md](TEST_POLICY.md). TX remains out of scope.

## Recovery discovery and official-image validation (#11)

Before any hardware experiment, record the exact original IC-7300 model/region,
installed version, official-image hashes, test-radio identity (the owner’s single IC-7300 is permitted), settings
backup location/hash, tester, instruments, power arrangement, and reviewed stop
conditions. Keep backups and private identifiers outside Git. Establish an
independent way to observe normal receive operation without a route to PTT.

1. Resolve recovery entry, bank-selector persistence, writable regions and failure
   behavior through updater/bootloader evidence and authoritative device
   instructions. Record source and address evidence for each step. If recovery
   entry or the effect of a step is unknown, stop at research.
2. Write the exact official-image-only procedure from that evidence, including
   expected displays, completion criteria and recovery verification. Review this
   initial recovery experiment separately: proven recovery is its outcome, not a
   prerequisite it can claim in advance.
3. In a future authorized session, capture stock boot/version and normal receive
   observations, preserve settings, and exercise only the reviewed official-image
   path. Do not use a modified image, arbitrary downgrade, corrupt image or
   power-interruption test to discover recovery.
4. Record actual recovery entry and completion, returned version, independently
   observable receive behavior and restored settings. Record bank behavior only
   if directly measured; a menu reinstall does not prove unbootable-image recovery.
5. Sign off only the failure classes actually exercised. A recovery route that
   depends on a working application does not satisfy recovery from a failed
   application boot. Such a gap blocks #13.

Stop on any hash/target mismatch, unavailable backup, unexpected prompt, unclear
bank state, loss of observation or abnormal device behavior. Do not improvise
power cycling during a write. Follow the reviewed official failure instructions;
if none apply, end the experiment and seek a supported recovery/service route.

Evidence record: initial/final versions; source hashes; exact steps and times;
expected/actual observations; recovery entry dependencies; settings restoration;
covered and uncovered failure classes; tester outcome. No desktop result can fill
in a physical PASS.

## Visible-only proof (#13)

Prerequisites: proven recovery for the intended failure class, verified packer and
reviewed display-only site, exact target match, reviewed test record and backed-up
settings. None is implied by generation of a candidate file.

1. Review the patch preimage and same-length replacement, decoded diff, compressed
   capacity, integrity report and unchanged protected regions.
2. Record stock boot and receive baseline under a repeatable signal/source and
   configuration. Record the expected diagnostic label and normal UI behavior.
3. In a later approved hardware session, use the established installation path.
   Verify boot completion, diagnostic rendering, controls, normal receive/audio,
   and no unexpected TX indication or behavior. No FT8 audio injection is allowed.
4. Execute the previously proven rollback procedure. Verify stock identification,
   receive baseline and settings restoration; retain the local audit hashes.

Stop if any prerequisite is missing or any behavior diverges. Record PASS only
when boot, receive behavior and rollback are physically demonstrated. A desktop
rendering guess or unchanged RF code is not acceptance evidence.

## Runtime measurement worksheet (#14)

First identify allocator ownership, stack bounds, timer source, task objects and
priorities. Probes must not guess callable APIs or write into apparent unused
memory. Use read-only observation where possible; any instrumentation image needs
the same packer/recovery prerequisites. Bound and measure probe overhead.

Repeat a stock baseline and an instrumented run for: normal receive; receive with
scope and UI activity; receive with SD recording; combined scope/UI/SD load. Use
at least ten minutes per scenario and record configuration and actual duration.
This is an initial observation window, not a worst-case guarantee.

| Measurement | Record | Acceptance / consequence |
| --- | --- | --- |
| Target and probes | Image hash, source revision, task/probe addresses, clock units, probe overhead | Known ownership and repeatable timestamps; otherwise results invalid |
| RAM | Minimum free total and largest contiguous region; allocation failures | At least 393,216 bytes of reservable codec workspace plus separately budgeted adapter/DMA/runtime overhead |
| Stacks | Each task/exception stack bound, observed peak and remaining margin | No overflow; reserve margin based on observed paths and interrupt nesting; unknown bounds remain a blocker |
| Executable storage | Validated executable region, permissions, alignment, target build size | All code/runtime dependencies fit an owned region; padding is not evidence |
| CPU | Busy/idle interval, probe overhead, peak utilization by workload | Publish measured load and remaining budget; do not infer from host clock speed |
| Scheduler | Task priorities, longest scheduling delay, interrupts/preemption and observation method | Report maxima and distribution; identify whether later codec work can be bounded without blocking audio |
| Receive integrity | Audio gaps, buffer overruns, UI/scope responsiveness, SD errors | No regression against stock; any fault blocks integration |

For every row record expected value, actual value with units, evidence location,
uncertainty and PASS / FAIL / NOT MEASURED. Unknowns are not zeros. Keep CPU and
stack feasibility conditional until a target build and realistic scheduling
workload exist. The future decode deadline belongs to Epic 3; this phase reports
a measured budget and limitations, not a live FT8 performance claim.

If the workspace cannot be reserved, storage ownership is unsafe, or normal radio
behavior regresses, publish an infeasibility result with the limiting measurement
and required redesign. Do not manufacture a passing budget by summing fragmented
RAM or interpreting static image gaps as available runtime memory.

## Single-radio inventory and backup coverage

The owner permits work on their only original IC-7300. Read-only host inventory
has identified its CP2102 interface. Following owner confirmation of disabled
USB SEND/keying, two documented status queries succeeded; see
[the physical CI-V read record](../research/radio-readonly.md). This is not flash
readback. Before opening the serial port, confirm USB SEND is OFF and
RTS/DTR keying is disabled, since opening a port can change control-line states.
Record current port mapping afresh; device paths may change after reconnection.
Do not assume region, installed firmware or backup contents from the USB name.

| Required evidence | Current status |
| --- | --- |
| Original-model USB identity and serial mapping | Observed on host; identifiers stay local |
| Physical CI-V status communication | Frequency and operating-mode queries succeeded; raw evidence stays local |
| Region, board revision, fitted flash revision | Not verified |
| Displayed firmware and component versions | Main CPU 1.42, Front CPU 1.01, DSP Program 1.07, DSP Data 1.00, FPGA 1.13; owner photo |
| Settings backup and readable restoration format | Two 8,224-byte files observed on card before update; restore and format not validated |
| Boot/application flash and selector-record readback | No supported access established |
| Calibration/configuration storage locations and backup | Not established |
| Recovery without application boot | Not demonstrated; main CPU debug connector J491 is a documented but unqualified lead |

Prefer a documented bootloader/service recovery mechanism. If unavailable, the
next step is qualified investigation of external recovery access, including exact
part identification, electrical isolation, complete repeated readback and a
restore/readback verification procedure. Opening the radio, attaching a programmer
or performing a restoration needs a concrete board-specific plan. Do not power
an unidentified in-circuit flash interface or improvise pin connections.

No write test is scheduled while these prerequisites remain missing. The normal
SD update path and the two observed application source locations are insufficient
recovery evidence. Offline emulation reports accompany, but cannot replace, a
physical recovery demonstration.

The owner has now completed the ordinary official update; see
[the stock-update record](../research/stock-update.md). This supersedes the prior
unknown installed-version entry, but does not establish failed-application recovery.

The [recovery-access review](../research/recovery-access.md) records the J491
schematic evidence, separate EEPROM coverage, bounded loader findings and an
unsent service inquiry. It supplies no approved hardware attachment procedure.
