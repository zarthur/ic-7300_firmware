# Updater execution evidence and remaining blockers

Publication note (2026-09-27): packing and recompression results below are
historical local research. Packing/recompression tooling is not distributed in
this branch pending the project distribution review. Reproduction commands
here cover read-only analysis and emulation. Generated instruction/CFG reports
such as `platform-evidence.json` remain local under `artifacts/`. Checked-in
emulation summaries retain their historical source/tool hashes; they are not
test results for the current revision.

Historical desktop record: later stock-version and physical CI-V observations are
recorded in [stock-update.md](stock-update.md) and [radio-readonly.md](radio-readonly.md).
The recovery investigation is in [recovery-access.md](recovery-access.md).

This follow-up advances #10, #12 and #14, but does not close Epic 1. All execution
below is local. No serial port was opened, no radio setting was changed and no
image was generated or flashed. The radio's CP2102 USB identity was observed on
the host at `/dev/cu.usbserial-<radio>`; private device identifiers are not retained
in this repository. At the time of this initial record, displayed firmware,
region and safe serial-control settings remained unverified; later stock-version
and CI-V observations are linked above and do not qualify recovery.

## Reproduction and trust boundary

```sh
.venv/bin/pip install -r requirements-research.txt
.venv/bin/python tools/platform_evidence.py artifacts/original/7300_142.dat --output artifacts/platform-evidence-v2.json
.venv/bin/python tools/emulate_platform.py artifacts/original/7300_142.dat --output artifacts/emulation-results.json
IC7300_TEST_IMAGE=artifacts/original/7300_142.dat .venv/bin/python -m unittest discover -s tests -v
```

Unicorn is pinned to 2.1.4. Both commands validate the exact 1.42 source hash.
Firmware images remain user-supplied. The control-flow walker follows direct
branches within reviewed routine bounds, explores both conditional paths, stops
at returns, and reports unresolved indirect/external edges. It does not decode
unreachable literal pools as executable fallthrough or infer callee effects.

The emulator runs original instructions for the decompressor, marker selector,
magic/trailer checker and transfer loop. Transfer callees for file I/O, status
translation, byte comparison, MD5, controller transitions and flash mutation are
explicit models. Memory mapping is local and has no device access. Unmapped
accesses, unmodeled execution in the transfer/selector/checker and instruction or
30-second execution limits stop the run. Reports distinguish executed code from
models; they are not a full-machine boot test or proof of device safety.

## Findings

### Fixed envelope tag

The checker at 0x200247e4 compares four bytes against little-endian 0x55667733.
When given a non-null trailer pointer it also compares two bytes against 37 65.
The caller at 0x200253f4 reads the first four bytes, checks component identifiers,
seeks two bytes before EOF, reads the trailer and calls the checker again.
Valid magic/trailer pass in emulation; altered magic and trailer fail. The fixed
tag is not a computed checksum in this routine. Component identifier matching,
complete length constraints and every caller failure path remain unfinished.

### Persistent bank selection

Original loader 0x20004374 compares the 16-byte record at 0x187f0000 with a
compiled-in marker. Exact equality selects compressed source 0x18400004;
erased, zero and one-bit-modified markers select 0x18010004. The test intercepts
the decompressor entry and supplies synthetic length words; it does not boot
an application. There is no demonstrated corrupt-bank fallback in this path.

The application initialization near 0x20062ca4 compares the same marker and stores
its equality-derived state at 0x20390398. That byte controls the alternate transfer
destination. Routine 0x20024d60 erases the block at offset 0x7f0000 and programs a
16-byte record. Its zero-argument template differs from the loader's matching
marker; the other branch copies caller-supplied bytes. Full activation ordering,
caller buffer provenance and behavior after interrupted record writes remain
unresolved. Do not interpret two banks as proven rollback.

### Transfer loop

The original 0x20024db8 routine processes 64 KiB chunks. It pads a short final
chunk, reads the requested bytes, checks the read count/status, updates MD5,
checks cancellation and compares a full chunk with mapped flash. Equal chunks
skip programming. Changed chunks call controller transition, erase, program and
controller restoration routines, then set the changed flag. Instruction evidence
includes erase command value 0xd80000 in 0x20024bb8 and program command value
0x20000 in 0x20024a60; detailed controller/status semantics still need validation.

Emulation covers changed/unchanged data, short reads, read errors, cancellation,
and interruption before erase, after erase and after programming. Short reads,
read errors and cancellation return -19 without erase/program events. A simulated
programming failure can leave mismatched flash while this caller still returns
zero and sets the changed flag: it does not check the modeled programmer return.
This is a limitation of the caller under that explicit fault model, not proof
that real hardware silently fails; inspect real completion/error behavior next.
The harness does not yet cover every persistent transition in the whole updater.

### Original-loader recompression validation

The full 3,738,392-byte application is decoded identically by the host and the
original ARM decompressor. The latter advances the source by 1,676,646 bytes,
one byte beyond the host's logical consumed length of 1,676,645.

The optimized deterministic encoder indexes three-byte history prefixes while
retaining longest-match/lowest-ring-index selection. Two full encodings agree:
1,460,358 bytes, SHA-256
`f709a8dc21503d19bc2b5bc4eec8df31541968047dcacd94ca92ea0835cf26c3`.
The original loader reproduces the application from this stream, advancing three
bytes into explicitly supplied synthetic lookahead. Preserved real trailing bytes
and bounds must therefore be checked before any packer policy can be enabled.
Smaller recompression is not proof of writable capacity or custom-image acceptance.

### Runtime ownership leads

The initialization table at 0x20360aac has three 16-byte entries. Thumb routine
0x20186478 copies words; 0x20186488 clears words. The table describes:

| Destination | Length | Operation |
| --- | ---: | --- |
| 0x20390000 | 0xb18 | Copy from 0x20360b54 |
| 0x20390b18 | 0x24c448 | Zero-fill |
| 0x2080d000 | 0x3fc00 | Zero-fill |

These are occupied initialized/zeroed ranges, not free RAM. Heap ownership, task
objects, priorities, stack high-water marks and scheduling measurements remain
open. No instrumentation image is authorized by these static observations.

## Primary documentation and hardware boundary

The manufacturer-authored [EN25Q64 Rev. J datasheet, mirrored by BDTIC](https://www.bdtic.com/DataSheet/EON/EN25Q64.pdf)
describes 8 MiB, 256-byte programming pages, 4 KiB sectors and 64 KiB blocks.
These support the model geometry but do not establish the fitted chip revision,
protection state or board-level programming method. A differently suffixed flash
part must not be substituted without checking its datasheet.

[Icom's official 1.42 instructions](https://www.icomjapan.com/support/firmware_driver/4102/)
describe the normal SD/menu update path. That requires a functioning application;
it does not establish failed-application recovery. Independent recovery remains
unproven, and modified-image testing is blocked on the owner's single radio.

## Remaining implementation gates

- #10: header and selected-payload validation plus main-caller activation ordering
  are now exercised offline. Physical flash completion/errors, DSP/FPGA update
  paths and actual interrupted-update outcomes remain unresolved.
- #11: qualify actual hardware and establish backup coverage plus a physically
  demonstrated application-independent restoration path. No key sequence or
  programmer wiring is guessed.
- #12: prove stream boundaries including loader lookahead and a display-only
  patch region. Real-image output remains refused. Staged exclusive output/audit
  publication is now implemented and tested for synthetic outputs and failures.
- #13: verify all consumers of a proposed display string; then review the exact
  candidate and recovery evidence before any modified boot.
- #14: resolve runtime interfaces before probes; perform the prescribed physical
  baseline/load measurements only after recovery and instrumentation prerequisites.

## Verification record — 2026-09-20

- Phase: desktop; TX authorization: none; no serial opening or hardware writes.
- All 34 Python tests passed with pinned research dependencies and the explicit
  `IC7300_TEST_IMAGE` opt-in. System-Python `make -j4 test` passed its available
  tests (13 optional research tests skipped), C QSO/codec tests and simulation.
- All three official releases passed digests, decompression and byte-identical
  reconstruction; report: `artifacts/epic1-followup-firmware-results.json`.
- Full original-loader and deterministic recompression runs passed. The tracked
  `emulation-results.json` records outcomes and matching tool hashes; it contains
  no firmware bytes. `platform-evidence.json` contains updated control-flow and
  initialization-table evidence. `git diff --check` passed.
- Source revision is recorded with dirty status: pre-existing Epic 0 and Epic 1
  changes were preserved. No issue was closed and no firmware image was emitted.

## Additional updater stages and observed stock update

The owner subsequently completed the normal official 1.41 → 1.42 update; see
[stock-update.md](stock-update.md). No modified firmware has been tested.

The new offline command executes more of the original v1.42 code:

```sh
.venv/bin/python tools/updater_stages.py artifacts/original/7300_142.dat --output artifacts/updater-stages.json
```

`research/updater-stages.json` records code hashes, modeled boundaries and results.
It executes v1.42 routines against the official corpus; it does not assert that
older firmware executes identical validation logic.

### Recovered validation specification

The original precheck at 0x200253f4 verifies magic, reads three four-byte component
identifiers, checks each character against its bitmap, compares each identifier
with a modeled installed identifier, then seeks to and checks the trailer.
The allowed characters are period and decimal digits; this predicate does not
require a specific dot position. A different valid identifier sets a component
change flag, rather than failing the precheck. These header identifiers are not
the public Main CPU version. The installed identifiers in the harness are explicit
inputs, not measurements of the radio's RAM. Short reads, invalid characters,
wrong magic/trailer and a modeled seek failure all reject and close the file.

The original 0x20025650 payload-validation caller reads declared lengths and
validates the main payload digest. It reads/hashes/compares the other three payloads
only when their corresponding component flags are enabled; otherwise it seeks
past each payload and digest. Tests corrupt each payload independently and compare
outcomes with an independently written specification. The host parser remains
stricter and validates all four digests regardless of device selection flags.
The payload phase alone does not reject a changed trailer; the earlier precheck
is necessary. MD5 primitives and filesystem/status APIs remain modeled.

### Main-update caller ordering

The original main-update caller at 0x20025ae4 rejects a main stored length greater
than 0x380000. It reads the expected main digest and a 16-byte record at DAT offset
0x4f2c (main offset 0x4f00), then transfers the first 64 KiB to flash offset zero
and the remainder to 0x10000 or 0x400000 according to the current selector.
The source record matches the loader's compiled-in marker.

With modeled unchanged boot bytes, main digest comparison precedes the activation
call at 0x200260f0; digest mismatch stops before activation. With modeled changed
boot bytes, the earlier call at 0x20025e2c precedes finalization/comparison of the
main digest, and remains in the trace even when that final comparison fails.
Both branches are tested for both selectors. This is evidence about original
caller ordering under explicit models, not a claim that a physical update will
fail. The harness disables DSP/FPGA component updates and does not establish their
state machines, controller behavior, readback guarantees or overall power-loss
safety. Transfer errors also stop before activation in the covered cases.

### Persistent-record interruptions

The original 0x20024d60 record writer is executed separately, with flash erase and
program operations modeled. Selector zero writes its compiled-in nonmatching
record; selector one copies the matching marker from the source image. The model
then runs the original loader selector against the result.

Before erase, selection remains unchanged. After erase and after every modeled
0–15-byte programmed prefix, selection is the first bank (0x18010004). Only the
complete matching record selects the second bank (0x18400004). The second-bank
case thus has an asymmetric transition through the first-bank selection. A real
interrupted flash program need not produce a prefix; these tests deliberately do
not equate the prefix fault model with physical power-loss behavior. Ownership of
the rest of the erased 64 KiB record block also remains unresolved.

### Conservative recompression check

The original decoder is now additionally tested with the recompressed application
overlaid onto the original compressed span while preserving its suffix bytes.
The source mapping ends at the original logical consumed length; the new stream
plus three lookahead bytes fits within that span. The resulting application must
match exactly. This demonstrates an offline option that needs no additional
compressed storage for the unchanged application. Every future patch still needs
its own bounded decoding check and verified display-only region; it does not
open the production packing gate.

### Verification after the additional stages

All 41 Python tests passed with the pinned dependencies and the explicit firmware
opt-in, including independent header/payload specifications, both activation
branches and every modeled record prefix. `make -j4 test` also passed its available
Python tests, C suites and simulation; its system Python skipped 20 optional
research tests. The v1.42 routines accepted all three official containers in the
corpus tests. The retained-suffix decoder test produced the exact application and
advanced 1,460,360 bytes within the 1,676,645-byte mapped original consumed span.
All three generated evidence reports have tool hashes matching the current source.
`git diff --check` passed. This remains offline evidence, not recovery acceptance.

## Controller follow-up — 2026-09-25

Run the following against the pinned official 1.42 source, or use the full
`make development-check` profile. Generated reports and disassembly stay ignored;
no firmware bytes or instruction listings are added to the repository.

```sh
.venv/bin/python tools/controller.py artifacts/original/7300_142.dat --output artifacts/controller-results.json --verify-repeat
```

The report includes exact source/tool hashes, Capstone/Unicorn versions, bounded
ARM control-flow records, register events, execution counts, stopping PCs,
modeled dependencies and caller results. `--verify-repeat` regenerates and
compares the complete report before adding `repeat_identical: true`; mismatches
fail the command. Event lists retain the first 2,048 events with an explicit
truncation flag, total counts and a digest of the complete event stream.

### Executed code and register evidence

| Original ARM entry | Bounded observation |
| --- | --- |
| `0x20024bb8` erase | Requests write enable, waits for the status condition, issues command sequence including `0xd8`, and advances destination by `0x10000` through the inclusive end argument |
| `0x20024a60` program | Skips leading all-ones words, transfers four-byte words, splits transactions at 256-byte boundaries, then polls status |
| `0x2002497c` wait helper | Reads status through controller transactions until masked bit 1 is set |
| `0x20024904` wait helper | Reads status through controller transactions until masked bit 0 is clear |
| `0x20360b44` register helper | Original load/mask/shift instructions execute; not replaced with a return-value stub |
| `0x20024cd0` enter command mode | Executes register changes with runtime helper `0x200b9008` explicitly modeled as returning |
| `0x20024850` restore mapping | Executes register changes with runtime helper `0x200b9098` explicitly modeled as returning |

The reviewed instructions use the register base `0x3fefa000`, load transfer status
at offset `0x48`, and load command-return data at `0x38`. Every reviewed wait for
transfer status tests bit 0 through the original register helper. The harness
allows only observed four-byte register accesses; unknown addresses/widths stop
execution. Register names and command interpretations in the model describe
stimulus assumptions, not physically qualified peripheral semantics.

Immediate and delayed completion return in the tested erase/program scenarios.
A permanently absent transfer-complete bit, busy bit remaining set, or absent
write-enable bit causes continued polling until the instruction budget stops the
emulator. These are LIMIT outcomes, not successful returns or a recovered firmware
timeout. No separate error-return branch was found in the reviewed routines.
Injected upper status bits are masked away on these paths; they are not labeled
as real device error flags. The erase return register contains loop arithmetic
(the tested end argument plus one), so it must not be treated as a conventional
zero/nonzero success code.

The unmodeled transition runs stop precisely at `0x200b9008` and `0x200b9098`.
Static inspection identifies further calls and cache/TLB-related instructions in
those helper families. Their runtime effects, mapping state and synchronization
remain unqualified. The modeled transition runs establish only the surrounding
register-control sequence, conditional on those helpers returning.

### Caller composition and its limits

The transfer and activation harnesses can consume separately executed controller
results using `controller_scenario`. Results are matched against the caller's
exact destination/range and program-payload hash. This avoids nested Unicorn
execution from inside a hook, which was observed to stop the outer emulator
prematurely. It is a composition of independently executed routines, not a
shared-state controller or full-machine simulation.

With immediate responses, the original callers reach restoration and their
ordinary return. With stuck responses, execution stops at the unresolved wait;
subsequent programming/restoration and normal return are not reached. The report
sets final flash equality/hash or selector outcome to unknown for these stalls.
It does not infer that flash remained unchanged or that cleanup ran. Successful
caller flash mutations are still explicit models, not proof of physical writes,
readback, or error recovery. File operations, MD5, memory helpers and other prior
caller models remain listed in the existing harnesses.

### Selector-block search

The bounded scan records aligned words in the loader/application whose values
fall within the selector's 64 KiB offset or mapped-address interval, plus immediate
references in the reviewed ARM routines. It finds 48 aligned-word candidates;
several are likely unrelated data or instruction encodings, so this is not a
complete access inventory.

One useful candidate is the application literal at `0x20062d34`, holding
`0x187f0000`. The static window `0x20062ca4..0x20062ccc` passes this address and a
16-byte marker to the comparator, maps equality to zero and inequality to one,
and stores that byte at `0x20390398`. The compared marker matches the loader's
marker. This links a conditional startup path to the updater selector variable;
preceding initialization calls and the entry condition are not executed here.

The known record writer still requests an entire 64 KiB erase at `0x7f0000`
followed by a 16-byte program. Ownership of the remainder of that block, computed
or indirect references, DSP/FPGA updates, physical completion/error behavior and
application-independent recovery remain unresolved. Real-image packing remains
disabled. Older tracked JSON snapshots are historical and are not silently
refreshed when harness code changes; use each new run's source hashes and report.

## Mapping/cache helper follow-up — 2026-09-27

The same offline controller-report command now includes `runtime_helper_evidence`
from `tools/runtime_helpers.py`. This executes both original ARM helper entries,
their descriptor builders (`0x200b8a0c`, `0x200b8804`), section-table writer
(`0x200b91e0`), cache traversal (`0x200052dc`), and the enter path's external
controller wait (`0x200b92d0`) and synchronization write (`0x200b9260`).
All instruction windows are bounded. RAM starts with the official image and zero
scratch/table storage; startup initialization is not simulated. Unknown writes,
MMIO and execution targets stop the run. The parent controller/transfer harnesses
retain their explicitly listed helper-return substitutions; these new runs are
separate evidence, not a coherent full-machine integration.

**Static observations confirmed by original-instruction execution:** the helpers
build attribute words at `0x203907a8` (enter) or `0x20390794` (restore), then write
64 consecutive descriptors at `0x20000600..0x200006fc`. Their encoded section
addresses advance in 1 MiB units from `0x18000000` through `0x1bf00000`. The tested
attribute bits are `0x85016` and `0x8dc06`, respectively. These are CPU memory-table
writes, not observed flash writes. No MMU translation is enabled by the harness.

Both strict runs stop at `0x200052e0`, before the CP15 CLIDR read. This is a precise
physical dependency: the cache traversal needs geometry from the CPU. Optional
stimulus runs supply either no data cache or one level with one set and one way.
All reviewed coprocessor writes and barriers are explicitly intercepted and
recorded as **modeled maintenance with no simulated physical effects**. Unicorn's
ability to step past such instructions is not treated as cache/TLB evidence.
The one-set/way stimulus exercises the clean branch with argument 1 and the
invalidate branch with argument 0 on the enter path; restoration uses argument 1.
These synthetic dimensions are not a claim about the radio's CPU.

With cache stimuli but no external-controller response, enter stops at
`0x200b92d4`, reading `0x3ffff104`. The original code chooses an eight- or
sixteen-bit mask from bit 16, writes `0xff` or `0xffff` to `0x3ffff7fc`, and polls
that same address until it reads zero. Scripted immediate and two-read delayed
responses reach the synchronization write of zero to `0x3ffff730` and return.
Persistent nonzero status exhausts the instruction budget in the polling loop;
it does not reach synchronization or the subsequent invalidation sequence.
This is a harness LIMIT, not a firmware error return or timeout. Register roles
are inferred from this sequence; peripheral identity and physical behavior remain
unqualified. Restoration has no such external-controller wait in its reviewed
path and returns only under the explicit maintenance substitutions.

The evidence narrows the earlier entry-point boundaries without resolving cache
coherency, actual table activation, peripheral completion, or physical recovery.
It also does not establish selector-block ownership or DSP/FPGA behavior. Tests
check the independently specified descriptor progression, both mask branches,
clean/invalidate call modes, persistent polling without cleanup, and rejection of
an unreviewed memory-write target. Report repeat comparison includes these runs.

## Bounded selector candidate follow-up

[Five candidate words have a conditional instruction interpretation](selector-candidates.md).
Fifteen one-instruction trials match register-only effects; mode-qualified runtime
reachability and complete selector-block ownership remain unresolved.

## Exact loader byte bounds

The desktop loader harness now checks source reads and output reads/writes
against their exact byte intervals, including accesses crossing an interval end.
Page-aligned mappings alone left prefix input padding and final output padding
accessible. Synthetic ARM regressions cover these cases and a valid one-byte
copy. Reports record the largest observed access end separately from the final
source register; a register advance is not a measurement of all memory accesses.
Every candidate still needs its own original-loader decode with its preserved
suffix and bounded source span. These checks do not model physical memory/cache
behavior or authorize candidate installation.
