#!/usr/bin/env python3
"""Bounded IC-7300 container inspection, extraction and lossless reconstruction.

MD5 validates the observed payload integrity scheme, not firmware authenticity.
Reconstruction preserves compressed bytes; this is NOT a custom-image packer.
"""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import struct
import subprocess
import sys

MAX_IMAGE = 16 * 1024 * 1024
NAMES = ('main', 'dsp_program', 'dsp_data', 'fpga')


def digest(b):
    return hashlib.sha256(b).hexdigest()


def revision():
    root = Path(__file__).resolve().parents[1]
    return {'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip(),
            'dirty': bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=root, text=True).strip())}


def read_image(path):
    with open(path, 'rb') as f:
        b = f.read(MAX_IMAGE + 1)
    if len(b) > MAX_IMAGE:
        raise ValueError('Image exceeds 16 MiB bound')
    return b


def parse(b):
    if len(b) < 46 or b[:4] != b'3wfU':
        raise ValueError('Invalid or truncated IC-7300 header')
    w = struct.unpack_from('<7I', b, 16)
    sizes = (w[0], w[1], w[3], w[5])
    outputs = (None, w[2], w[4], w[6])
    if any(s == 0 or s > MAX_IMAGE for s in sizes) or any(s > MAX_IMAGE for s in outputs[1:]):
        raise ValueError('Invalid payload size')
    if 44 + sum(sizes) + 4 * 16 + 2 != len(b):
        raise ValueError('Header lengths do not cover the container exactly')
    pos = 44
    parts = []
    for name, size, output in zip(NAMES, sizes, outputs):
        payload = b[pos:pos + size]
        stored = b[pos + size:pos + size + 16]
        if hashlib.md5(payload).digest() != stored:
            raise ValueError(f'MD5 mismatch in {name}')
        parts.append(dict(name=name, offset=pos, size=size, decoded_size=output,
                          sha256=digest(payload), md5=stored.hex()))
        pos += size + 16
    return parts


def lzss(data, output_size):
    """Loader's LSB-first, 4 KiB ring, 3..18 byte matches, initial write=0xfee.

    Loader initializes only ring[0:0xfee]; reject any read of uninitialized tail.
    Output length is authoritative, including a partial final match.
    """
    if not 0 < output_size <= MAX_IMAGE:
        raise ValueError('Invalid decoded size')
    ring = bytearray(4096)
    initialized = bytearray([1]) * 4078 + bytearray(18)
    write, pos = 4078, 0
    out = bytearray()
    while len(out) < output_size:
        if pos >= len(data):
            raise ValueError('Truncated LZSS flags')
        flags = data[pos]
        pos += 1
        for bit in range(8):
            if flags & (1 << bit):
                if pos >= len(data):
                    raise ValueError('Truncated LZSS literal')
                values, index, count = data[pos], None, 1
                pos += 1
            else:
                if pos + 2 > len(data):
                    raise ValueError('Truncated LZSS reference')
                low, high = data[pos:pos + 2]
                pos += 2
                index, count = low | ((high & 240) << 4), (high & 15) + 3
            for k in range(min(count, output_size - len(out))):
                if index is not None:
                    if not initialized[(index + k) & 4095]:
                        raise ValueError('LZSS references uninitialized history')
                    values = ring[(index + k) & 4095]
                out.append(values)
                ring[write] = values
                initialized[write] = 1
                write = (write + 1) & 4095
            if len(out) == output_size:
                break
    return bytes(out), pos


def entropy(b):
    return -sum((n / len(b)) * math.log2(n / len(b)) for n in Counter(b).values()) if b else 0


def strings(b):
    return [{'offset': m.start(), 'text': m.group().decode('ascii')[:200]}
            for m in re.finditer(rb'[\x20-\x7e]{8,}', b)]


def analyze(b):
    parts = parse(b)
    signatures = {}
    for name, magic in [('ELF', b'\x7fELF'), ('PNG', b'\x89PNG\r\n\x1a\n'),
                        ('gzip', b'\x1f\x8b\x08'), ('ZIP', b'PK\x03\x04'), ('XZ', b'\xfd7zXZ\x00')]:
        signatures[name] = [m.start() for m in re.finditer(re.escape(magic), b)]
    return dict(source_revision=revision(), bytes=len(b), sha256=digest(b),
                header_hex=b[:44].hex(), header_ascii=b[4:16].decode('ascii', errors='replace'),
                header_words=list(struct.unpack_from('<7I', b, 16)), parts=parts,
                trailer_hex=b[-2:].hex(), trailer_interpretation='unknown',
                signatures=signatures, strings=strings(b),
                entropy_64k=[dict(offset=i, entropy=round(entropy(b[i:i+65536]), 6)) for i in range(0, len(b), 65536)])


def write_report(report, prefix):
    prefix.parent.mkdir(parents=True, exist_ok=True)
    prefix.with_suffix('.json').write_text(json.dumps(report, indent=2) + '\n')
    lines = ['# Firmware analysis', '', f"SHA-256: `{report['sha256']}`", '',
             f"Source revision: `{report['source_revision']['commit']}`; dirty: {report['source_revision']['dirty']}", '',
             '| Payload | File offset | Stored bytes | Decoded bytes | MD5 |', '|---|---:|---:|---:|---|']
    for p in report['parts']:
        lines.append(f"| {p['name']} | 0x{p['offset']:x} | {p['size']} | {p['decoded_size']} | {p['md5']} |")
    lines += ['', 'All four MD5 values verified. Trailer semantics unknown; no signature validation established.',
              '', 'Strings, signature candidates and block entropy are in the companion JSON.']
    prefix.with_suffix('.md').write_text('\n'.join(lines) + '\n')


def extract(b, folder):
    parts = parse(b)
    if folder.exists():
        raise ValueError('Extraction directory already exists; choose a new directory')
    # Validate all streams before creating output files.
    decoded = {}
    for p in parts:
        raw = b[p['offset']:p['offset']+p['size']]
        if p['name'] == 'main':
            if len(raw) < 0x10004:
                raise ValueError('Main payload too short for known layout')
            size = struct.unpack_from('<I', raw, 0x10000)[0]
            decoded['application'] = lzss(raw[0x10004:], size)
        else:
            decoded[p['name']] = lzss(raw, p['decoded_size'])
    folder.mkdir(parents=True)
    (folder / 'header.bin').write_bytes(b[:44])
    (folder / 'trailer.bin').write_bytes(b[-2:])
    for p in parts:
        start = p['offset']
        (folder / (p['name'] + '.stored.bin')).write_bytes(b[start:start+p['size']])
        (folder / (p['name'] + '.md5.bin')).write_bytes(b[start+p['size']:start+p['size']+16])
    for name, (data, consumed) in decoded.items():
        (folder / (name + '.decoded.bin')).write_bytes(data)
    manifest = {'original_sha256': digest(b), 'parts': parts,
                'decoded': {n: dict(size=len(d), consumed=c, sha256=digest(d)) for n, (d, c) in decoded.items()}}
    (folder / 'extraction.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return manifest


def rebuild(folder):
    manifest = json.loads((folder / 'extraction.json').read_text())
    result = (folder / 'header.bin').read_bytes()
    for name in NAMES:
        result += read_image(folder / (name + '.stored.bin')) + (folder / (name + '.md5.bin')).read_bytes()
    result += (folder / 'trailer.bin').read_bytes()
    parse(result)
    if digest(result) != manifest['original_sha256']:
        raise ValueError('Reconstruction differs from original; modified packing is not implemented')
    return result


def compare(a, b):
    pa, pb = parse(a), parse(b)
    changed = [i for i, (x, y) in enumerate(zip(a, b)) if x != y]
    return dict(source_revision=revision(), a_sha256=digest(a), b_sha256=digest(b),
                a_bytes=len(a), b_bytes=len(b), changed_common_bytes=len(changed),
                extra_bytes=abs(len(a)-len(b)), first_difference=min(changed) if changed else None,
                last_difference=max(changed) if changed else None,
                parts=[dict(name=x['name'], equal=x['sha256']==y['sha256']) for x,y in zip(pa,pb)])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    for name in ('analyze', 'extract'):
        s = sub.add_parser(name); s.add_argument('image', type=Path); s.add_argument('output', type=Path)
    s = sub.add_parser('rebuild'); s.add_argument('folder', type=Path); s.add_argument('output', type=Path)
    s = sub.add_parser('diff'); s.add_argument('a', type=Path); s.add_argument('b', type=Path)
    args = p.parse_args()
    try:
        if args.command == 'analyze': write_report(analyze(read_image(args.image)), args.output)
        elif args.command == 'extract': print(json.dumps(extract(read_image(args.image), args.output), indent=2))
        elif args.command == 'rebuild':
            data = rebuild(args.folder)
            with args.output.open('xb') as f: f.write(data)
        else: print(json.dumps(compare(read_image(args.a), read_image(args.b)), indent=2))
    except (ValueError, OSError, KeyError, struct.error) as e:
        print(f'error: {e}', file=sys.stderr); return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
