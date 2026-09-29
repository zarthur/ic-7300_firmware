#!/usr/bin/env python3
"""Offline original-v1.42 timer probes; MMIO is synthetic memory, never hardware."""
import argparse
import importlib.metadata
from pathlib import Path
import struct

from control_flow import walk
from emulate_platform import APP_BASE, inputs
from firmware import digest, revision
from native_receive import Isolated, tool_hashes as receive_hashes
from recorder_interface import identity
from reporting import atomic_json

OSTM0 = 0xfcfec000
OSTM1 = 0xfcfec400
CLOCK_GATE = 0xfcfe0428
MTU3 = 0xfcff0200
TICK = 0x20390a78
ROUTINES = {
    'scheduler_timer_setup': (0x200b93b0, 0x200b93e4, 'ARM'),
    'delay_timer_setup': (0x20005d2c, 0x20005d58, 'ARM'),
    'delay_timer_stop': (0x20005dc8, 0x20005dd8, 'ARM'),
    'delay_timer_start': (0x20005d78, 0x20005d88, 'ARM'),
    'delay_predicate': (0x20005d88, 0x20005dc8, 'ARM'),
    'scheduler_increment': (0x2018809a, 0x201880a4, 'Thumb'),
    'audio_compare_advance': (0x20005bf4, 0x20005c04, 'ARM'),
}


def uint32(value):
    if type(value) is not int or not 0 <= value <= 0xffffffff:
        raise ValueError('Require an unsigned 32-bit synthetic value')
    return value


def delay_probe(app, microseconds, counter):
    uint32(microseconds)
    uint32(counter)
    h = Isolated(app, [(0x20005d88, 0x20005dc8)], [(OSTM1+4, 4)])
    # Original routine uses VFP double conversion/multiply/divide. Enable the
    # emulator's coprocessor execution; this does not measure target CPU time.
    h.uc.reg_write(h.a.UC_ARM_REG_C1_C0_2, 0xf << 20)
    h.uc.reg_write(h.a.UC_ARM_REG_FPEXC, 1 << 30)
    h.uc.mem_write(OSTM1+4, struct.pack('<I', counter))
    result = h.run(0x20005d88, (microseconds,))
    result.update(microseconds=microseconds, counter=counter,
                  threshold=h.uc.reg_read(h.a.UC_ARM_REG_R1),
                  writes=sum(access == h.u.UC_MEM_WRITE for access, _, _ in h.accesses))
    return result


def register_probe(app, name):
    if name not in ('scheduler_timer_setup', 'delay_timer_setup', 'delay_timer_stop', 'delay_timer_start'):
        raise ValueError('Unsupported isolated register routine')
    start, end, _ = ROUTINES[name]
    h = Isolated(app, [(start, end)],
                 [(CLOCK_GATE, 1), (OSTM0, 4),
                  (OSTM0+0x14, 1), (OSTM0+0x18, 1), (OSTM0+0x20, 1),
                  (OSTM1+0x14, 1), (OSTM1+0x18, 1), (OSTM1+0x20, 1)])
    h.uc.mem_write(CLOCK_GATE, b'\xff')
    writes = []
    def record(uc, access, address, size, value, unused):
        writes.append({'address': hex(address), 'size': size, 'value': value})
    h.uc.hook_add(h.u.UC_HOOK_MEM_WRITE, record)
    result = h.run(start)
    result.update(writes=writes, modeled='Register storage only; no timer progression or interrupts')
    return result


def increment_probe(app, name, before):
    uint32(before)
    if name not in ('scheduler_increment', 'audio_compare_advance'):
        raise ValueError('Unsupported bounded increment block')
    size, address = (4, TICK) if name == 'scheduler_increment' else (2, MTU3+0x18)
    if before >= 1 << (size*8):
        raise ValueError('Value exceeds register width')
    start, end, mode = ROUTINES[name]
    h = Isolated(app, [(start, end)], [(address, size)])
    h.uc.mem_write(address, before.to_bytes(size, 'little'))
    result = h.run(start | (mode == 'Thumb'), stop=end)
    result.update(before=before, after=int.from_bytes(h.uc.mem_read(address, size), 'little'),
                  boundary='Only increment block; surrounding interrupt/task execution excluded')
    return result


def tool_hashes():
    return dict(receive_hashes(), **{'native_timing.py': digest(Path(__file__).read_bytes())})


def _report(image):
    data, _, app, _ = inputs(image)
    cases = [(us, ticks) for us in (0, 1, 10, 250, 1000, 1000000)
             for ticks in sorted({max(0, 32*us-1), 32*us, 32*us+1})]
    return {
        'schema_version': 1, 'image_sha256': digest(data), 'application_sha256': digest(app),
        'dependencies': {n: importlib.metadata.version(n) for n in ('capstone','unicorn')},
        'static_flows': {name: walk(app, APP_BASE, start, end, mode=mode)
                         for name, (start,end,mode) in ROUTINES.items()},
        'register_sequences': {name: register_probe(app, name) for name in ROUTINES
                               if name.endswith(('_setup','_start','_stop'))},
        'delay_cases': [delay_probe(app, us, counter) for us,counter in cases],
        'scheduler_increments': [increment_probe(app, 'scheduler_increment', value)
                                 for value in (0, 0xfffffffe, 0xffffffff)],
        'compare_increments': [increment_probe(app, 'audio_compare_advance', value)
                              for value in (0, 57535, 57536, 65535)],
        'limitations': ['MMIO is isolated synthetic storage, not simulated timer hardware.',
                       '32 MHz is the original delay routine\'s conversion, not measured frequency.',
                       'Bounded increment blocks do not prove interrupt delivery, atomic timestamp reads or UTC.',
                       'No timestamped target diagnostic capture has been collected.'],
    }


def report(image):
    image = Path(image)
    initial, hashes, source = identity(image), tool_hashes(), revision()
    result = _report(image)
    if identity(image) != initial or result['image_sha256'] != initial[0] or hashes != tool_hashes() or source != revision():
        raise ValueError('Image/source changed during native timing analysis')
    return dict(result, source_revision=source, tool_sha256=hashes, source_unchanged=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output exists; choose a new evidence path')
    result = report(args.image)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(args.output, result)
    print(f'Native timing evidence: {args.output}')


if __name__ == '__main__':
    main()
