#!/usr/bin/env python3
"""Read-only, exact-v1.42 display-label investigation; never emits a firmware image.

The modeled menu trace stops at the renderer entry; separate bounded probes run
its original ASCII converter. Neither qualifies a patch or proves live UI state.
"""
import argparse
import importlib.metadata
import json
from pathlib import Path
import re
import struct

from firmware import checked_image, digest, lzss, parse, require_target, revision
from reporting import atomic_json

BASE = 0x20005000
LABEL = 0x2035A76C
TABLE = 0x2018FE24
INDEX = 41
RECORD_SIZE = 24
TEXT = b'Information'
APP_SHA256 = '4686728c9d1f7249b6278a29686a40b8fa5e527bd2428a76a33cd9395178c9a4'
RENDERER = 0x200AC6E0


def describe_site(app):
    """Check structural preimages; callers must separately verify exact-image identity."""
    offset = LABEL - BASE
    if app[offset:offset + len(TEXT) + 1] != TEXT + b'\0':
        raise ValueError('Label/terminator preimage differs')
    record = TABLE + INDEX * RECORD_SIZE
    if len(app) < record - BASE + RECORD_SIZE:
        raise ValueError('Truncated descriptor')
    words = struct.unpack_from('<6I', app, record - BASE)
    expected = (0x20042F3C, 0x01010009, 0x2035A3CC, LABEL, 0x2035AA24, 0x2035AA24)
    if words != expected:
        raise ValueError('Menu descriptor preimage differs')
    pointers = {hex(address): [hex(BASE + m.start()) for m in
        re.finditer(re.escape(struct.pack('<I', address)), app)]
        for address in range(LABEL, LABEL + len(TEXT) + 1)}
    return dict(text=TEXT.decode(), address=hex(LABEL), decoded_offset=hex(offset),
                interval=[hex(LABEL), hex(LABEL + len(TEXT))], byte_length=len(TEXT),
                terminator=hex(LABEL + len(TEXT)), pointer_occurrences=pointers,
                descriptor=dict(table=hex(TABLE), index=INDEX, stride=RECORD_SIZE,
                    address=hex(record), callback=hex(words[0]), category=9, subtype=0,
                    title_pointer=hex(words[2]), english_label_pointer=hex(words[3]),
                    japanese_title_pointer=hex(words[4]), japanese_label_pointer=hex(words[5])))


def probe_original_menu(app, *, through_wrapper=False):
    """Execute original code with synthetic menu state, stopping before drawing."""
    if digest(app) != APP_SHA256:
        raise ValueError('Menu execution requires the exact pinned v1.42 application')
    from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_PROT_READ, UC_PROT_EXEC
    from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
        UC_ARM_REG_R3, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_SP, UC_ARM_REG_LR)
    machine = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    machine.mem_map(BASE, (len(app) + 4095) & ~4095)
    machine.mem_write(BASE, app)
    machine.mem_protect(BASE, (len(app) + 4095) & ~4095, UC_PROT_READ | UC_PROT_EXEC)
    scratch = 0x21000000
    machine.mem_map(scratch, 0x10000)
    # Nonzero scratch makes the wrapper's explicit zero offset store observable.
    machine.mem_write(scratch, b'\xA5' * 0x10000)
    context, stack = scratch + 0x100, scratch + 0x8000
    machine.mem_write(context + 8, b'\x01\x00' + struct.pack('<H', INDEX))
    machine.mem_write(stack, struct.pack('<III', 10, 20, 0))
    registers = (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3)
    for reg, value in zip(registers, (context, 0, 0, 0)):
        machine.reg_write(reg, value)
    machine.reg_write(UC_ARM_REG_SP, stack)
    machine.reg_write(UC_ARM_REG_LR, scratch + 0xFF00)
    instruction_count = 0
    label_reads = []
    sink = {}
    stops = {RENDERER}
    reached = []
    selected_offsets = []
    allowed = ((0x20086510, 0x2008653C), (0x20086100, 0x200861BC),
               (0x20086000, 0x20086098), (0x20080790, 0x200807CC),
               (0x2008A4DC, 0x2008A4F0), (0x2008A654, 0x2008A66C))

    def instruction(uc, address, size, unused):
        nonlocal instruction_count
        instruction_count += 1
        if address in stops:
            reached.append(address)
            if address == RENDERER:
                sink.update({f'r{i}': uc.reg_read(reg) for i, reg in enumerate(registers)})
            uc.emu_stop()
            return
        if not any(lo <= address < hi for lo, hi in allowed):
            raise ValueError(f'Unexpected menu execution target: {address:#x}')
        if address == 0x20086000:
            selected_offsets.append(uc.reg_read(UC_ARM_REG_R3))

    def read(uc, access, address, size, value, unused):
        if LABEL <= address < LABEL + len(TEXT) + 1:
            label_reads.append(dict(address=hex(address), size=size))

    machine.hook_add(UC_HOOK_CODE, instruction)
    machine.hook_add(UC_HOOK_MEM_READ, read)
    entry = 0x20086510 if through_wrapper else 0x20086100
    machine.emu_start(entry, scratch + 0xFF00, count=500)
    if sink.get('r2') != LABEL or sink.get('r3') != len(TEXT):
        raise ValueError('Original menu trace did not reach the expected text/length sink')
    # Read the actual descriptor subtype via original instructions, then execute
    # the original subtype switch. Subtype 1 has a first-byte icon consumer;
    # this record's subtype 0 takes the ordinary text wrapper instead.
    machine.reg_write(UC_ARM_REG_R5, context)
    stops.clear(); stops.add(0x2008A4F0)
    machine.emu_start(0x2008A4DC, scratch + 0xFF00, count=30)
    if not reached or reached[-1] != 0x2008A4F0:
        raise ValueError('Subtype descriptor load did not complete')
    subtype = machine.reg_read(UC_ARM_REG_R6)
    stops.clear(); stops.update((0x2008A70C, 0x2008A6EC, 0x2008AA4C))
    machine.emu_start(0x2008A654, scratch + 0xFF00, count=10)
    if subtype != 0 or reached[-1] != 0x2008A70C:
        raise ValueError('Unexpected subtype dispatch')
    return dict(outcome='PASS', original_instruction_count=instruction_count,
        modeled_inputs=dict(row=0, language_selector=0, menu_type=1, descriptor_index=INDEX,
                            text_offset=None if through_wrapper else 0,
                            coordinates=None if through_wrapper else [10, 20]),
        wrapper_forces_zero_offset=through_wrapper and selected_offsets == [0],
        observed_selector_offsets=selected_offsets,
        wrapper_coordinates=[10, 38] if through_wrapper else None,
        entry=hex(entry), selector='0x20086000', bounded_length='0x20080790',
        length_bound=128, stopped_before_renderer=hex(RENDERER),
        renderer_arguments={key: hex(value) for key, value in sink.items()},
        label_reads=label_reads, subtype=subtype, subtype_dispatch=hex(reached[-1]),
        ordinary_wrapper='0x20086510', excluded_known_icon_wrapper='0x20086484',
        hardware_modeled=False, live_menu_state_observed=False, renderer_executed=False)



def probe_original_ascii_parser(app):
    """Run the original byte-to-codepoint routine on two bounded plain-ASCII cases.

    The second input is a separate synthetic scratch buffer, never an application
    edit. Font selection, glyph metrics and drawing are deliberately not modeled.
    """
    if digest(app) != APP_SHA256:
        raise ValueError('ASCII execution requires the exact pinned v1.42 application')
    from unicorn import (Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE,
        UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE, UC_PROT_READ, UC_PROT_EXEC)
    from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_SP, UC_ARM_REG_LR
    cases = []
    for name, text in (('original_label', TEXT), ('synthetic_ascii', b'Custom info')):
        machine = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        span = (len(app) + 4095) & ~4095
        machine.mem_map(BASE, span)
        machine.mem_write(BASE, app)
        machine.mem_protect(BASE, span, UC_PROT_READ | UC_PROT_EXEC)
        scratch = 0x21000000
        machine.mem_map(scratch, 0x10000)
        pointer = LABEL if name == 'original_label' else scratch + 0x1000
        if name != 'original_label':
            machine.mem_write(pointer, text + b'\0')
        output, stack, sentinel = scratch + 0x4000, scratch + 0x8000, scratch + 0xF000
        machine.mem_write(output, b'\xA5' * 64)
        for reg, value in ((UC_ARM_REG_R0, pointer), (UC_ARM_REG_R1, len(text)),
                (UC_ARM_REG_R2, output), (UC_ARM_REG_SP, stack), (UC_ARM_REG_LR, sentinel)):
            machine.reg_write(reg, value)
        instructions, reads, writes, branches = [], [], [], []

        def code(uc, address, size, unused):
            if not (0x200AE0B8 <= address < 0x200AE190 or 0x200BCB40 <= address < 0x200BCB74):
                raise ValueError(f'Outside reviewed ASCII parser bounds: {address:#x}')
            instructions.append(address)
            if address == 0x200BCB5C:
                branches.append(address)

        def read(uc, access, address, size, value, unused):
            if pointer <= address < pointer + len(text) + 1:
                reads.append(dict(offset=address - pointer, size=size))
            elif not (stack - 256 <= address and address + size <= stack):
                raise ValueError(f'Unexpected ASCII data read: {address:#x}')

        def write(uc, access, address, size, value, unused):
            if output <= address and address + size <= output + 2 * len(text):
                writes.append(dict(offset=address - output, size=size))
            elif not (stack - 256 <= address and address + size <= stack):
                raise ValueError(f'Unexpected ASCII data write: {address:#x}')

        machine.hook_add(UC_HOOK_CODE, code)
        machine.hook_add(UC_HOOK_MEM_READ, read)
        machine.hook_add(UC_HOOK_MEM_WRITE, write)
        machine.emu_start(0x200AE0B8, sentinel, count=2000)
        from unicorn.arm_const import UC_ARM_REG_PC
        if machine.reg_read(UC_ARM_REG_PC) != sentinel:
            raise ValueError('ASCII parser did not return within its instruction budget')
        count = machine.reg_read(UC_ARM_REG_R0)
        points = list(struct.unpack('<' + 'H' * len(text), machine.mem_read(output, 2 * len(text))))
        if count != len(text) or points != list(text) or len(branches) != len(text):
            raise ValueError('ASCII codepoint conversion differs')
        if bytes(machine.mem_read(output + 2 * len(text), 64 - 2 * len(text))) != b'\xA5' * (64 - 2 * len(text)):
            raise ValueError('ASCII output guard changed')
        cases.append(dict(name=name, text=text.decode('ascii'), input_location='original application' if name == 'original_label' else 'separate synthetic scratch buffer',
            byte_length=len(text), returned_codepoints=count, codepoints=points,
            direct_ascii_branches=len(branches), original_instructions=len(instructions),
            input_reads=reads, output_writes=writes, guard_unchanged=True,
            application_read_only=True, read_past_declared_bytes=max(r['offset'] + r['size'] for r in reads) - len(text)))
    return dict(outcome='PASS', entry='0x200ae0b8', byte_decoder='0x200bcb40', cases=cases,
        qualified_domain='Only these two plain ASCII strings; no arbitrary encodings or control bytes.',
        interpretation='Length-driven conversion reads one lookahead byte, the preserved NUL, after the final ASCII character.',
        actual_renderer_executed=False, font_or_cache_modeled=False, application_modified=False)


def _investigate(image):
    target = require_target(image, 'trace')
    if target['version'] != '142':
        raise ValueError('Display-label investigation supports v1.42 only')
    main = parse(image)[0]
    payload = image[main['offset']:main['offset'] + main['size']]
    size = struct.unpack_from('<I', payload, 0x10000)[0]
    app, consumed = lzss(payload[0x10004:], size)
    if digest(app) != APP_SHA256:
        raise ValueError('Unexpected decoded application')
    site = describe_site(app)
    probe = probe_original_menu(app, through_wrapper=True)
    parser_probe = probe_original_ascii_parser(app)
    return dict(schema_version=1, outcome='PASS', meaning='Bounded investigation reproduced; not patch qualification',
        source_revision=revision(), image_sha256=digest(image), application_sha256=digest(app),
        tool_sha256=digest(Path(__file__).read_bytes()), compressed_bytes_consumed=consumed,
        site=site, probe=probe, ascii_parser_probe=parser_probe, patch_qualified=False, approved_patch_interval=None,
        known_consumers=[
            dict(address='0x2003a860', fields='record +0 callback, +4 category',
                 finding='Menu dispatch uses descriptor metadata, not label bytes, on the examined path.'),
            dict(address='0x20042c50', fields='record +5 subtype', finding='Formatting selection uses metadata.'),
            dict(address='0x2006434c', fields='record +4 category', finding='Control selection uses metadata.'),
            dict(address='0x2008605c', fields='record +12 plus language*8', finding='Label pointer returned with caller-supplied byte offset.'),
            dict(address='0x200864b4', fields='record +12 plus language*8, then first label byte',
                 finding='Icon selector exists for subtype 1; original subtype switch excludes it for modeled record 41 subtype 0.'),
            dict(address='0x2008a444', fields='record +8 plus language*8', finding='Separate title pointer, not the English label field.'),
            dict(address='0x200ab390', fields='record +4 category', finding='Layout selection uses metadata.')],
        unresolved=[
            'Full renderer 0x200ac6e0 -> 0x200aef70 remains unexecuted; glyph widths and initialized font/cache state are unresolved. Isolated ASCII parsing is covered.',
            'Normal live menu row construction and language state are not established. The ordinary wrapper forces zero text offset once reached.',
            'Pointer scans and bounded ARM paths do not enumerate all mixed-ISA, computed or aliased references.',
            'No candidate-specific loader/acceptance/write evidence exists; no image was modified or emitted.'])


TOOL_FILES = ('display_label.py', 'firmware.py', 'reporting.py')


def tool_hashes():
    paths = {name: Path(__file__).with_name(name) for name in TOOL_FILES}
    paths['research/targets.json'] = Path(__file__).resolve().parents[1] / 'research/targets.json'
    return {name: digest(path.read_bytes()) for name, path in paths.items()}


def dependency_versions():
    return {name: importlib.metadata.version(name) for name in ('capstone', 'unicorn')}


def investigate(image):
    # Keep exact checked input bytes in memory; bind reports to every local helper
    # and the target registry, as well as the emulation/disassembly runtimes.
    image = bytes(image)
    before, source, dependencies = tool_hashes(), revision(), dependency_versions()
    result = _investigate(image)
    if dependencies != dependency_versions():
        raise ValueError('Dependencies changed during display-label analysis')
    if before != tool_hashes() or source != revision():
        raise ValueError('Source changed during display-label analysis')
    return dict(result, source_revision=source, tool_sha256=before,
                dependencies=dependencies, source_unchanged=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Evidence output already exists; choose a new JSON path')
    if args.output.suffix != '.json':
        parser.error('Evidence output must be a JSON report')
    image = checked_image(args.image, 'trace')
    report = investigate(image)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(args.output, report)
    print(json.dumps(dict(outcome=report['outcome'], patch_qualified=False, report=str(args.output))))


if __name__ == '__main__':
    main()
