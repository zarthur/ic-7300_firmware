#!/usr/bin/env python3
"""Bounded v1.42 control-flow observations, not complete function recovery."""
import argparse
import json
from pathlib import Path
import struct
import sys
from control_flow import walk
from firmware import checked_image, digest, lzss, parse, revision

BASE = 0x20005000
# Explicit code intervals stop before known literal pools. Other boundaries are
# investigative windows, not declarations of complete functions.
WINDOWS = [('updater_first_digest', 0x20025800, 0x20025878),
           ('updater_second_digest', 0x20025920, 0x20025970),
           ('updater_destination', 0x20025d80, 0x20025e40),
           ('updater_final_digest', 0x20026030, 0x20026080),
           ('application_startup', 0x20005050, 0x200050c0)]


def observe(data, base, start, end, mode='ARM'):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB, CS_GRP_JUMP, CS_GRP_CALL
    from capstone.arm import ARM_OP_IMM, ARM_OP_REG, ARM_OP_MEM, ARM_REG_PC
    if mode not in ('ARM', 'Thumb') or not base <= start < end <= base+len(data):
        raise ValueError('Invalid code window')
    cs = Cs(CS_ARCH_ARM, CS_MODE_ARM if mode == 'ARM' else CS_MODE_THUMB)
    cs.detail = True
    edges, literals, markers = [], [], []
    previous_literal = None
    count = 0
    for ins in cs.disasm(data[start-base:end-base], start):
        count += 1
        is_flow = ins.group(CS_GRP_JUMP) or ins.group(CS_GRP_CALL)
        if is_flow:
            edge = {'address': hex(ins.address), 'mode': mode, 'instruction': ins.mnemonic,
                    'confidence': 'decoded instruction; reachability not established'}
            op = ins.operands[-1] if ins.operands else None
            if op and op.type == ARM_OP_IMM:
                target = op.imm
                target_mode = ('Thumb' if mode == 'ARM' else 'ARM') if ins.mnemonic == 'blx' else mode
                edge.update(target=hex(target & ~1), target_mode=target_mode, resolution='immediate')
            elif (op and op.type == ARM_OP_REG and previous_literal and
                  previous_literal[0] == op.reg and previous_literal[2] == ins.address):
                target = previous_literal[1]
                edge.update(target=hex(target & ~1), target_mode='Thumb' if target & 1 else 'ARM',
                            resolution='adjacent literal load candidate')
            else:
                edge.update(target=None, target_mode=None, resolution='unresolved indirect')
            edges.append(edge)
        if ins.mnemonic in ('svc', 'msr') or any(op.type == ARM_OP_REG and cs.reg_name(op.reg) == 'sp' for op in ins.operands):
            markers.append({'address': hex(ins.address), 'instruction': ins.mnemonic})
        previous_literal = None
        if ins.mnemonic in ('ldr', 'ldr.w') and len(ins.operands) == 2:
            dst, src = ins.operands
            if src.type == ARM_OP_MEM and src.mem.base == ARM_REG_PC:
                pc = ins.address+8 if mode == 'ARM' else (ins.address+4) & ~3
                pool = pc+src.mem.disp
                if base <= pool <= base+len(data)-4:
                    value = struct.unpack_from('<I', data, pool-base)[0]
                    literals.append({'address': hex(ins.address), 'pool': hex(pool), 'value': hex(value)})
                    previous_literal = (dst.reg, value, ins.address+ins.size)
    return {'start': hex(start), 'end': hex(end), 'mode': mode, 'instructions': count, 'window_sha256': digest(data[start-base:end-base]),
            'edges': edges, 'literal_loads': literals, 'runtime_markers': markers,
            'limitation': 'Bounded linear window; conditional paths and callee effects require review'}


def report(image):
    import capstone
    data = checked_image(image, 'trace')
    main = parse(data)[0]
    payload = data[main['offset']:main['offset']+main['size']]
    app, consumed = lzss(payload[0x10004:], struct.unpack_from('<I', payload, 0x10000)[0])
    windows = [{'name': name, **observe(app, BASE, start, end)} for name, start, end in WINDOWS]
    windows.append({'name': 'loader_selection', **observe(payload[0x4000:0x4650], 0x20004000,
                                                         0x20004380, 0x20004400)})
    # Follow only literal-resolved startup transitions, with explicit ISA state.
    startup = next(w for w in windows if w['name'] == 'application_startup')
    for edge in startup['edges']:
        if edge['resolution'] == 'adjacent literal load candidate':
            target = int(edge['target'], 16)
            if BASE <= target <= BASE+len(app)-32:
                windows.append({'name': 'startup_callee_candidate',
                                **observe(app, BASE, target, target+32, edge['target_mode'])})
    for name, start, end, mode in [
        ('update_transfer_candidate', 0x20024db8, 0x20024ef0, 'ARM'),
        ('runtime_init_table_candidate', 0x2017ccf8, 0x2017cd14, 'Thumb'),
        ('runtime_service_candidate', 0x20186d2c, 0x20186d52, 'Thumb'),
        ('runtime_object_candidate', 0x20187044, 0x2018707c, 'Thumb'),
        ('runtime_start_candidate', 0x20186d58, 0x20186d9c, 'Thumb'),
        ('runtime_init_branch', 0x200b8690, 0x200b86a0, 'ARM')]:
        windows.append({'name': name, **observe(app, BASE, start, end, mode)})
    flows = {name: walk(app, BASE, start, end) for name, start, end in [
        ('transfer', 0x20024db8, 0x20024ef8),
        ('flash_erase_candidate', 0x20024bb8, 0x20024cd0),
        ('flash_program_candidate', 0x20024a60, 0x20024bb8),
        ('persistent_record_write', 0x20024d60, 0x20024db8),
        ('magic_trailer_check', 0x200247e4, 0x20024850),
        ('header_precheck', 0x200253f4, 0x20025604),
        ('payload_integrity', 0x20025650, 0x20025ae4),
        ('main_update', 0x20025ae4, 0x20026130)]}
    flows['loader_decode'] = walk(payload[0x4000:0x4650], 0x20004000, 0x2000425c, 0x20004334)
    return {'schema_version': 2, 'control_flow': flows, 'source_revision': revision(),
            'image_sha256': digest(data), 'application_sha256': digest(app),
            'tools': {'python': sys.version.split()[0], 'capstone': capstone.__version__},
            'tool_sha256': {name: digest(Path(__file__).with_name(name).read_bytes())
                            for name in ('platform_evidence.py', 'firmware.py', 'control_flow.py')},
            'application_compressed_bytes': consumed, 'windows': windows,
            'runtime_initialization': [dict(table_entry=hex(address), source=hex(values[0]),
                destination=hex(values[1]), length=values[2], function=hex(values[3]),
                interpretation='copy' if values[3]==0x20186478 else 'zero-fill candidate')
                for address in range(0x20360aac,0x20360adc,16)
                for values in [struct.unpack_from('<4I',app,address-BASE)]],
            'unresolved': ['physical controller completion/error semantics', 'DSP/FPGA update paths and interrupted writes',
                           'application-independent recovery and physical bank contents', 'compressed capacity',
                           'display-only patch region', 'heap/task APIs and runtime headroom']}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('image', type=Path); p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    try:
        result = report(args.image)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2)+'\n')
    except (ValueError, OSError, KeyError, struct.error) as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
