#!/usr/bin/env python3
"""Exact-image offline probes of CPU state publication and DSP command gates."""
import argparse
from pathlib import Path
import struct

from emulate_platform import APP_BASE, SOURCE, STACK, inputs
from firmware import digest, revision
from native_receive import Isolated, tool_hashes as receive_hashes
from recorder_interface import identity
from reporting import atomic_json

FLAGS = 0x203906c8
PENDING = 0x2039071c
OTHER = 0x2039071f
STATE = 0x2039077e
UI_STATE = 0x203903f0
SHARED_STATE = 0x203def59
LEVEL_SETTINGS = {76: ('ACC/USB Output Select', 0x203de518),
                  77: ('ACC/USB AF Output Level', 0x203de519),
                  80: ('ACC/USB IF Output Level', 0x203de51c)}


def byte(value):
    if type(value) is not int or not 0 <= value <= 255:
        raise ValueError('Require integer byte fixtures')
    return value


def gate_probe(app, cases):
    """Refresh cached flags, then execute the original command prefix packer.

    Cases contain (pending, state, other, previous_flag0, previous_flag1).
    The update tail's command-packer branch is replaced by an explicit boundary:
    the intervening full packer and its other fields are not executed.
    """
    if not isinstance(cases, (list, tuple)) or not cases:
        raise ValueError('Require nonempty gate fixtures')
    for case in cases:
        if not isinstance(case, (list, tuple)) or len(case) != 5:
            raise ValueError('Require five byte values per gate fixture')
        for value in case:
            byte(value)
    h = Isolated(app, [(0x200b232c, 0x200b2378), (0x200b1a1c, 0x200b1a70)],
                 [(FLAGS-1, 5), (PENDING, 1), (OTHER, 1), (STATE, 1)])
    stack = STACK+0xf000
    rows = []
    for pending, state, other, old0, old1 in cases:
        h.uc.mem_write(PENDING, bytes([pending]))
        h.uc.mem_write(STATE, bytes([state]))
        h.uc.mem_write(OTHER, bytes([other]))
        h.uc.mem_write(FLAGS-1, bytes([0xa5, old0, old1, 0x5a, 0xa5]))
        h.accesses.clear()
        refresh = h.run(0x200b232c, stop=0x200b2374 if pending else 0x200b2378)
        snapshot = bytes(h.uc.mem_read(FLAGS-1, 5))
        writes = [(a, n) for kind, a, n in h.accesses if kind == h.u.UC_MEM_WRITE]
        expected_writes = [(PENDING, 1), (FLAGS, 1), (FLAGS+1, 1), (FLAGS+2, 1)] if pending else []
        if writes != expected_writes or snapshot[0] != 0xa5 or snapshot[-1] != 0xa5:
            raise ValueError('Unexpected flag refresh write footprint')
        if bytes(h.uc.mem_read(PENDING, 1)) != b'\0':
            raise ValueError('Pending refresh was not consumed')
        h.uc.mem_write(stack+8, b'\xa5'*12)
        h.uc.reg_write(h.a.UC_ARM_REG_R1, FLAGS)
        h.accesses.clear()
        packed = h.run(0x200b1a1c, stop=0x200b1a70)
        if any(kind == h.u.UC_MEM_WRITE for kind, _, _ in h.accesses):
            raise ValueError('Command prefix modified non-stack state')
        if bytes(h.uc.mem_read(stack+8, 4))+bytes(h.uc.mem_read(stack+16, 4)) != b'\xa5'*8:
            raise ValueError('Command prefix stack guard changed')
        if bytes(h.uc.mem_read(STATE, 1)) != bytes([state]) or bytes(h.uc.mem_read(OTHER, 1)) != bytes([other]):
            raise ValueError('Input state changed')
        rows.append({'pending': pending, 'state': state, 'other': other,
                     'previous_flags': [old0, old1, 0x5a], 'refreshed_flags': list(snapshot[1:4]),
                     'command_prefix': struct.unpack('<I', h.uc.mem_read(stack+12, 4))[0],
                     'refresh_instructions': refresh['instructions'], 'pack_instructions': packed['instructions']})
    return rows


def publication_probe(app, values):
    if not isinstance(values, (list, tuple)) or not values:
        raise ValueError('Require nonempty state fixtures')
    for value in values:
        byte(value)
    h = Isolated(app, [(0x200523f8, 0x20052404)], [(UI_STATE, 1), (SHARED_STATE-1, 3)])
    rows = []
    for value in values:
        h.uc.mem_write(UI_STATE, bytes([value]))
        h.uc.mem_write(SHARED_STATE-1, b'\xa5\x5a\xa5')
        h.uc.reg_write(h.a.UC_ARM_REG_R4, 0x203def28)
        h.accesses.clear()
        h.run(0x200523f8, stop=0x20052404)
        result = bytes(h.uc.mem_read(SHARED_STATE-1, 3))
        writes = [(a, n) for kind, a, n in h.accesses if kind == h.u.UC_MEM_WRITE]
        if writes != [(SHARED_STATE, 1)] or result[0] != 0xa5 or result[2] != 0xa5:
            raise ValueError('Unexpected state publication footprint')
        rows.append({'input': value, 'published': result[1]})
    return rows


def level_settings_probe(app):
    h = Isolated(app, [(0x20086000, 0x20086098)], [(SOURCE, 12)])
    rows = []
    for index, (label, address) in LEVEL_SETTINGS.items():
        h.uc.mem_write(SOURCE, bytes(8)+struct.pack('<BBH', 2, 0, index))
        h.accesses.clear()
        result = h.run(0x20086000, (SOURCE, 0, 0, 0))
        fields = struct.unpack_from('<16I', app, 0x20190ecc+index*64-APP_BASE)
        offset = result['r0']-APP_BASE
        if (fields[0] != address or result['r0'] != fields[10] or
                app[offset:offset+len(label)+1] != label.encode()+b'\0' or
                any(k == h.u.UC_MEM_WRITE for k, _, _ in h.accesses)):
            raise ValueError('Unexpected ACC/USB setting descriptor')
        rows.append({'index': index, 'label': label, 'address': address})
    return rows


def level_probe(app, cases):
    """Cases: (output_select, AF level, IF level, command high byte, low byte).

    Executes the level helper including original interpolation/division, then
    separate publication and command-packing slices. Does not submit commands.
    """
    if not isinstance(cases, (list, tuple)) or not cases:
        raise ValueError('Require nonempty level fixtures')
    for case in cases:
        if not isinstance(case, (list, tuple)) or len(case) != 5:
            raise ValueError('Require five byte values per level fixture')
        for value in case:
            byte(value)
    settings, cache, shared, command = 0x203de518, 0x20390101, 0x203def28, 0x20414cc4
    h = Isolated(app, [(0x2001fb98, 0x2001fbfc), (0x2000621c, 0x20006288),
                      (0x2017c618, 0x2017c644), (0x200b2120, 0x200b2148)],
                 [(settings, 5), (cache-1, 3), (shared, 17), (command-1, 6)])
    rows = []
    for select, af, intermediate, high, low in cases:
        source = bytes([select, af, 0xa5, 0x5a, intermediate])
        state = bytearray(b'\xa5'*17)
        state[2], state[15] = low, high
        h.uc.mem_write(settings, source)
        h.uc.mem_write(cache-1, b'\xa5\xcc\x5a')
        h.uc.mem_write(shared, bytes(state))
        h.uc.mem_write(command-1, b'\xa5'*6)
        h.accesses.clear()
        h.run(0x2001fb98)
        level = bytes(h.uc.mem_read(cache, 1))[0]
        h.run(0x2001fbe8)
        h.uc.reg_write(h.a.UC_ARM_REG_R4, shared)
        h.uc.reg_write(h.a.UC_ARM_REG_R11, command-0x3c)
        h.uc.mem_write(STACK+0xf008, b'\xa5'*12)
        h.run(0x200b2120, stop=0x200b2148)
        state[14] = level
        writes = [(a, n) for k, a, n in h.accesses if k == h.u.UC_MEM_WRITE]
        packed = bytes(h.uc.mem_read(command-1, 6))
        if (writes != [(cache, 1), (shared+14, 1), (command, 4)] or
                bytes(h.uc.mem_read(cache-1, 3)) != bytes([0xa5, level, 0x5a]) or
                bytes(h.uc.mem_read(shared, 17)) != bytes(state) or
                bytes(h.uc.mem_read(settings, 5)) != source or
                packed[0] != 0xa5 or packed[-1] != 0xa5 or
                bytes(h.uc.mem_read(STACK+0xf008, 4))+bytes(h.uc.mem_read(STACK+0xf010, 4)) != b'\xa5'*8):
            raise ValueError('Unexpected ACC/USB level write footprint')
        rows.append({'output_select': select, 'af_level': af, 'if_level': intermediate,
                     'high_byte': high, 'low_byte': low, 'mapped_level': level,
                     'command': struct.unpack('<I', packed[1:5])[0]})
    return rows


def tool_hashes():
    return dict(receive_hashes(), native_dsp_controls=digest(Path(__file__).read_bytes()))


def _report(image):
    data, _, app, _ = inputs(image)
    cases = [(p, s, o, a, b) for p in (0, 1, 255) for s in range(256)
             for o in (0, 32, 255) for a, b in ((0, 255), (255, 0))]
    levels = [(s, x if s == 0 else other, other if s == 0 else x, 0xa5, 0x5a)
              for s in (0, 1, 128, 255) for x in range(256) for other in (0, 128, 255)]
    return {'image_sha256': digest(data), 'application_sha256': digest(app),
            'gates': gate_probe(app, cases), 'publication': publication_probe(app, list(range(256))),
            'level_settings': level_settings_probe(app), 'levels': level_probe(app, levels),
            'limits': ['Original CPU slices with synthetic state, not a whole-task or DSP execution.',
                       'Refresh and packing are separate bounded calls; intervening command construction and submission are not executed.',
                       'No physical TX/RX label, timer units, serializer identity or control-independent audio gain is established.',
                       'No radio, PTT, peripheral or firmware-write interface is opened.']}


def report(image):
    image = Path(image)
    initial, hashes, source = identity(image), tool_hashes(), revision()
    result = _report(image)
    if identity(image) != initial or result['image_sha256'] != initial[0] or hashes != tool_hashes() or source != revision():
        raise ValueError('Image/source changed during DSP control analysis')
    return dict(result, source_revision=source, tool_sha256=hashes, source_unchanged=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output already exists')
    result = report(args.image)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(args.output, result)
    print(args.output)


if __name__ == '__main__':
    main()
