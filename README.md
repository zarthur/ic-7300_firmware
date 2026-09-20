# IC-7300 native FT8 research

Offline reverse engineering and a portable FT8 prototype for the original Icom
IC-7300. The intended radio feature is standard FT8 QSOs with operator-enabled
sequencing and no external computer during operation.

This is a research repository, not installable radio firmware. Vendor firmware,
extracted payloads, recordings, dependencies, and build outputs are kept outside
Git. No radio access or flashing is part of this phase.

## Layout

- `tools/`: acquisition, container analysis, reproducibility, benchmarks
- `prototype/`: portable C sequencer and desktop codec adapters
- `tests/`: synthetic parser fixtures and sequencing/codec validation
- `research/`: provenance, specifications, evidence and measured results
- `ghidra/`: reproducible import and annotation support

Setup and results will be documented as implementation proceeds.
