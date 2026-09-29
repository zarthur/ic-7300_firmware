# Receive diagnostic memory and cursor ownership

The next receive diagnostic cannot assume the decoder budget is free RAM. Exact
v1.42 allocator code exposes a **348,152-byte shared arena**, and a separate large
region is registered for graphics framebuffer management. The second read cursor
in the second sample queue is also actively used. These findings narrow the
candidate design; they do not constitute a live allocation/headroom measurement.

## Reproduce

```
.venv/bin/python tools/native_memory.py artifacts/original/7300_142.dat \
  --output artifacts/native-receive/memory.json
IC7300_TEST_IMAGE=artifacts/original/7300_142.dat \
  .venv/bin/python -m unittest discover -s tests -p 'test_native*.py' -v
```

The tool uses the same exact application gate and bounded original-code engine as
[native_receive.py](../tools/native_receive.py), preserves image/source provenance,
and rejects mutation during analysis. It executes the allocator, free routine
and original copy helper against a private initially empty heap. It checks live
payload preservation, free-list bounds/order and non-overlapping allocations.
This models sequential calls, not target concurrency or available memory.

## Recovered allocator

Thumb entry `0x20186230` tries `0x20186bc8` and lazily initializes the free list
if allocation failed and the initialized flag is zero. Its arena starts at
`0x20587b64`, with limit `0x205dcb60`; it rounds the difference down to an
8-byte multiple. The head pointer is at `0x20390b00`, initialization flag at
`0x20390b04`. Core allocation rounds `request+11` down to a multiple of eight,
uses a four-byte allocated header, splits a larger free block and returns an
8-byte-aligned payload pointer for this arena layout.

Free entry `0x20184b5c` inserts by address and coalesces adjacent blocks. The
original routine trusts its input; the test harness only permits releasing a
known live allocation. No double-free or invalid-pointer tolerance is claimed.
Neither bounded allocator routine supplies evidence of locking or interrupt-safe
concurrent operation. Do not allocate in the audio interrupt handler.

The stateful test sequence establishes:

- Two 4096-byte allocations and one 72-byte allocation remain disjoint and retain
  their supplied payloads while other blocks are allocated/freed.
- Releasing the middle block permits a same-size allocation at that address.
- A 393,216-byte request fails without changing the established free list.
- Releasing the three live blocks coalesces the full 348,152-byte arena.
- An initially unused arena can supply a 348,148-byte payload; the next one-byte
  request fails. Freeing the large block restores the full arena again.

The estimated 393,216-byte codec reservation exceeds this **entire** arena before
other users are counted. This disproves allocating that reservation from this
allocator as-is, not the feasibility of every FT8 memory design. The measured
smaller host heap, stack placement, other target allocations and possible static
reservation still need a unified budget. A small diagnostic can request memory
and handle failure, but allocator availability and call context must be verified.

## Graphics and startup ranges

At `0x20079254`, startup passes base `0x2084cc00` and length `0x1b3400` to
`0x2007daf8`. That function stores the region in the object at `0x203904ec` and
creates metadata through `0x2007dab4`, which uses the shared allocator above.
Associated initialization/error strings identify framebuffer management alongside
EGL/OpenVG startup. The region is not an unused extension heap. Its clear at
`0x2002b2d8` is not permission to repurpose it.

The existing scatter table at `0x20360aac` is reproduced in the new report:

| Destination | Length | Action |
| --- | ---: | --- |
| `0x20390000` | `0xb18` | Copy initialized data from `0x20360b54` |
| `0x20390b18` | `0x24c448` | Clear |
| `0x2080d000` | `0x3fc00` | Clear |

The decoded file ends at `0x20395b18`, inside the first clear range. Appending
code at the decoded end would place it in memory cleared during startup and
already assigned to runtime state.

A different interval, **`0x2036166c..0x20390000` (190,868 bytes)**, contains only
`0xff` in the pinned decoded image and lies after the initialized-data source and
before those destination ranges. This is a candidate for further placement
analysis, not yet a declared executable reservation. Before using it, verify
runtime references/aliases, memory attributes, loader/image limits, initialization
ordering and updater behavior for the exact proposed footprint. Padding bytes
alone do not prove free memory. The current report deliberately records
`runtime_ownership_established: false`.

## Second sample queue is not a spare subscription

The [receive map](native-receive-interface.md) identifies two read cursors at
`0x203fc002+0x241/+0x242`. Consumer `0x20067130` uses selector 0 for the recording
path. `0x2004536c` uses selector 1, scans signed minima/maxima over the queued
36-sample blocks, clamps absolute peak to 32767 and retains a peak at
`0x2039024e`. Caller `0x20045424` gates this work on UI/state fields and can flush
that cursor separately.

The receive probe now executes this meter with negative full scale, silence,
previous-peak and empty-queue fixtures. It advances only the second cursor,
preserves the first cursor, retains a greater previous peak, and maps -32768 to
32767. Thus both native read cursors have consumers. This does not yet establish
whether the stream represents RX, TX monitoring or a DSP-selectable source in
all modes.

## Next candidate work

1. Qualify the padding interval for a small original diagnostic payload; preserve
   every existing initialization range and allocator/queue owner. No region is
   reserved by this document alone.
2. Trace stream selection and gain controls. Capture both channels initially if
   needed to establish identity; do not silently label one an invariant RX tap.
3. Resolve a bounded initialization hook and a task-context export path. Keep
   copying and raw timing observations bounded in the interrupt, with no decoder,
   allocation or filesystem operation there. Preserve original call/register flow.
4. Build and emulate the exact diagnostic candidate, its lifetime, failure/overflow
   behavior and export format. Retain raw timer/sequence information described in
   [the timing findings](native-receive-timing.md).
5. Present the concrete installation/test scope for owner approval, then collect
   target evidence. The earlier display-only installation does not perform this
   test, and the goal remains open until timestamped diagnostic capture succeeds.
