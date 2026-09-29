#!/usr/bin/env python3
"""Exact-image DMA decision and receive-queue reset probes; no hardware access."""
import argparse
from pathlib import Path
import struct

from control_flow import walk
from emulate_platform import APP_BASE, RETURN, STACK, inputs
from firmware import digest, revision
from native_receive import Isolated, QUEUE, tool_hashes as receive_hashes
from recorder_interface import identity
from reporting import atomic_json

RESTART = 0x200605e4
HANDLERS = {
    # entry, ready boundary before acknowledgment, idle return block, CHSTAT, bank register
    'receive_ch3': (0x20060614, 0x2006064c, 0x200606e8, 0xe82000e4, 'R0'),
    'output_ch4': (0x20060778, 0x200607b0, 0x20060884, 0xe8200124, 'R4'),
    'input_ch5': (0x20060888, 0x200608c0, 0x20060944, 0xe8200164, 'R0'),
}


def decision_probe(app, channel, statuses):
    if channel not in HANDLERS or not isinstance(statuses, (list, tuple)) or not statuses or any(
            type(s) is not int or not 0 <= s <= 0xffffffff for s in statuses):
        raise ValueError('Require a known handler and uint32 status fixtures')
    entry, ready, idle, status_address, bank_reg = HANDLERS[channel]
    h = Isolated(app, [(entry, ready+4), (idle, idle+8), (RESTART, RESTART+4)], [(status_address, 4)])
    def stop(uc, address, size, unused):
        if address in (ready, RESTART):
            uc.emu_stop()
    h.uc.hook_add(h.u.UC_HOOK_CODE, stop)
    results = []
    for status in statuses:
        h.uc.mem_write(status_address, struct.pack('<I', status))
        h.uc.reg_write(h.a.UC_ARM_REG_SP, STACK+0xf000)
        h.uc.reg_write(h.a.UC_ARM_REG_LR, RETURN)
        before = h.count
        h.accesses.clear()
        h.uc.emu_start(entry, RETURN, timeout=1000000, count=100)
        pc = h.uc.reg_read(h.a.UC_ARM_REG_PC)
        if pc not in (RETURN, ready, RESTART):
            raise ValueError('Handler did not reach a reviewed boundary')
        if h.accesses != [(h.u.UC_MEM_READ, status_address, 4)]:
            raise ValueError('Unexpected handler register access')
        if pc in (RETURN, RESTART) and h.uc.reg_read(h.a.UC_ARM_REG_SP) != STACK+0xf000:
            raise ValueError('Idle/restart path did not restore the caller stack')
        results.append({'status': status, 'decision': 'ready' if pc == ready else 'restart' if pc == RESTART else 'idle',
                        'bank': h.uc.reg_read(getattr(h.a, 'UC_ARM_REG_'+bank_reg)) if pc == ready else None,
                        'instructions': h.count-before, 'boundary': hex(pc)})
    return results


def queue_reset_probe(app, operation, producer, consumer):
    if operation not in ('initialize', 'flush') or any(type(x) is not int or not 0 <= x < 8 for x in (producer, consumer)):
        raise ValueError('Require queue initialize/flush and indices 0..7')
    h = Isolated(app, [(0x2005fac4, 0x2005fae8)], [(QUEUE, 0x242)])
    payload = bytes((i*17+3)&255 for i in range(576))
    h.uc.mem_write(QUEUE, payload+bytes((producer, consumer)))
    result = h.run(0x2005fac4 if operation == 'initialize' else 0x2005fad8)
    after = bytes(h.uc.mem_read(QUEUE, 0x242))
    result.update(producer=after[576], consumer=after[577], payload_unchanged=after[:576] == payload,
                  writes=[{'offset': addr-QUEUE, 'size': size} for access, addr, size in h.accesses if access == h.u.UC_MEM_WRITE])
    return result


def tool_hashes():
    return dict(receive_hashes(), native_lifecycle=digest(Path(__file__).read_bytes()))


def _report(image):
    data, _, app, _ = inputs(image)
    statuses = list(range(256))+[0x80000000|s for s in (0, 1, 0x40, 0x41, 0x80, 0x81, 0xc0, 0xc1)]
    return {'image_sha256': digest(data), 'application_sha256': digest(app),
            'handler_decisions': {name: decision_probe(app, name, statuses) for name in HANDLERS},
            'queue_resets': {f'{op}_{w}_{r}': queue_reset_probe(app, op, w, r)
                             for op in ('initialize','flush') for w in range(8) for r in range(8)},
            'original_flow': {name: walk(app, APP_BASE, lo, hi) for name, lo, hi in (
                ('cold_start',0x200605fc,0x20060614), ('shared_restart',RESTART,0x200605fc),
                ('service_gate_and_dispatch',0x20005bd4,0x20005bf0))},
            'limits': ['Status words are supplied fixtures, not progressing DMA hardware.',
                       'Handler execution stops before acknowledgment/cache/data processing or at shared restart entry.',
                       'The shared restart body is statically walked; its callees and physical completion are not simulated.',
                       'Queue reset tests execute original stores only in private synthetic RAM.',
                       'Aligned direct callers are evidence, not an exhaustive indirect-call inventory.']}


def report(image):
    image = Path(image)
    initial, hashes, source = identity(image), tool_hashes(), revision()
    result = _report(image)
    if identity(image) != initial or result['image_sha256'] != initial[0] or hashes != tool_hashes() or source != revision():
        raise ValueError('Image/source changed during lifecycle analysis')
    return dict(result, source_revision=source, tool_sha256=hashes, source_unchanged=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image',type=Path);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():parser.error('Output already exists')
    result=report(args.image);args.output.parent.mkdir(parents=True,exist_ok=True);atomic_json(args.output,result)
    print(args.output)


if __name__ == '__main__':main()
