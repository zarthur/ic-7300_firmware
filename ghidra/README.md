# Ghidra import

Ghidra is optional and was not installed on the development host. Static evidence
is generated with pinned Capstone; this Java post-script is provided for follow-up
and has not been executed in Ghidra yet.

After extraction, import `application.decoded.bin` as raw ARM little-endian v7,
base `0x20005000`, compiler default. The main CPU is Cortex-A9 (RZ/A1H).
Do not import the compressed file as executable ARM code.

Example (set `GHIDRA_HOME` to an existing installation):

```sh
mkdir -p artifacts/ghidra
"$GHIDRA_HOME/support/analyzeHeadless" artifacts/ghidra ic7300 \
  -import artifacts/extracted/142/application.decoded.bin \
  -processor ARM:LE:32:v7 -loader BinaryLoader \
  -loader-baseAddr 0x20005000 -noanalysis \
  -scriptPath ghidra -postScript Annotate7300.java
```

Import `main.stored.bin` separately at `0x18000000`. Its first 64 KiB contains
boot/loader material. The loader copies offset `0x4000`, length `0x650`, to
`0x20004000`; create a separate initialized RAM block with those bytes to recover
its branch destinations. Main application expansion goes to `0x20005000`.
Compressed data and fonts should remain data. DSP/FPGA payloads require their
own architecture/container research; do not import them as ARM.

Commit analysis scripts, address annotations and factual findings, not `.gpr` or
`.rep` databases. Treat string xrefs as investigation leads until actual control
flow and calling conventions are verified.
