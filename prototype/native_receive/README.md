# Bounded receive diagnostic prototype

This directory contains original ARMv7-A diagnostic code and offline integration
tests. It is not an installable firmware image, and no target capture exists yet.

`capture.S` copies 36 signed 16-bit samples from each of the two native extracted
streams into fixed storage, preserving their bit patterns and halfword alignment.
It retains a sequence and seven raw observation words per record, stops at 512
records, and cannot wrap or overwrite an earlier record. Storage is 90,128 bytes:
16 control bytes plus 512 records of 176 bytes. The standalone core is 164 bytes
and takes 343 emulated instructions per copy, not measured CPU cycles.

`transport.S` carries the frozen storage through 470 recorder payloads of 216
bytes. It leaves original audio unchanged before capture completion and after
export. Each fragment has a magic identifier, total size, byte offset, payload
length and FNV-1a-32 checksum. Host recovery requires all fragments in order in
one file and rejects incomplete or corrupt input. The intended diagnostic would
replace part of a recording with capture data rather than listenable audio.

`wrappers.S` integrates both cores at three exact original v1.42 call sites. It
arms once on the first nonzero recorder write submission, reads raw timer/pending
observations at the extracted sample boundary, preserves native queue publication,
and routes the recorder copy through the carrier only while needed. Automatic
recording could also trigger it; the ring watermark gate is not a recording-start
indicator. See the [wrapper qualification](../../research/native-receive-wrappers.md)
and [export boundary](../../research/native-receive-export.md).

The two standalone cores have no absolute device addresses or external calls.
The wrappers have explicit pinned addresses and restore the original queue/write
operations. They introduce no file requests, allocator calls, task creation,
timer configuration, interrupt acknowledgment or transmit operation. Tests bound
execution and memory accesses; this is not a substitute for target verification.

The caller must provide valid nonoverlapping storage and serialize producers.
Capture control is status/count/reserved/reserved. Status values are disabled=0,
armed=1, full=2, invalid=3 and busy=4; reserved words start at zero. BUSY is an
observation state, **not an atomic lock**. The consumer must wait for FULL with
appropriate ordering, or stop the producer before reading a partial buffer.
There is no rearm until reboot in the proposed wrapper design. DMB instructions
order publication; offline execution does not prove cache or interrupt behavior.

`tools/native_capture.py` assembles with clang's ARM target and rejects relocations
or extra allocated sections. The standalone tests require no firmware:

```sh
.venv/bin/python -m unittest discover -s tests -p test_native_capture.py -v
.venv/bin/python -m unittest discover -s tests -p test_native_transport.py -v
```

Exact-image wrapper tests also execute original native queue and publisher code
through the actual patched calls. Ring-to-file routing, partial-buffer handling,
target stack headroom and latency, candidate update validation, owner installation
review, and a timestamped hardware capture remain required by issue #15.
