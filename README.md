# IC-7300 native FT8 research

Offline reverse engineering and a portable FT8 prototype for the original Icom
IC-7300. The intended radio feature is standard FT8 QSOs with operator-enabled
sequencing and no external computer during operation.

This is a research repository, not installable radio firmware. Vendor firmware,
extracted payloads, recordings, dependencies, and build outputs are kept outside
Git. No radio access or flashing is part of this phase.

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
it is not a modified-image packer. The unknown two-byte trailer is preserved.
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

## Verification and development

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

Keep focused commits on the local `main` repository or use topic branches for
experiments. No remote has been configured. Never add original/extracted firmware,
audio recordings, build output or Ghidra databases to Git; store reproducible
instructions, hashes and annotations instead.

## Feasibility boundary

The ARM application is the preferred investigation target, with approximately
231 KiB measured codec heap plus stack/context requirements. Available RAM,
audio buffer ownership, scheduling deadlines and acceptance of modified images
remain unproven. The next milestone is recovery/updater research and resolving
the recorder/playback paths, followed by receive-only hardware measurements.
