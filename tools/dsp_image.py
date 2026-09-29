#!/usr/bin/env python3
"""Read-only, exact-image DSP load and initialization map; no DSP execution."""
import argparse
from pathlib import Path
import struct

from firmware import checked_image, digest, lzss, MAX_IMAGE, parse, read_image, require_target, revision, TARGET_REGISTRY
from reporting import atomic_json

PROGRAM_SHA = '3093818ec5716abb00c16dd686a980c00812c88e73d0753b3c19e9f1d15429a1'
CINIT_ADDRESS = 0x1182f2f8
DISPATCH_ADDRESS = 0x11818100


def disjoint(ranges, address, size):
    if not size or address + size > 2**32:
        raise ValueError('Invalid destination range')
    if any(address < other + count and other < address + size for other, count in ranges):
        raise ValueError('Overlapping destinations')
    ranges.append((address, size))


def ais(data):
    """Parse only the observed uncompressed AIS commands; reject unknown effects.

    Return a separate trailer after Jump & Close. Trailer bytes are not loaded.
    Section contents remain in the caller's input, referenced by offset and hash.
    """
    if not 4 <= len(data) <= MAX_IMAGE:
        raise ValueError('Invalid AIS size')
    offset = 0

    def word():
        nonlocal offset
        if offset + 4 > len(data):
            raise ValueError('Truncated AIS word')
        result = struct.unpack_from('<I', data, offset)[0]
        offset += 4
        return result

    if word() != 0x41504954:
        raise ValueError('Invalid AIS magic')
    commands, sections, ranges = [], [], []
    while offset < len(data):
        start, opcode = offset, word()
        row = {'offset': start, 'opcode': opcode}
        if opcode == 0x58535963:
            row['name'] = 'sequential_read_enable'
        elif opcode == 0x5853590d:
            spec = word()
            count = spec >> 16
            if count > (len(data) - offset) // 4:
                raise ValueError('Truncated AIS function arguments')
            row.update(name='function_execute', function=spec & 65535,
                       arguments=[word() for _ in range(count)])
        elif opcode == 0x58535901:
            address, size = word(), word()
            end = offset + ((size + 3) & ~3)
            if end > len(data):
                raise ValueError('Truncated AIS section')
            disjoint(ranges, address, size)
            if any(data[offset + size:end]):
                raise ValueError('Nonzero AIS section padding')
            row.update(name='section_load', address=address, size=size,
                       data_offset=offset, sha256=digest(data[offset:offset + size]))
            sections.append(row)
            offset = end
        elif opcode == 0x58535906:
            entry = word()
            if not any(a <= entry < a + n for a, n in ranges):
                raise ValueError('AIS entry is outside loaded sections')
            row.update(name='jump_close', entry=entry)
            commands.append(row)
            return {'commands': commands, 'sections': sections, 'entry': entry,
                    'ais_bytes': offset, 'trailer_bytes': len(data) - offset,
                    'trailer_sha256': digest(data[offset:])}
        else:
            raise ValueError(f'Unsupported AIS opcode {opcode:#x}')
        commands.append(row)
    raise ValueError('Missing AIS Jump & Close')


def initialization_records(data):
    """Observed size/address/payload format with 8-byte record alignment.

    This is a structural parser, not an execution of the startup copy routine.
    Returns offsets, not reconstructed RAM or firmware payloads.
    """
    if not 4 <= len(data) <= MAX_IMAGE:
        raise ValueError('Invalid initialization table size')
    offset, rows, ranges = 0, [], []
    while offset + 4 <= len(data):
        size = struct.unpack_from('<I', data, offset)[0]
        if size == 0:
            if offset + 4 != len(data):
                raise ValueError('Trailing initialization data')
            return rows
        if offset + 8 + size > len(data):
            raise ValueError('Truncated initialization record')
        address = struct.unpack_from('<I', data, offset + 4)[0]
        disjoint(ranges, address, size)
        end = (offset + 8 + size + 7) & ~7
        if end > len(data) or any(data[offset + 8 + size:end]):
            raise ValueError('Invalid initialization padding')
        rows.append({'offset': offset, 'address': address, 'size': size,
                     'data_offset': offset + 8,
                     'sha256': digest(data[offset + 8:offset + 8 + size])})
        offset = end
    raise ValueError('Missing initialization terminator')


def analyze(container):
    require_target(container, 'trace')
    part = next(p for p in parse(container) if p['name'] == 'dsp_program')
    encoded = container[part['offset']:part['offset'] + part['size']]
    program, consumed = lzss(encoded, part['decoded_size'])
    if consumed != len(encoded) or digest(program) != PROGRAM_SHA:
        raise ValueError('Require exact reviewed DSP program')
    layout = ais(program)
    trailer = program[layout['ais_bytes']:]
    if trailer != b'\xff' * 29312 + b'31101070':
        raise ValueError('Unexpected DSP trailer')
    section = next(s for s in layout['sections'] if s['address'] == CINIT_ADDRESS)
    table = program[section['data_offset']:section['data_offset'] + section['size']]
    records = initialization_records(table)
    dispatch = next(r for r in records if r['address'] == DISPATCH_ADDRESS)
    if dispatch['size'] != 1024:
        raise ValueError('Unexpected dispatch table size')
    targets = struct.unpack_from('<256I', table, dispatch['data_offset'])
    if any(not any(s['address'] <= t < s['address'] + s['size']
                   for s in layout['sections']) for t in targets):
        raise ValueError('Dispatch target outside loaded sections')
    return {'image_sha256': digest(container), 'program_sha256': digest(program),
            'program_bytes': len(program), 'layout': layout,
            'initialization': {'address': CINIT_ADDRESS, 'records': records,
                               'initialized_bytes': sum(r['size'] for r in records)},
            'command_table': {'address': DISPATCH_ADDRESS, 'entries': len(targets),
                              'command_0x42_target': targets[0x42]},
            'limits': ['Structural load/initialization map, not DSP execution or live RAM.',
                       'Loaded sections are not automatically classified as executable code.',
                       'Command-table entry alone does not establish audio gain or channel meaning.',
                       'ROM function commands are recorded but never executed.']}


def tool_hashes():
    return dict({name: digest(Path(__file__).with_name(name).read_bytes())
                 for name in ('dsp_image.py', 'firmware.py', 'reporting.py')},
                targets=digest(TARGET_REGISTRY.read_bytes()))


def report(image):
    image = Path(image)
    hashes, source = tool_hashes(), revision()
    data = checked_image(image, 'trace')
    result = analyze(data)
    if read_image(image) != data or hashes != tool_hashes() or source != revision():
        raise ValueError('Image/source changed during DSP analysis')
    return dict(result, tool_sha256=hashes, source_revision=source, source_unchanged=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output already exists')
    result = report(args.image)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(args.output, result)
    print(args.output)


if __name__ == '__main__':
    main()
