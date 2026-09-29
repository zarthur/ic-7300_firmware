#!/usr/bin/env python3
"""Read-only, exact-v1.42 stored-audio evidence; not a native capture adapter."""
import argparse
import importlib.metadata
from pathlib import Path
import struct

from control_flow import walk
from emulate_platform import APP_BASE, OUTPUT, RETURN, SOURCE, STACK, engine, inputs
from firmware import digest, revision
from reporting import atomic_json

APPLICATION_SHA256 = '4686728c9d1f7249b6278a29686a40b8fa5e527bd2428a76a33cd9395178c9a4'
FORMAT_ENTRY = 0x20068d04
FORMAT_RANGES = ((FORMAT_ENTRY, 0x20068dfc), (0x20068768, 0x20068788),
                 (0x20068cf0, FORMAT_ENTRY))
ROUTINES = {
    'metadata_parser': (0x20068788, 0x200688ac),
    'metadata_file_wrapper': (0x20068bb4, 0x20068c50),
    'format_file_wrapper': (0x20068dfc, 0x20068e90),
    'format_checker': (FORMAT_ENTRY, 0x20068dfc),
    'chunk_reader': (0x200689b0, 0x20068a94),
    'chunk_selector': (0x20068a94, 0x20068bb4),
    'file_read_wrapper': (0x20068920, 0x2006898c),
    'file_summary': (0x20068e90, 0x20068f54),
    'file_summary_caller_a': (0x20023ca4, 0x20023d08),
    'file_summary_caller_b': (0x2006bf64, 0x2006bfd4),
}
TOOL_FILES = ('recorder_interface.py', 'control_flow.py', 'emulate_platform.py',
              'firmware.py', 'reporting.py')


def format_probe(app, blob):
    """Execute original format checker/endian helpers with private RAM only.

    The 20-byte input is a size word followed by the basic WAVE fmt fields.
    Declared size need not equal supplied storage: this isolated routine reads
    only the basic fields and does not establish whole-file bounds validation.
    """
    if not isinstance(blob, bytes) or len(blob) != 20:
        raise ValueError('Require exactly 20 synthetic format bytes')
    if digest(app) != APPLICATION_SHA256:
        raise ValueError('Requires exact pinned v1.42 application')
    uc, u, a = engine()
    span = (len(app) + 4095) & ~4095
    uc.mem_map(APP_BASE, span, u.UC_PROT_READ | u.UC_PROT_EXEC)
    uc.mem_write(APP_BASE, app)
    uc.mem_map(SOURCE, 4096, u.UC_PROT_READ)
    uc.mem_write(SOURCE, blob)
    uc.mem_map(OUTPUT, 4096, u.UC_PROT_READ | u.UC_PROT_WRITE)
    uc.mem_write(OUTPUT, b'\xa5')
    uc.reg_write(a.UC_ARM_REG_R0, OUTPUT)
    uc.reg_write(a.UC_ARM_REG_R1, SOURCE)
    instructions, reads, writes = [], [], []

    def code(machine, address, size, unused):
        if not any(lo <= address and address + size <= hi for lo, hi in FORMAT_RANGES):
            raise ValueError(f'Unreviewed format execution at {address:#x}')
        instructions.append(address)

    def memory(machine, access, address, size, value, unused):
        if STACK <= address and address + size <= STACK + 0x10000:
            return
        if SOURCE <= address and address + size <= SOURCE + len(blob) and access == u.UC_MEM_READ:
            reads.append(dict(offset=address - SOURCE, size=size))
            return
        if OUTPUT <= address and address + size <= OUTPUT + 1:
            if access == u.UC_MEM_WRITE:
                writes.append(dict(offset=address - OUTPUT, size=size, value=value))
            return
        raise ValueError(f'Format data access outside exact bounds: {address:#x}+{size}')

    uc.hook_add(u.UC_HOOK_CODE, code)
    uc.hook_add(u.UC_HOOK_MEM_READ | u.UC_HOOK_MEM_WRITE, memory)
    try:
        uc.emu_start(FORMAT_ENTRY, RETURN, timeout=1000000, count=500)
    except u.UcError as exc:
        raise ValueError(f'Format emulation stopped: {exc}') from exc
    if uc.reg_read(a.UC_ARM_REG_PC) != RETURN:
        raise ValueError('Format execution did not return within limits')
    return dict(return_code=uc.reg_read(a.UC_ARM_REG_R0),
                output_byte=uc.mem_read(OUTPUT, 1)[0], initial_output_byte=0xa5,
                instruction_count=len(instructions), source_reads=reads, output_writes=writes,
                stimulus_sha256=digest(blob), original_helpers_executed=True,
                limits=dict(instructions=500, wall_seconds=1))


def format_cases():
    base = (16, 1, 1, 8000, 16000, 2, 16)
    cases = {'pcm_mono_8k16': base}
    # Independent one-field changes expose rejected values and early side effects.
    for name, index, value in (
        ('size_15', 0, 15), ('size_18', 0, 18), ('non_pcm', 1, 3),
        ('stereo', 2, 2), ('rate_12k', 3, 12000), ('byte_rate_wrong', 4, 16001),
        ('block_wrong', 5, 4), ('bits_8', 6, 8)):
        fields = list(base)
        fields[index] = value
        cases[name] = tuple(fields)
    return {name: struct.pack('<IHHIIHH', *fields) for name, fields in cases.items()}


def tool_hashes():
    hashes = {name: digest(Path(__file__).with_name(name).read_bytes()) for name in TOOL_FILES}
    hashes['research/targets.json'] = digest((Path(__file__).resolve().parents[1] / 'research/targets.json').read_bytes())
    return hashes


def identity(path):
    before = path.stat()
    value = digest(path.read_bytes())
    after = path.stat()
    def stamp(stat):
        return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns
    if stamp(before) != stamp(after):
        raise ValueError('Image changed while hashing')
    return value, stamp(after)


def _report(image):
    data, _, app, _ = inputs(image)
    if digest(app) != APPLICATION_SHA256:
        raise ValueError('Requires exact pinned v1.42 application')
    flows = {name: walk(app, APP_BASE, lo, hi) for name, (lo, hi) in ROUTINES.items()}
    return dict(schema_version=1, image_sha256=digest(data), application_sha256=digest(app),
                dependencies={name: importlib.metadata.version(name) for name in ('capstone', 'unicorn')},
                format_cases={name: format_probe(app, blob) for name, blob in format_cases().items()},
                bounded_static_flows=flows, native_capture_interface_established=False,
                limitations=[
                    'Only the format checker and its two endian helpers execute; no helper result is substituted.',
                    'Private synthetic input/output/stack RAM and a return sentinel are modeled.',
                    'Format acceptance is not whole-file validation or evidence of live receiver sample rate.',
                    'Static caller flows record calls, not their runtime effects or reachability from the active receiver.',
                    'The shared file-parser scratch address is not a demonstrated PCM/DMA buffer.',
                    'No file I/O on the radio, audio stream, device, serial or firmware-write path is opened.'])


def report(image):
    image = Path(image)
    initial = identity(image)
    hashes, source = tool_hashes(), revision()
    result = _report(image)
    if identity(image) != initial or result['image_sha256'] != initial[0]:
        raise ValueError('Image changed during recorder analysis')
    if hashes != tool_hashes() or source != revision():
        raise ValueError('Source changed during recorder analysis')
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
    print(f'Bounded stored-audio evidence: {args.output}')


if __name__ == '__main__':
    main()
