# Epic 1 desktop platform evidence

Publication note (2026-09-27): packing and recompression results below are
historical local research. Packing/recompression tooling is not distributed in
this branch pending the project distribution review. Reproduction commands
here cover read-only analysis and emulation. Generated instruction/CFG reports
such as `platform-evidence.json` remain local under `artifacts/`. Checked-in
emulation summaries retain their historical source/tool hashes; they are not
test results for the current revision.

## Status and reproduction

This implements the desktop portion of issues #10–#14. No modified-image
acceptance, physical recovery, safe patch site or runtime headroom is established.
The follow-up now executes original loader, envelope-check and transfer routines
in an isolated emulator; see [the follow-up findings](updater-emulation.md).
All five issues retain unresolved acceptance criteria; Epic 1 is not complete.
The later [controller follow-up](updater-emulation.md#controller-follow-up--2026-09-25)
executes lower-level erase/program polling code with explicit register models and
identifies a conditional startup source for the selector byte. The dated tables
below describe earlier evidence, not the complete current findings.

Use the existing pinned Capstone environment and user-acquired images:

```sh
.venv/bin/python tools/platform_evidence.py artifacts/original/7300_142.dat --output artifacts/platform-evidence.json
python3 tools/verify_firmware.py --output artifacts/epic1-firmware-results.json
.venv/bin/python -m unittest discover -s tests -p 'test_platform*.py' -v
make -j4 test
```

`platform-evidence.json` records source/application hashes, source revision and
dirty state, Python/Capstone versions, code windows, branch targets, explicit ISA
states, literal references and runtime markers. The tracked snapshot contains
addresses and observations, not code bytes or full disassembly. Windows are
bounded linear observations, not recovered functions or proof of reachability.
Unknown indirect targets remain unknown; only adjacent literal loads are resolved
as candidates. Immediate BLX switches ISA; register BLX uses the target low bit.

## Updater findings (#10)

All addresses here refer to pinned 1.42. The container specification remains in
[container.md](container.md). Container-level verification covers pinned 1.40,
1.41 and 1.42; it does not transplant these addresses to older versions.

| Topic | Evidence | Interpretation and remaining work |
| --- | --- | --- |
| Container header | Exact coverage by four payloads and MD5 fields in all three images | Host parser validates magic/lengths; full device-side header acceptance remains unresolved |
| Integrity | Calls at 0x2002580c, 0x20025930, 0x20025d94, 0x20026040 reach MD5 init 0x2003c860 | Observed MD5 is not proof of authenticity or complete acceptance semantics |
| Final comparison | 0x20026050/58 call MD5 update/finalize candidates; 0x20026068 BLX reaches Thumb 0x2017c81e | Inspect comparator and every rejection/cleanup path before enabling packing |
| Transfer sequence | 0x20025db8 calls 0x20024db8 with destination argument zero and length 0x10000; 0x20025e08 calls it again with a selected destination | Static call order observed; physical erase/program/readback effects still unresolved |
| Destination selector | Literal at 0x200264a4 points to byte 0x20390398; branch selects 0x400000 or 0x10000 | Find all writers and persistent source of selector; do not assume inactive-bank updates |
| Loader selection | Literal loads at 0x200043a4/ac resolve to 0x18010000 and 0x18400000 | Corroborates two source locations, not automatic fallback or recoverability |
| Transfer candidate | 0x20024db8 divides work into 0x10000 chunks, checks returned counts, updates MD5 | Trace lower-level callees for erase/program ordering, watchdog handling and persistence |
| Failure branches | Nonzero results at 0x20025dd4 and 0x20025e14 branch to 0x20026108 | Error propagation observed; atomicity, cleanup and bootability after failure unknown |
| Trailer | Constant 37 65 in all three official images | v1.42 helper 0x200247e4 checks fixed tag 37 65; full acceptance remains incomplete |
| Compressed extent | 1.42 decoder consumes 1,676,645 bytes after the length word | Consumption is not capacity; fonts and padding are not free space |

Next research steps are to recover the lower-level transfer routines, trace all
writes to the selector, resolve header/trailer reads and rejection paths, and
connect loader selection to persistent state. Issue #10 remains open until those
findings are reproducible, rather than treating a successful host parse as proof.

## Local packing (#12)

`python3 tools/firmware.py pack BASE PATCH OUTPUT` is a separate, fail-closed
command. `rebuild` remains lossless. PATCH is JSON with exactly `base_sha256` and
`edits`; each edit contains decoded-application-relative integer `offset`,
`expected_hex`, and `replacement_hex`. Replacements must have equal nonzero
length. There is no force flag, external policy override or self-approval field.

The production gate currently rejects every real output: acceptance semantics,
compressed capacity and reviewed application regions remain unresolved. Merely
changing acquisition metadata or a patch document cannot enable it. No real
patch description is supplied because there is no verified display-only site.

Internal synthetic-tested primitives implement greedy longest-match LZSS with
lowest ring-index tie breaking, initialized history and overlapping copies.
They enforce stream bounds, exact preimages, approved intervals, non-overlap and
capacity. Packing retains header, decoded length, unused stream bytes, boot,
fonts, other payloads and trailer; it updates only the compressed bytes and main
MD5. Reparse/decompression verify the resulting application. Audits contain base,
output and application hashes, compressed size/capacity and half-open changed
file-offset ranges. This mechanism does not establish a real-image layout policy.

Future enabling work must add a code-reviewed, exact-base policy with proven
regions and stream bounds and prove all unresolved acceptance fields. Exclusive
output/audit publication and ordinary-failure cleanup now have synthetic tests,
but the real-image policy still refuses output.

## Visible proof (#13)

The existing Firmware Update and other UI string references are only candidates.
No display-only site has a verified renderer, consumer set and length semantics;
therefore no replacement bytes or custom image are provided. Before selecting a
site, trace all readers, establish that the value is not used for compatibility
or control decisions, and verify fixed-length rendering and terminator behavior.
Then use an equal-length ASCII diagnostic label and exact preimage/hash checks.
Do not alter the real compatibility/version identifier just because it is visible.

The physical checklist is in [the platform validation procedure](../docs/PLATFORM_VALIDATION.md).

## Runtime candidates (#14)

Startup 0x20005064 loads 0x205dcf60 and assigns banked stack pointers while
switching CPU modes. This is an initialization observation, not a measured stack
limit or free-memory boundary. Calls at 0x200050a4/a8 reach 0x200b8d2c and
0x2002b878. Adjacent literal loads identify candidate targets 0x200b94e4 and
0x20005290; the former branches to 0x200b8690.

0x20005290 loads 0x205dcc60 and calls Thumb 0x2017ccf8. That routine iterates a
table in 16-byte steps and makes indirect calls, a memory-initialization lead.
Do not overwrite the table or assume entries are unused RAM. Subsequent startup
calls reach 0x20186d2c, 0x20187044 and 0x20186d58. SVC and CPU-mode checks in these
windows are runtime-service leads; allocator, task-create, priority and scheduler
interfaces have not been positively identified. Trace service dispatch and object
layout before proposing probes. No target instrumentation is emitted yet.

## Desktop verification record

- Date: 2026-09-20. Tester: automated desktop run. Revision: 1ab637b plus
  pre-existing Epic 0 and new Epic 1 working-tree changes; dirty. Exact script
  hashes and image hashes are in `platform-evidence.json`.
- Phase: desktop, synthetic packing and user-acquired official-image inspection.
  TX authorized: no. Hardware, recovery, operator and instrument fields: N/A.
- Expected: deterministic synthetic packing with protected bytes preserved;
  unknown/unsupported/unresolved real packing rejected without output; all
  official images reconstruct exactly. Any mismatch stops progression.
- Results: `make -j4 test` passed C QSO/codec tests and simulation; its system
  Python run passed 19 tests and skipped four optional Capstone tests.
  `.venv/bin/python -m unittest discover -s tests -v` passed all 23 Python tests,
  including those four Capstone tests. `git diff --check` passed.
- `verify_firmware.py` verified all payload digests, decompression and identical
  reconstruction for 1.40/1.41/1.42. Local evidence:
  `artifacts/epic1-firmware-results.json`.
- Direct CLI checks rejected official 1.40/1.41 as non-development packing bases
  and 1.42 for unresolved gates. No image or audit output was created.
- Outcome: PASS for implemented desktop behavior. Recovery, updater acceptance,
  patch-region verification and physical resource measurements remain pending.
