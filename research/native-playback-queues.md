# Native audio output queues: bounded v1.42 findings

This is a software-only continuation of Epic 2 issue #16. Addresses refer to
the decoded original IC-7300 v1.42 application, SHA-256
`4686728c9d1f7249b6278a29686a40b8fa5e527bd2428a76a33cd9395178c9a4`.
The pinned container is `artifacts/original/7300_142.dat`.

## Reproduction

The tests run the original push, pop and reset instructions against private
synthetic RAM. They do not run either worker or any peripheral code.

```sh
IC7300_TEST_IMAGE=artifacts/original/7300_142.dat \
  artifacts/toolchains/python311/venv/bin/python -m unittest \
  tests.test_native_playback_map -v
```

`tools/native_playback_map.py` verifies the application hash and selected
instruction/literal words before producing its static summary. The bounded
runner imported from `native_receive.py` rejects execution outside the selected
instruction slices and memory outside the fixture regions.

## Queue mechanics

| Ring | Base from original literal | Entries | Producer cursor | Consumer cursor | Operations |
| --- | --- | ---: | ---: | ---: | --- |
| A | `0x203fbcc0` (`0x200606f8`) | 13 × 12 bytes | `+0x9c` | `+0x9d` | push `0x2005f900`, pop `0x2005f948`, reset `0x2005f8ac` |
| B | `0x203fbd5e` (`0x200606fc`) | 8 × 12 bytes | `+0x60` | `+0x61` | push `0x2005fa14`, pop `0x2005fa5c`, reset `0x2005f9b0` |

Each push copies three 32-bit words into the slot selected by the producer
cursor, then advances that cursor modulo the ring size. The push helpers do not
check available capacity or return a status code. Each pop copies a 12-byte
entry and advances the consumer cursor when the cursors differ. If the cursors
match, it writes twelve zero bytes and leaves the consumer cursor unchanged.
The exact-image probes cover both rings, including cursor wrap.

Resetting either ring sets both cursors to zero and leaves every slot byte
untouched. Repeated pushes can lap the consumer until the cursors match again;
the next pop then observes the empty case. A caller must prevent overrun or
distinguish a full lap through separate state.

The separate producer at `0x20067480` calculates free entries and returns
without producing when fewer than six are available; otherwise it generates
six 12-byte entries. It selects
one of these rings and directly calls the matching push helper. The output
service at `0x20060778` directly calls both pop helpers while preparing output
DMA buffers. These producer/consumer call sites establish that the two rings
feed an existing DMA output service. The DMA service itself uses MMIO and is
only statically inspected here.

## Worker and completion boundary

Two task loops use the shared object at `0x20390444`: `0x2006bb58` waits on
object `+0x24` and dispatches the byte at `+4`; `0x2006c2c4` waits on `+0x28`
and dispatches the byte at `+5`. The former's command-7 branch enters
`0x2006ab80`, which can invoke the voice-file scanner `0x2006a90c`. The latter's
command-6 branch enters the stored-file reader `0x2006bfd4`. Posting helpers
include `0x2006bcac`, which writes command 9 and signals `+0x28`.

Those code paths do not establish that the voice-file scan or stored-file
reader owns rings A/B. The output producer's owning task/caller is also not
qualified. Worker results enter local cleanup/state-update routines, but no
verified path waits for these queues to drain before reporting audio completion.
No caller association for the two reset routines, abort notification, PTT
release, or transmit lifecycle was established. Consequently a worker return
must not be treated as audible playback completion or safe TX release.

## Host mock sequencer contract

The portable station abstraction now requires cumulative backend progress for
each reservation. A queue report cannot exceed samples generated; a drain report
cannot exceed samples queued. Only after exactly 151,680 samples have been
generated, accepted by the backend queue, and reported drained does the station
call `qso_tx_finished(..., true)`. Generation completion and queue acceptance
alone leave the QSO active.

Duplicate progress is rejected without changing state. Backward/future counts,
drain-before-queue, and stale tickets fail closed: the waveform is cancelled and
the QSO reservation is invalidated. Cancellation first enters abort-requested;
backend abort and flush reports remain separate. Pending output requires an
explicit flush confirmation before another reservation can start. Backend
failure never completes the QSO and likewise needs a flush confirmation to
clear the local restart gate.

`tests/test_station.c` provides the only backend implementation, a local mock
that supplies these reports. It tests queue-versus-drain, abort/flush, duplicate
and out-of-order progress, stale tickets, and failure. This does not map the
radio's sample counters or signals.

## Issue #16 status and next step

The queue mechanics and mock sequencer contract are now reproducible, but #16
remains open until the voice/TX worker-to-ring ownership and completion boundary
are traced. Firmware integration still depends on locating the real drain,
abort/flush, and PTT-release signals. The host contract does not establish RF
cessation or hardware safety.

This study executes only the ring slices in synthetic memory. It does not
access a radio, exercise PTT, inject a waveform, run a task/event wait, perform
MMIO or DMA, or establish audible timing, concurrency, or physical TX behavior.
