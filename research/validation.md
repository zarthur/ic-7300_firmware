# Validation record

This table is the initial desktop snapshot. Later stock update/CI-V observations
and receive-capture attempts are recorded separately; it is not the current test
count or hardware status. Current unattended verification uses
`make test-synthetic` and `make development-check`, saving each run's counts,
source fingerprints, dependency checks and terminal results under ignored
`artifacts/development-*/report.json`. See the
[controller follow-up](updater-emulation.md#controller-follow-up--2026-09-25).

The tracked JSON snapshots include the generating source revision. A dirty flag
may reflect result files being refreshed; inspect the commit alongside the
executable hash. `reproduction.json` records a clean committed checkout test.

| Check | Result |
|---|---|
| Official corpus | All three image SHA-256 values match acquisition manifest |
| Container integrity | Four payload MD5 checks per release pass |
| LZSS | All four decoded outputs generated per release with bounded input/output |
| Reconstruction | All three DAT files reconstructed byte-identically |
| Python tests | Seven tests pass, including malformed/truncated WAV and container cases |
| C tests | Codec streaming/continuity/cancellation and QSO state/slot/retry tests pass |
| Sanitizers | AddressSanitizer and UndefinedBehaviorSanitizer pass the same local suite |
| Codec comparisons | 21 scenarios, 16 required cases pass; five characterization cases retain limitations |
| Independent decoder | Installed WSJT-X v3.0.2 jt9 decodes all six generated standard messages |
| Clean checkout | Pinned dependency fetch, fresh official acquisition, build/tests, corpus roundtrip pass |
| Git exclusions | Firmware, derived binaries, WAVs, dependencies, environments and build outputs ignored |
| Ghidra | Import script supplied; not executed because Ghidra is not installed |
| Radio | No hardware execution, flashing or RF testing |

The five characterization cases are -15 dB, -20 dB and three recorded files.
The -15 dB signal decoded; -20 dB did not in the compact decoder. Recorded samples
show lower counts than WSJT-X. Empty expected lists on recorded cases do not mean
decoder parity passed; compare the actual message lists in codec-results.json.
Noise-only cases explicitly require zero decodes in both implementations.

Sanitizer command:

```sh
make BUILD=build/sanitize CFLAGS='-std=c11 -D_DEFAULT_SOURCE -D_DARWIN_C_SOURCE -O1 -g -Wall -Wextra -fsanitize=address,undefined -fno-omit-frame-pointer' test
```

The pinned upstream codec emits two unused-code compiler warnings. No warnings
were emitted for the project's own C source in these builds. This is a bounded
offline test corpus, not validation of a complete radio firmware image.
