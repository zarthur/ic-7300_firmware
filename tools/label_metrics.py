#!/usr/bin/env python3
"""Compare embedded font metrics without extracting fonts or modifying firmware."""
import argparse
from collections import Counter
from pathlib import Path
import struct
import sys

from firmware import checked_image, digest, lzss, parse, require_target, revision
from reporting import atomic_json

APP_SHA256 = '4686728c9d1f7249b6278a29686a40b8fa5e527bd2428a76a33cd9395178c9a4'
TEXTS = ('Information', 'Custom info', 'Informaiton')
FONT_OFFSETS = (0x210000, 0x240000)


def unpack(fmt, data, offset=0):
    if offset < 0 or offset + struct.calcsize(fmt) > len(data):
        raise ValueError('Truncated font structure')
    return struct.unpack_from(fmt, data, offset)


def font_metrics(font, texts=TEXTS):
    """Bounded sfnt/cmap4/hmtx/glyf inspection; output contains metrics, not font data."""
    if len(font) > 2 * 1024 * 1024 or font[:4] != b'\0\1\0\0':
        raise ValueError('Expected bounded TrueType font')
    count = unpack('>H', font, 4)[0]
    if not 1 <= count <= 64 or 12 + 16 * count > len(font):
        raise ValueError('Invalid font table count')
    tables, ranges = {}, []
    for index in range(count):
        tag, checksum, offset, length = unpack('>4sIII', font, 12 + 16 * index)
        if tag in tables or offset < 12 + 16 * count or not length or offset + length > len(font):
            raise ValueError('Invalid or duplicate font table')
        tables[tag] = font[offset:offset + length]
        ranges.append((offset, offset + length))
    if any(end > start for (_, end), (start, _) in zip(sorted(ranges), sorted(ranges)[1:])):
        raise ValueError('Overlapping font tables')
    if not all(tag in tables for tag in (b'head', b'hhea', b'maxp', b'hmtx', b'cmap', b'loca', b'glyf')):
        raise ValueError('Missing required metric table')
    units = unpack('>H', tables[b'head'], 18)[0]
    location_format = unpack('>h', tables[b'head'], 50)[0]
    glyph_count = unpack('>H', tables[b'maxp'], 4)[0]
    metric_count = unpack('>H', tables[b'hhea'], 34)[0]
    if not 16 <= units <= 16384 or not 1 <= metric_count <= glyph_count or location_format not in (0, 1):
        raise ValueError('Invalid font metric dimensions')
    if len(tables[b'hmtx']) < 4 * metric_count + 2 * (glyph_count - metric_count):
        raise ValueError('Truncated horizontal metrics')
    cmap = tables[b'cmap']
    records = unpack('>H', cmap, 2)[0]
    if not 1 <= records <= 64 or 4 + 8 * records > len(cmap):
        raise ValueError('Invalid character-map records')
    selected = None
    for index in range(records):
        platform, encoding, offset = unpack('>HHI', cmap, 4 + 8 * index)
        if (platform, encoding) == (3, 1) and unpack('>H', cmap, offset)[0] == 4:
            length = unpack('>H', cmap, offset + 2)[0]
            if length < 16 or offset + length > len(cmap):
                raise ValueError('Truncated format-4 map')
            selected = cmap[offset:offset + length]
            break
    if selected is None:
        raise ValueError('Supported Unicode format-4 character map missing')
    segment_twice = unpack('>H', selected, 6)[0]
    if segment_twice % 2 or not 2 <= segment_twice <= 8192:
        raise ValueError('Invalid character-map segments')
    segments = segment_twice // 2
    if 16 + 8 * segments > len(selected):
        raise ValueError('Truncated character-map segments')
    end_at, start_at = 14, 16 + 2 * segments
    delta_at, range_at = start_at + 2 * segments, start_at + 4 * segments
    def word(offset):
        return unpack('>H', selected, offset)[0]
    def glyph(code):
        for index in range(segments):
            lo, hi = word(start_at + 2 * index), word(end_at + 2 * index)
            if lo <= code <= hi:
                delta, relative = word(delta_at + 2 * index), word(range_at + 2 * index)
                if not relative:
                    return (code + delta) & 0xFFFF
                result = word(range_at + 2 * index + relative + 2 * (code - lo))
                return ((result + delta) & 0xFFFF) if result else 0
        return 0
    def outline(gid):
        fmt, stride, scale = ('>H', 2, 2) if location_format == 0 else ('>I', 4, 1)
        start = unpack(fmt, tables[b'loca'], stride * gid)[0] * scale
        end = unpack(fmt, tables[b'loca'], stride * (gid + 1))[0] * scale
        if not 0 <= start <= end <= len(tables[b'glyf']):
            raise ValueError('Invalid glyph extent')
        if start == end:
            return None
        if end - start < 10:
            raise ValueError('Truncated glyph bounds')
        box = list(unpack('>4h', tables[b'glyf'], start + 2))
        if box[0] > box[2] or box[1] > box[3]:
            raise ValueError('Invalid glyph bounds')
        return box
    if not texts or any(not text or len(text) > 128 or any(not 32 <= ord(c) < 127 for c in text) for text in texts):
        raise ValueError('Require bounded printable ASCII comparison strings')
    metrics = {}
    for char in sorted(set(''.join(texts))):
        gid = glyph(ord(char))
        if not 0 < gid < glyph_count:
            raise ValueError(f'Missing mapped glyph for {char!r}')
        metrics[char] = dict(glyph_id=gid,
            advance=unpack('>H', tables[b'hmtx'], 4 * min(gid, metric_count - 1))[0], ink=outline(gid))
    runs = {}
    for text in texts:
        pen, boxes, placements = 0, [], []
        for char in text:
            metric = metrics[char]
            placements.append(dict(character=char, origin=pen, advance=metric['advance']))
            if metric['ink'] is not None:
                x0, y0, x1, y1 = metric['ink']
                boxes.append([pen + x0, y0, pen + x1, y1])
            pen += metric['advance']
        ink = [min(b[0] for b in boxes), min(b[1] for b in boxes),
               max(b[2] for b in boxes), max(b[3] for b in boxes)] if boxes else None
        runs[text] = dict(advance=pen, ink=ink, glyph_count=len(text), placements=placements)
    return dict(font_sha256=digest(font), font_bytes=len(font), units_per_em=units,
        characters=metrics, runs=runs, kern_table_present=b'kern' in tables,
        coordinate_space='Unhinted font units, zero added spacing; no pixel/raster claim')


def font_resource(main, offset):
    length = unpack('<I', main, offset)[0]
    if not 0 < length <= 2 * 1024 * 1024 or offset + 4 + length > len(main):
        raise ValueError('Invalid embedded font resource length')
    return main[offset + 4:offset + 4 + length]


def _report(image):
    target = require_target(image, 'trace')
    if target['version'] != '142':
        raise ValueError('Font analysis supports pinned v1.42 only')
    part = parse(image)[0]
    main = image[part['offset']:part['offset'] + part['size']]
    app, _ = lzss(main[0x10004:], unpack('<I', main, 0x10000)[0])
    if digest(app) != APP_SHA256:
        raise ValueError('Unexpected decoded application')
    fonts = [dict(main_offset=hex(offset), **font_metrics(font_resource(main, offset))) for offset in FONT_OFFSETS]
    same_metrics = all(font['runs'][TEXTS[0]]['advance'] == font['runs'][TEXTS[2]]['advance']
        and font['runs'][TEXTS[0]]['ink'] == font['runs'][TEXTS[2]]['ink'] for font in fonts)
    return dict(schema_version=1, outcome='PASS' if same_metrics else 'FAIL',
        image_sha256=digest(image), application_sha256=digest(app), fonts=fonts,
        preferred_proposal=TEXTS[2], same_glyph_multiset=Counter(TEXTS[0]) == Counter(TEXTS[2]),
        same_advance_and_outer_ink_in_both_fonts=same_metrics,
        changed_character_indices=[i for i, (a, b) in enumerate(zip(TEXTS[0], TEXTS[2])) if a != b],
        patch_qualified=False, candidate_emitted=False,
        interpretation='Prefer the two-character transposition for a first visible label experiment; static font evidence removes the measured widening of Custom info in the proportional font.',
        limitations=['Metrics are from embedded original fonts; active runtime font selection/cache state is not observed.',
            'Glyph order and local ink placement differ even with equal total advance and outer ink bounds.',
            'Hinting, subpixel rounding, clipping, graphics backend and final visible pixels were not executed.',
            'Original reviewed width/draw loops use per-glyph advances and constant spacing; this report does not claim universal shaping/kerning behavior.',
            'Live menu-row construction and residual indirect consumers remain separate qualification questions.',
            'No application changes, candidate packing or device I/O occur.'])


def tool_hashes():
    paths = {name: Path(__file__).with_name(name) for name in ('label_metrics.py', 'firmware.py', 'reporting.py')}
    paths['research/targets.json'] = Path(__file__).resolve().parents[1] / 'research/targets.json'
    return {name: digest(path.read_bytes()) for name, path in paths.items()}


def report(image):
    before, source = tool_hashes(), revision()
    result = _report(bytes(image))
    if before != tool_hashes() or source != revision():
        raise ValueError('Source changed during font analysis')
    return dict(result, source_revision=source, tool_sha256=before, source_unchanged=True, python=sys.version)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.suffix != '.json':
        parser.error('Choose a new JSON evidence path')
    result = report(checked_image(args.image, 'trace'))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(args.output, result)
    print(f'{result["outcome"]}: {args.output}; patch_qualified=false')
    return 0 if result['outcome'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
