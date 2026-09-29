#!/usr/bin/env python3
"""Exact-image offline probes of CPU state publication and DSP command gates."""
import argparse
from pathlib import Path
import struct

from emulate_platform import STACK, inputs
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


def tool_hashes():
    return dict(receive_hashes(), native_dsp_controls=digest(Path(__file__).read_bytes()))


def _report(image):
    data, _, app, _ = inputs(image)
    cases = [(p, s, o, a, b) for p in (0, 1, 255) for s in range(256)
             for o in (0, 32, 255) for a, b in ((0, 255), (255, 0))]
    return {'image_sha256': digest(data), 'application_sha256': digest(app),
            'gates': gate_probe(app, cases), 'publication': publication_probe(app, list(range(256))),
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
