# Native recorder batch preservation

`tools/native_record_batch.py` executes original v1.42 selection and copying from
`0x2004943c` to the write-submission boundary `0x200497f0`, or the no-write exit
`0x20049840`. It includes the original tag lookup and record metadata helpers.
The preceding asynchronous-command busy check is outside this fixture; a stable,
ready recorder and producer snapshot are explicit inputs.

The ordinary batch ceiling is 4096 bytes. The first-header flag reduces it to
4052 bytes. Selection can consume only part of a 216-byte ring payload, leaving
a remaining-byte count and the consumer on that slot. The original post-submit
bookkeeping (`0x200497f4..0x20049838`) persists the count for the next batch.
The probe skips the submission and stops before the next helper; it does not
claim successful I/O, worker completion or an actual written SD file.

The test generates a valid 512-record synthetic capture and uses the original
project ARM carrier to create all 470 diagnostic fragments. It passes the
fragments, with ordinary prefix/suffix payloads, through repeated native batch
selection/copy. Tests begin at ring indices 0 and 1913, use both batch ceilings,
require partial slots to occur, and reconstruct all bytes in order. The strict
carrier decoder then recovers storage identical to the input. Guards check that
no output bytes beyond the submitted length change.

Separate cases verify an initial partial slot, the pause/no-submit branch, and
a tag mismatch: selection stops before another file's payload and sets the
file-change flag. This establishes why keeping one recording/file tag throughout
export matters. It does not establish the runtime mapping of UI settings to
these flags, concurrent producer scheduling, tag redirection, all recorder
modes, filesystem transformation or lossless target storage.

Reproduce with a locally supplied pinned original image:

```sh
IC7300_TEST_IMAGE=artifacts/original/7300_142.dat \
  .venv/bin/python -m unittest discover -s tests -p test_native_record_batch.py -v
```

The receive candidate remains a diagnostic experiment. Target stack headroom,
interrupt latency, actual recorder output and timestamp interpretation still
need measurement. The existing exact-wrapper tests bound added DMA stack use
at 88 bytes below the supplied post-cache SP; this is not free-stack evidence.
A full carrier fragment takes 1209 emulated instructions. Some original publisher
calls occur with IRQs disabled, so this cannot be equated to negligible latency.
No acceptance criterion for issue #15 is satisfied by synthetic capture alone.
