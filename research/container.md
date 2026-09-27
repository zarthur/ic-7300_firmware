# IC-7300 update container

Evidence: official v1.40, v1.41, v1.42 packages in acquisition.json; reproducible
parser/extractor in tools/firmware.py. All offsets below are for these releases.

## Confirmed structure

All three DAT files are 3,954,089 bytes. The little-endian magic at offset 0 is
`0x55667733`. Bytes 4..15 contain `3.112.003.16`; this is not the public release
number. Its finer semantics are unresolved. Offset 16 contains seven LE32 words:

| Header offset | Meaning | Value |
|---|---|---|
| 0x10 | Main stored length | 0x252bf0 |
| 0x14 | Second stored length | 0x17e46 |
| 0x18 | Second decoded length | 0x27f08 |
| 0x1c | Third stored length | 0xb03ac |
| 0x20 | Third decoded length | 0xaff08 |
| 0x24 | Fourth stored length | 0xaa759 |
| 0x28 | Fourth decoded length | 0xd1d14 |

| Payload | File offset | Digest offset | Identification |
|---|---|---|---|
| Main | 0x2c | 0x252c1c | Confirmed ARM bootstrap and application |
| DSP program candidate | 0x252c2c | 0x26aa72 | Decodes to TI boot-style `TIPA` prefix; role strongly supported |
| DSP data candidate | 0x26aa82 | 0x31ae2e | Role inferred from ordering and release component list |
| FPGA candidate | 0x31ae3e | 0x3c5597 | Role inferred; decoded prefix `31601130`; bitstream format unresolved |

Each payload is followed by its 16-byte MD5. Every digest matches all three
official releases. Header + four payload/digest pairs + two trailer bytes covers
the file exactly. Trailer `37 65` is constant. The v1.42 checker at 0x200247e4 compares it
against a fixed tag; emulation confirms rejection on mismatch. It is not a
computed checksum in this recovered check. Other versions’ device-side checks
have not been traced; see [updater emulation](updater-emulation.md). ZIP CRC and
payload MD5 are integrity checks, not proof of signed firmware or authenticity.
No conclusion about acceptance of modified images follows from these checks.

## Compression and addresses

Main payload offset 0x10000 contains a LE32 output length followed by LZSS.
Boot code at flash 0x18000000 installs vectors and copies a 0x650-byte loader
from flash 0x18004000 to RAM 0x20004000. At 0x200043b4 the loader reads the output
length; it passes source+4 and destination 0x20005000 to decompressor 0x2000425c.
The decoded application's reset vector is 0x20005050 and its self-consistent
string pointers corroborate the RAM mapping.

The decompressor uses flags LSB first, 1=literal, 0=two-byte match; a 4096-byte
ring starts writing at 0xfee. Match offset is `lo | ((hi & 0xf0) << 4)`, length is
`(hi & 15)+3`. Initially bytes 0..0xfed are zero. Reads from the uninitialized
tail are rejected by our parser. Output length bounds expansion, including a
partial final match. All three other streams consume their stored length exactly.

For v1.42, application output length is 3,738,392 bytes. Expansion consumes
1,676,645 bytes after the length word, including bytes in the 0xff-filled region;
do not infer compressed extent from the first long padding run. Retain raw bytes.
The main payload also includes uncompressed font-like data beginning at offset
0x210000 (file 0x21002c); this region is not part of the application stream.

Reconstruction concatenates retained original sections and requires the original
SHA-256. It does not recompress changed code, regenerate unknown metadata, or
produce a flashable custom image. This deliberate limit prevents a lossless
roundtrip from being mistaken for a working firmware packer.

Across v1.40/1.41/1.42 only the main payload and its MD5 change. DSP program,
DSP data, FPGA, header and trailer remain byte-identical.
