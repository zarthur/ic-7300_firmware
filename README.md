# IC-7300 native FT8 research

Offline reverse engineering and a portable FT8 prototype for the original Icom
IC-7300. The intended radio feature is standard FT8 QSOs with operator-enabled
sequencing and no external computer during operation.

This is a research repository, not installable radio firmware. Vendor firmware,
extracted payloads, recordings, dependencies, and build outputs are kept outside
Git. Stock USB status reads have been demonstrated; input-only USB audio capture
is now available for receive validation. Modified-image flashing remains blocked
on recovery and platform evidence.

The project is independent of Icom. Read [the legal and distribution policy](LEGAL.md),
[security policy](SECURITY.md), and [hardware test policy](docs/TEST_POLICY.md)
before contributing or attempting any hardware work.
The initial analysis target and its fail-closed compatibility rules are recorded
in the [supported target matrix](docs/SUPPORTED_TARGETS.md).

Original project material is licensed under the [MIT License](LICENSE). Vendor
and third-party material is not relicensed; see [third-party notices](THIRD_PARTY_NOTICES.md).

## Layout

- `tools/`: acquisition, container analysis, reproducibility, benchmarks
- `prototype/`: portable C sequencer and desktop codec adapters
- `tests/`: synthetic parser fixtures and sequencing/codec validation
- `research/`: provenance, specifications, evidence and measured results
- `ghidra/`: reproducible import and annotation support

## Current results

- Official v1.40, v1.41 and v1.42 acquired and hashed; v1.42 matches the mirror.
- Four MD5-checked sections, LZSS extraction, validated ARM boot/application
  mappings, and byte-identical reconstruction of all three releases.
- Streaming FT8 C codec, selected-caller QSO simulation and cancellation tests.
- Independent WSJT-X interoperability, noise/offset/overlap and recorded-audio
  comparisons. The compact decoder is less sensitive than WSJT-X in this corpus.

Start with [integration findings](research/integration.md),
[container specification](research/container.md), and
[hardware evidence](research/hardware.md). Full generated results live in
`research/firmware-results.json` and `research/codec-results.json`.

## Setup

Requirements: Git, Python 3.9+, a C11 compiler, Make and internet access for initial
acquisition. The basic parser and test runner use only Python's standard library.
Capstone and PyMuPDF are optional analysis/document-inspection dependencies.

```sh
python3 tools/bootstrap.py
python3 tools/acquire.py --verify
make -j4 test
python3 -m venv .venv
.venv/bin/pip install -r requirements-research.txt
```

Bootstrap checks out the exact dependency revision in ignored `third_party/`.
Acquisition uses links from Icom's official release pages; `--verify` checks
tracked SHA-256 values and does not rewrite acquisition metadata. Without that
flag it records a new manifest, so review any provenance changes before commit.

## Firmware analysis

```sh
python3 tools/verify_firmware.py --output artifacts/firmware-results.json
python3 tools/firmware.py analyze artifacts/original/7300_142.dat artifacts/reports/142
python3 tools/firmware.py diff artifacts/original/7300_140.dat artifacts/original/7300_142.dat
python3 tools/firmware.py extract artifacts/original/7300_142.dat artifacts/extracted/142
python3 tools/firmware.py rebuild artifacts/extracted/142 artifacts/rebuilt142.dat
.venv/bin/python tools/trace.py artifacts/extracted/142 artifacts/address-map.json
```

Extraction and reconstruction refuse to overwrite existing output. Reuse the
existing extracted directory for tracing or choose a fresh destination. The
verification command performs temporary extraction and is repeatable.

`rebuild` preserves original compressed bytes and requires the original SHA-256;
it is not a modified-image packer. The two-byte trailer is preserved; its fixed-tag check is recovered for v1.42.
Firmware commands accept only the exact research images in `research/targets.json`;
renaming a file or updating acquisition metadata cannot authorize another image.
Tracing verifies extracted inputs and supports only v1.42's pinned source and
application, because the recorded addresses are version-specific.
Ghidra import instructions and an annotation script are in [ghidra/](ghidra/).
Ghidra was not installed during this phase; its script remains unexecuted.

## Offline FT8

```sh
mkdir -p artifacts/demo
build/ft8_proto generate 'CQ K1ABC FN42' artifacts/demo/260920_120000.wav
build/ft8_proto decode artifacts/demo/260920_120000.wav
build/ft8_proto simulate
python3 tools/validate_codec.py --output artifacts/codec-results.json \
  --jt9 /Applications/wsjtx.app/Contents/MacOS/jt9
```

The prototype accepts mono PCM16 WAV at 12 kHz, up to 15 seconds. Decodes are
JSON lines; signal quality is a sync score, not calibrated SNR. `simulate` uses
example callsigns and report values; it produces no RF. See
[prototype interfaces](prototype/README.md) for supported exchanges and timing.
Set `--jt9` to a separately installed WSJT-X decoder on other systems. No GUI or
sound device is needed. Dependency and license details are in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

### Offline replay of a live receive capture

`tools/compare_receive.py` verifies the capture manifest, continuity/alignment
flags and every exported slot hash before replay. It saves candidate-stage
diagnostics, exact-text matches/misses, WSJT-X signal measurements, executable
hashes and decoder logs in a new local evidence directory. It opens no audio or
serial device. Recordings and message lists must remain under ignored artifacts.

```sh
make -j4 BUILD=artifacts/rx-analysis-build all
.venv/bin/python tools/compare_receive.py --capture artifacts/YOUR_CAPTURE --exe artifacts/rx-analysis-build/ft8_proto --output artifacts/YOUR_REPLAY
```

For an experimental executable, add `--reference artifacts/YOUR_REPLAY/report.json`
and select another new output directory. Add `--require-no-regressions` to fail
when any previously matched per-slot message is lost, even if total counts rise.
Reuse requires the same capture manifest,
slot hashes and reference decoder hash. PASS means replay completed, not decoder
parity. Counts represent unique decoded text per slot; repeated transmissions in
different slots count again. Candidate proximity alone does not establish why a
particular signal was missed. See [the receive study](research/receive-study.md).

## Verification and development

For unattended validation of the **current working tree**, including uncommitted
work, run `make development-check`. This uses `.venv` and the default `full`
profile: all Python tests without skips, C tests, official-image roundtrips,
ASan/UBSan, malformed-WAV checks, repeat-verified controller evidence and the
independent WSJT-X comparison. `make test-synthetic` explicitly selects the
synthetic Python cases plus C and sanitizer checks; it needs neither firmware
nor WSJT-X and clears any inherited firmware-test opt-in.

Both profiles require the pinned research/audio packages and a clean pinned codec
checkout. Full validation additionally requires the existing official images and
WSJT-X. Preflight verifies package versions, actual dependency contents, and full
profile image hashes. It does not install dependencies or download firmware.
Missing prerequisites produce BLOCKED, not a partial PASS.

Every run builds normal and sanitized binaries from scratch in its own ignored
`artifacts/development-*` directory. Logs, benchmark workspaces, detailed firmware
reports and temporary files also stay there. Atomic `report.json` records source
fingerprints before/after, dependency and executable hashes, compiler versions,
test counts/skips, terminal outcomes and unexecuted stages. Each step has a
timeout; failure, interruption or changed source prevents PASS. No radio I/O or
firmware write occurs. Use `.venv/bin/python tools/development_check.py --help`
for profile, decoder/output paths and timeout configuration. Custom evidence
directories must be outside tracked source (normally under `artifacts/`) and
contain no whitespace because Make cannot handle those build paths.
Benchmark success does not imply sensitivity parity. The synthetic profile is
ready for a future CI job; no hosted workflow has been activated.

```sh
make -j4 test
make BUILD=build/sanitize CFLAGS='-std=c11 -D_DEFAULT_SOURCE -D_DARWIN_C_SOURCE -O1 -g -Wall -Wextra -fsanitize=address,undefined -fno-omit-frame-pointer' test
python3 tools/reproduce.py --output artifacts/reproduction.json
git status --short
```

Reproduction tests the committed HEAD in an isolated temporary clone, fetching
the pinned dependency and official archives again, and checks that tracked state
remains clean. It does not test uncommitted changes. Interoperability benchmarks
are separate because they require an installed WSJT-X executable. To refresh
tracked result snapshots, omit `--output` on the verification/benchmark tools
and review the changes. Reports record source commit and dirty-worktree status.

Keep focused commits or use topic branches for experiments. The GitHub repository
is `zarthur/ic-7300_firmware`. Never add original/extracted firmware,
audio recordings, build output or Ghidra databases to Git; store reproducible
instructions, hashes and annotations instead.

## Feasibility boundary

The ARM application is the preferred investigation target, with approximately
231 KiB measured codec heap plus stack/context requirements. Available RAM,
audio buffer ownership, scheduling deadlines and acceptance of modified images
remain unproven. The next milestone is recovery/updater research and resolving
the recorder/playback paths, followed by receive-only hardware measurements.

## Epic 1 desktop platform work

See [the next-work plan](docs/NEXT_STEPS.md) and
[automated results and manual steps](docs/RECEIVE_VALIDATION.md) for the current
receive-only work session.

[Platform evidence and packing status](research/platform.md) records updater and
runtime candidates and remaining blockers. Packing/recompression results in the research notes are historical local work; that tooling is not published pending distribution review.
[Recovery and measurement procedures](docs/PLATFORM_VALIDATION.md) prepare later
hardware validation; no physical acceptance is claimed.

```sh
.venv/bin/python tools/platform_evidence.py artifacts/original/7300_142.dat --output artifacts/platform-evidence.json
```

Custom-image packing is not distributed. The existing `rebuild` command performs
only byte-identical reconstruction of a supported official image.

Original-routine emulation and desktop validation:

```sh
.venv/bin/python tools/emulate_platform.py artifacts/original/7300_142.dat --output artifacts/emulation-results.json
IC7300_TEST_IMAGE=artifacts/original/7300_142.dat .venv/bin/python -m unittest discover -s tests -v
```

See [updater execution findings](research/updater-emulation.md) for the recovered
fixed trailer tag, bank selector, decoder lookahead, modeled failures and remaining
hardware blockers. Emulation runs entirely offline and does not open the radio.

For bounded original flash-controller execution and a deterministic repeat check:

```sh
.venv/bin/python tools/controller.py artifacts/original/7300_142.dat --output artifacts/controller-results.json --verify-repeat
```

This executes erase/program/status-polling instructions with explicit MMIO
responses. Stuck polling is reported as a harness limit, and unresolved runtime
helpers remain visible. It does not establish physical recovery or acceptance.


## Offline cancellation research

The [bounded cancellation study](research/cancellation-study.md) fits decoded
waveforms to saved audio and attempts a second decode after subtracting accepted
fits. It preserves original-pass messages and records rejection reasons, limits,
gains/losses and host memory/time. It is an opt-in desktop experiment whose sample
buffers exceed the current embedded workspace target; receive defaults remain
unchanged. No device playback or transmit path is used.

`tools/study_cancellation.py` creates synthetic fixtures, freezes a fresh candidate,
evaluates saved captures and verifies repeated behavior. The study documents exact
commands, evidence locations and holdout handling. `tools/capture_batch.py` provides
two bounded, explicitly requested input-only recordings with one retry per role;
it is not invoked by either development-check profile.
