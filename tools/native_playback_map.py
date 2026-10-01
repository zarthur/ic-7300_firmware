#!/usr/bin/env python3
"""Bounded original-instruction probes for two IC-7300 audio output rings.

The queue code runs only against private synthetic RAM. This does not emulate
DMA, a radio, PTT, the voice-file worker, or physical playback completion.
"""
import struct

from emulate_platform import APP_BASE, OUTPUT, SOURCE
from firmware import digest
from native_receive import Isolated
from recorder_interface import APPLICATION_SHA256


RINGS = {
    'A': {
        'base': 0x203fbcc0, 'slots': 13, 'write_offset': 0x9c, 'read_offset': 0x9d,
        'reset': (0x2005f8ac, 0x2005f8c0),
        'push': (0x2005f900, 0x2005f948),
        'pop': (0x2005f948, 0x2005f9b0),
    },
    'B': {
        'base': 0x203fbd5e, 'slots': 8, 'write_offset': 0x60, 'read_offset': 0x61,
        'reset': (0x2005f9b0, 0x2005f9c4),
        'push': (0x2005fa14, 0x2005fa5c),
        'pop': (0x2005fa5c, 0x2005fac4),
    },
}

# Exact ARM words from the pinned v1.42 application. These anchor the queue
# tests and the static worker/producer boundary described in the research note.
WORD_EVIDENCE = (
    (0x2005f8b4, 0xe5c1009c, 'strb r0,[r1,#0x9c]', 'ring A write cursor reset'),
    (0x2005f8b8, 0xe5c1009d, 'strb r0,[r1,#0x9d]', 'ring A read cursor reset'),
    (0x2005f908, 0xe5d3209c, 'ldrb r2,[r3,#0x9c]', 'ring A producer cursor'),
    (0x2005f930, 0xe20000ff, 'and r0,r0,#0xff', 'ring A modulo cursor mask'),
    (0x2005f958, 0xe1510002, 'cmp r1,r2', 'ring A empty comparison'),
    (0x2005f99c, 0xe3a01000, 'mov r1,#0', 'ring A empty-pop zero value'),
    (0x2005f9b8, 0xe5c10060, 'strb r0,[r1,#0x60]', 'ring B write cursor reset'),
    (0x2005f9bc, 0xe5c10061, 'strb r0,[r1,#0x61]', 'ring B read cursor reset'),
    (0x2005fa1c, 0xe5d32060, 'ldrb r2,[r3,#0x60]', 'ring B producer cursor'),
    (0x2005fa44, 0xe20000ff, 'and r0,r0,#0xff', 'ring B modulo cursor mask'),
    (0x2005fa6c, 0xe1510002, 'cmp r1,r2', 'ring B empty comparison'),
    (0x2005fab0, 0xe3a01000, 'mov r1,#0', 'ring B empty-pop zero value'),
    (0x2006bb88, 0xe5950024, 'ldr r0,[r5,#0x24]', 'first worker event wait'),
    (0x2006c2e4, 0xe5950028, 'ldr r0,[r5,#0x28]', 'file worker event wait'),
    (0x20067494, 0xebffe14e, 'bl 0x2005f9d4', 'producer checks ring B free entries'),
    (0x2006749c, 0xebffe107, 'bl 0x2005f8c0', 'producer checks ring A free entries'),
    (0x200674a0, 0xe3500006, 'cmp r0,#6', 'producer requires six free slots'),
    (0x200674a4, 0x3a000029, 'blo 0x20067550', 'producer skips batch when space is low'),
    (0x20067514, 0xebffe13e, 'bl 0x2005fa14', 'producer appends ring B entry'),
    (0x20067520, 0xebffe0f6, 'bl 0x2005f900', 'producer appends ring A entry'),
    (0x2006752c, 0xe3540006, 'cmp r4,#6', 'producer creates six entries'),
    (0x20067530, 0x3affffe9, 'blo 0x200674dc', 'producer repeats batch entry creation'),
    (0x200607cc, 0xebfffc5d, 'bl 0x2005f948', 'DMA service consumes ring A'),
    (0x200607d4, 0xebfffca0, 'bl 0x2005fa5c', 'DMA service consumes ring B'),
    (0x2006bb98, 0xe1d500d4, 'ldrsb r0,[r5,#4]', 'first worker command byte'),
    (0x2006bbc0, 0xea000024, 'b 0x2006bc58', 'first worker command-7 dispatch'),
    (0x2006bc58, 0xebfffbc8, 'bl 0x2006ab80', 'voice-file scan/state handler'),
    (0x2006c2f4, 0xe1d500d5, 'ldrsb r0,[r5,#5]', 'file worker command byte'),
    (0x2006c31c, 0xea000019, 'b 0x2006c388', 'file worker command-6 dispatch'),
    (0x2006c3a0, 0xebffff0b, 'bl 0x2006bfd4', 'stored-file reader handler'),
    (0x2006bcac, 0xe59f0720, 'ldr r0,[pc,#0x720]', 'worker request object literal'),
    (0x2006bcb4, 0xe5c01005, 'strb r1,[r0,#5]', 'request posts command 9'),
    (0x2006bcb8, 0xe5900028, 'ldr r0,[r0,#0x28]', 'request signals event +0x28'),
)

LITERAL_EVIDENCE = (
    (0x200606f8, 0x203fbcc0, 'ring A base literal'),
    (0x200606fc, 0x203fbd5e, 'ring B base literal'),
    (0x2006c3d4, 0x20390444, 'shared audio worker object'),
)

OPERATIONS = ('reset', 'push', 'pop')


def verify_image_words(app):
    if digest(app) != APPLICATION_SHA256:
        raise ValueError('Require the exact pinned IC-7300 v1.42 application')
    rows = []
    for address, expected, disassembly, meaning in WORD_EVIDENCE:
        offset = address - APP_BASE
        actual = struct.unpack_from('<I', app, offset)[0]
        if actual != expected:
            raise ValueError(f'Instruction mismatch at {address:#x}: {actual:#010x}')
        rows.append({'address': f'0x{address:08x}', 'encoding': f'0x{actual:08x}',
                     'disassembly': disassembly, 'evidence': meaning})
    for address, expected, meaning in LITERAL_EVIDENCE:
        offset = address - APP_BASE
        actual = struct.unpack_from('<I', app, offset)[0]
        if actual != expected:
            raise ValueError(f'Literal mismatch at {address:#x}: {actual:#010x}')
        rows.append({'address': f'0x{address:08x}', 'encoding': f'0x{actual:08x}',
                     'disassembly': 'literal pool word', 'evidence': meaning})
    return rows


def _harness(app, ring_name, operations):
    ring = RINGS[ring_name]
    code = [ring[operation] for operation in operations]
    code_ranges = sorted(set(code))
    size = ring['slots'] * 12 + 2
    regions = [(ring['base'], size), (SOURCE, 12), (OUTPUT, 12)]
    return Isolated(app, code_ranges, regions), ring


def ring_sequence_probe(app, ring_name, write_index, read_index, actions):
    """Run push/pop/reset sequences in private RAM, retaining state between calls."""
    if ring_name not in RINGS:
        raise ValueError('Ring must be A or B')
    ring = RINGS[ring_name]
    slots = ring['slots']
    if (type(write_index) is not int or type(read_index) is not int or
            not 0 <= write_index < slots or not 0 <= read_index < slots):
        raise ValueError(f'Ring {ring_name} indices must be in 0..{slots - 1}')
    if not isinstance(actions, (list, tuple)) or not actions:
        raise ValueError('Require a nonempty sequence of ring actions')
    for action in actions:
        if not isinstance(action, tuple) or len(action) != 2 or action[0] not in OPERATIONS:
            raise ValueError('Each action must be (reset|push|pop, payload-or-None)')
        if action[0] == 'push' and (not isinstance(action[1], bytes) or len(action[1]) != 12):
            raise ValueError('Push payloads must be exactly 12 bytes')
        if action[0] != 'push' and action[1] is not None:
            raise ValueError('Reset/pop actions do not take payloads')

    h, ring = _harness(app, ring_name, [action[0] for action in actions])
    extent = slots * 12 + 2
    before = bytearray((i * 29 + 7) & 0xff for i in range(extent))
    before[ring['write_offset']] = write_index
    before[ring['read_offset']] = read_index
    h.uc.mem_write(ring['base'], bytes(before))
    results = []
    entries = {'reset': ring['reset'][0], 'push': ring['push'][0], 'pop': ring['pop'][0]}
    for operation, payload in actions:
        if operation == 'push':
            h.uc.mem_write(SOURCE, payload)
            args = (SOURCE,)
        elif operation == 'pop':
            args = (OUTPUT,)
        else:
            args = ()
        h.uc.mem_write(OUTPUT, b'\xa5' * 12)
        result = h.run(entries[operation], args)
        data = bytes(h.uc.mem_read(ring['base'], extent))
        results.append({
            'operation': operation,
            'r0_observed': f'0x{result["r0"]:08x}',
            'write_index': data[ring['write_offset']],
            'read_index': data[ring['read_offset']],
            'output_hex': bytes(h.uc.mem_read(OUTPUT, 12)).hex() if operation == 'pop' else None,
            'slot_region_hex': data[:slots * 12].hex(),
        })
    after = bytes(h.uc.mem_read(ring['base'], extent))
    return {
        'ring': ring_name,
        'slots': slots,
        'slot_bytes': 12,
        'write_index': after[ring['write_offset']],
        'read_index': after[ring['read_offset']],
        'slot_region_before_hex': bytes(before[:slots * 12]).hex(),
        'slot_region_after_hex': after[:slots * 12].hex(),
        'actions': results,
        'private_ram_only': True,
    }


def static_summary(app):
    words = verify_image_words(app)
    return {
        'schema_version': 1,
        'application_sha256': digest(app),
        'verified_words': words,
        'rings': {
            key: {'base': f'0x{value["base"]:08x}', 'slots': value['slots'],
                  'entry_bytes': 12, 'write_cursor_offset': f'0x{value["write_offset"]:x}',
                  'read_cursor_offset': f'0x{value["read_offset"]:x}',
                  'empty_condition': 'write cursor equals read cursor',
                  'flush_effect': 'set both cursors to zero; slot bytes are untouched'}
            for key, value in RINGS.items()
        },
        'bounded_findings': [
            'Push stores three 32-bit words and advances the write cursor modulo ring size; the helper has no capacity check.',
            'Pop copies one 12-byte entry when cursors differ, otherwise writes twelve zero bytes; the helper advances the read cursor only after a nonempty pop.',
            'The separate output producer checks for at least six free entries, then appends six entries per call. That producer is not proven to belong to the voice-file worker.',
            'The DMA service pops one entry from each ring. The service path uses MMIO and is inspected statically only.',
            'The voice-file scan/state worker and stored-file reader worker use separate event objects. Static evidence does not join either worker to these two output rings.',
            'Worker handler returns reach worker cleanup/status code; this does not prove DMA drain, audible completion, queue flush, or PTT release.',
        ],
        'limits': [
            'No worker, event wait, MMIO, DMA, PTT, timing, concurrency, or physical playback was executed.',
            'Observed helper R0 values are recorded by probes but are not treated as a documented status or completion contract.',
            'Voice ownership of the two output rings, abort/flush caller association, and transmit lifecycle remain unresolved.',
        ],
    }
