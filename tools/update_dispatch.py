#!/usr/bin/env python3
"""Read-only v1.42 component equality and bounded update-command dispatch probe."""
import argparse
from pathlib import Path
import struct

from emulate_platform import APP_BASE, engine, inputs
from firmware import digest, revision
from reporting import atomic_json
from updater_stages import header_precheck, payload_precheck

COMMANDS = {38: 0x200253f4, 39: 0x20025650, 11: 0x20025ae4}
TOOL_FILES = ('update_dispatch.py', 'emulate_platform.py', 'updater_stages.py',
              'firmware.py', 'reporting.py')


def dispatch(app, command):
    if command not in COMMANDS:
        raise ValueError('Unreviewed dispatch command')
    target = COMMANDS[command]
    machine, u, a = engine()
    machine.mem_map(0x20000000, 0x600000)
    machine.mem_write(APP_BASE, app)
    context = 0x20500000
    machine.mem_write(context + 0x44, struct.pack('<I', command))
    machine.reg_write(a.UC_ARM_REG_R4, context)
    machine.reg_write(a.UC_ARM_REG_R5, 0)
    visited = []

    def code(uc, address, width, user):
        visited.append(address)
        if address == target:
            uc.emu_stop()
        elif not 0x2002754c <= address < 0x20027714:
            raise ValueError('Unreviewed dispatch execution')

    machine.hook_add(u.UC_HOOK_CODE, code)
    machine.emu_start(0x2002754c, target + 4, count=30, timeout=1000000)
    if not visited or visited[-1] != target:
        raise ValueError('Dispatch did not reach expected callee within limits')
    return dict(command=command, callee=hex(target), reached=True,
                executed_instructions=len(visited) - 1, callee_executed=False,
                limits=dict(instructions=30, wall_seconds=1),
                modeled=['command field at synthetic context +0x44', 'private RAM/register state'])


def _report(image):
    data, _, app, _ = inputs(image)  # Exact hash/version trace gate before execution.
    import capstone
    import unicorn
    installed = [data[4 + i * 4:8 + i * 4] for i in range(3)]
    cases = [('equal', installed), ('synthetic_lower_numeric', [b'0.00'] * 3),
             ('synthetic_higher_numeric', [b'9.99'] * 3)]
    cases.extend((f'only_component_{i}_different',
                  [b'9.99' if i == j else value for j, value in enumerate(installed)])
                 for i in range(3))
    headers = {name: header_precheck(app, data, installed_ids=ids) for name, ids in cases}
    return dict(schema_version=1, image_sha256=digest(data),
                dependencies=dict(capstone=capstone.__version__, unicorn=unicorn.__version__),
                header_cases=headers,
                equal_component_payload=payload_precheck(app, data, flags=tuple(headers['equal']['component_change_flags'])),
                dispatch_cases={str(command): dispatch(app, command) for command in COMMANDS},
                same_version_reinstall_proven=False,
                limitations=[
                    'Installed component identifiers are synthetic RAM stimuli, not public Main CPU version state.',
                    'Numeric-difference cases test identifier equality behavior, not authorized downgrade acceptance.',
                    'Header/payload checks execute separately with file/hash/comparison helpers modeled.',
                    'Command state is injected; UI/event producer and command progression are unexecuted.',
                    'Dispatch stops before the callee; no coherent end-to-end installation path is simulated.',
                    'No same-version installation, custom-to-stock restoration, component writes or recovery is established.'])


def tool_hashes():
    hashes = {name: digest(Path(__file__).with_name(name).read_bytes()) for name in TOOL_FILES}
    hashes['research/targets.json'] = digest((Path(__file__).resolve().parents[1] / 'research/targets.json').read_bytes())
    return hashes


def identity(path):
    before = path.stat()
    value = digest(path.read_bytes())
    after = path.stat()
    def stamp(stat):
        return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
    if stamp(before) != stamp(after):
        raise ValueError('Image changed while hashing')
    return value, stamp(after)


def report(image):
    image = Path(image)
    initial = identity(image)
    hashes, source = tool_hashes(), revision()
    result = _report(image)
    if identity(image) != initial or result['image_sha256'] != initial[0]:
        raise ValueError('Image changed during dispatch analysis')
    if hashes != tool_hashes() or source != revision():
        raise ValueError('Source changed during dispatch analysis')
    return dict(result, source_revision=source, tool_sha256=hashes, source_unchanged=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output exists; choose a new evidence file')
    result = report(args.image)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(args.output, result)
    print(f'Bounded dispatch evidence: {args.output}')


if __name__ == '__main__':
    main()
