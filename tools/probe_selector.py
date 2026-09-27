#!/usr/bin/env python3
"""Local bounded selector-candidate semantics probe; no hardware I/O."""
import argparse
import json
from pathlib import Path
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
parser.add_argument('--image', type=Path)
args = parser.parse_args()
repo = args.repo.resolve()
sys.path.insert(0, str(repo / 'tools'))
from emulate_platform import inputs, APP_BASE
from firmware import digest
import capstone
import unicorn
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_R0

image = args.image or repo / 'artifacts/original/7300_142.dat'
data, _, app, _ = inputs(image)
rows = []
for address in (0x2015cc4c, 0x2015d600, 0x2015daa8, 0x2015e110, 0x2015e504):
    code = app[address - APP_BASE:address - APP_BASE + 4]
    instruction = next(capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_THUMB).disasm(code, address))
    if instruction.size != 4:
        raise ValueError('Unexpected instruction boundary')
    for value in (0, 0x12345678, 0xffffffff):
        machine = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        machine.mem_map(address & ~4095, 4096)
        machine.mem_write(address, code)
        machine.reg_write(UC_ARM_REG_R0, value)
        events = []
        machine.hook_add(UC_HOOK_MEM_READ | UC_HOOK_MEM_WRITE,
                         lambda uc, access, pointer, size, val, user: events.append((access, pointer, size)))
        machine.emu_start(address | 1, address + 4, count=1, timeout=1000000)
        expected = value & 0xff0000 if address == 0x2015cc4c else value | 0xff0000
        actual = machine.reg_read(UC_ARM_REG_R0)
        rows.append(dict(address=hex(address), initial_r0=hex(value), expected_r0=hex(expected),
                         actual_r0=hex(actual), data_memory_events=len(events),
                         passed=actual == expected and not events))
report = dict(image_sha256=digest(data), versions=dict(capstone=capstone.__version__, unicorn=unicorn.__version__),
              trials=rows, passed=all(row['passed'] for row in rows),
              uncertainties=['Thumb mode and exact entry boundary are supplied, not established by startup execution.',
                             'Single-instruction semantics do not prove normal runtime reachability or rule out data interpretation.',
                             'No complete selector-block ownership, physical memory effects, recovery or packing qualification follows.'])
print(json.dumps(report, indent=2))
raise SystemExit(0 if report['passed'] else 1)
