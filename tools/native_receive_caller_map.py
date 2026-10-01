#!/usr/bin/env python3
"""Verify the pinned DSP receive-caller argument and branch map statically.

This checks exact C674x instruction words; it does not execute the DSP caller.
"""
import argparse
import json
import struct
from pathlib import Path

import dsp_image
from firmware import digest, lzss, parse, read_image, require_target
from reporting import atomic_json

PROGRAM_SHA256 = '3093818ec5716abb00c16dd686a980c00812c88e73d0753b3c19e9f1d15429a1'
CONTAINER_SHA256 = '8cf5324a126f105cd2307c30b191b9dd8183f86b2c8bf229e61bf9a6a8c32f32'
DSP_BASE = 0x11800000

# Addresses, widths, encodings and decoded text were checked against the
# hash-pinned GNU C674x disassembly retained with the restored slice bundle.
CALLER_WORDS = (
    (0x118104d8, 4, 0x020068fc, 'stw a4,*+b15(416)'),
    (0x118109a0, 4, 0x1ffbef13, 'callp 0x1180e918,b3'),
    (0x118109a4, 4, 0x020068ec, 'ldw *+b15(416),a4'),
    (0x118109a8, 4, 0x05101fda, 'or 0,a4,b10'),
    (0x1180e92e, 2, 0x0246, 'mv a4,a0'),
    (0x1180e930, 4, 0xd690a121, '[!a0] bnop 0x1180f640,5'),
    (0x1180e938, 4, 0x0000be6e, 'ldw *+b14(760),b0'),
    (0x1180e940, 4, 0x3204a35b, '[!b0] mvk 1,b4'),
    (0x1180e944, 4, 0x20078120, '[b0] bnop 0x1180e95c,4'),
    (0x1180e948, 4, 0x3200be7e, '[!b0] stw b4,*+b14(760)'),
    (0x1180e94c, 4, 0x0fe35610, 'b 0x118003f0'),
    (0x1180e95c, 4, 0x0002fd2e, 'ldb *+b14(765),b0'),
    (0x1180e964, 4, 0x300fa120, '[!b0] bnop 0x1180e99c,5'),
    (0x1180e968, 4, 0x00111410, 'b 0x11817200'),
    (0x1180e99c, 4, 0x073d9028, 'mvk 31520,a14'),
    (0x1180e9a0, 4, 0x0708c0e8, 'mvkh 293666816,a14'),
    (0x1180e92c, 2, 0x5647, 'mv a4,b10'),
    (0x1180eb74, 4, 0x01b87ec0, 'addad a14,3,a3'),
    (0x1180eb78, 4, 0x018c0264, 'ldw *+a3(0),a3'),
    (0x1180eb80, 4, 0x018e1808, 'extu a3,16,24,a3'),
    (0x1180eb84, 4, 0x000dea58, 'cmpeq 15,a3,a0'),
    (0x1180eb88, 2, 0xf4ba, '[!a0] bnop 0x1180ed24,5'),
    (0x1180ed24, 4, 0x0ffb1e10, 'b 0x1180c610'),
    (0x1180ed28, 4, 0x01809028, 'mvk 288,a3'),
    (0x1180ed2c, 4, 0x01864162, 'addkpc 0x1180ed38,b3,2'),
    (0x1180ed30, 4, 0x020d507b, 'add b10,a3,b4'),
    (0x1180ed34, 4, 0x12000afc, 'addaw b15,10,a4'),
    (0x1180ed48, 4, 0x0380066f, 'ldw *+b14(24),b7'),
    (0x1180ed50, 4, 0x031c9e01, 'mpysp a4,b7,a6'),
    (0x1180ed58, 4, 0x028cfe02, 'mpysp b7,a3,b5'),
    (0x1180ed70, 4, 0x1ffbdc93, 'callp 0x1180cc44,b3'),
)


def verify_program_words(program):
    if digest(program) != PROGRAM_SHA256:
        raise ValueError('Require the exact pinned DSP program')
    layout = dsp_image.ais(program)
    section = next((row for row in layout['sections'] if row['address'] == DSP_BASE), None)
    if section is None or section['size'] != 97056:
        raise ValueError('Unexpected DSP code section')
    rows = []
    for address, width, expected, disassembly in CALLER_WORDS:
        offset = section['data_offset'] + address - DSP_BASE
        if not section['data_offset'] <= offset or offset + width > section['data_offset'] + section['size']:
            raise ValueError(f'Address outside pinned DSP section: {address:#x}')
        actual = struct.unpack_from('<H' if width == 2 else '<I', program, offset)[0]
        if actual != expected:
            raise ValueError(f'Instruction mismatch at {address:#x}: {actual:#x}')
        rows.append({'address': f'0x{address:08x}',
                     'section_offset_bytes': f'0x{address - DSP_BASE:x}',
                     'decoded_program_file_offset_bytes': f'0x{offset:x}',
                     'width_bytes': width,
                     'encoding': f'0x{actual:0{width*2}x}', 'disassembly': disassembly})
    return layout, rows


def _analyze_program(program):
    layout, words = verify_program_words(program)
    return {
        'schema_version': 1,
        'program_sha256': digest(program),
        'decoded_program_layout': {
            'code_section_address': f'0x{DSP_BASE:08x}',
            'code_section_size_bytes': next(row['size'] for row in layout['sections']
                                             if row['address'] == DSP_BASE),
            'decoded_program_section_data_offset_bytes': f'0x{next(row["data_offset"] for row in layout["sections"] if row["address"] == DSP_BASE):x}',
        },
        'verified_words': words,
        'static_dataflow': [
            'The routine entered at 0x118104c0 stores its entry A4 value at B15+416 (0x118104d8). The call packet at 0x118109a0 reloads that slot into A4 (0x118109a4) for 0x1180e918. In the callee, A4 is copied to B10 and A0 before the null branch; the argument value is established, but its pointee contents are not.',
            'At 0x1180e938..0x1180e94c, B14+760 is read. If nonzero, the branch at 0x1180e944 skips the write and helper branch. If zero, code stores 1 and branches through 0x118003f0. The live word and helper effects are not captured.',
            'After that gate, byte B14+765 is read at 0x1180e95c: zero selects the continuation at 0x1180e99c; nonzero branches to 0x11817200. Neither live value nor destination-block semantics are established.',
            'The selector base is formed in A14 as 0x11807b20. At 0x1180eb74..0x1180eb88, code loads the word at A14+12 (0x11807b2c), applies EXTU 16,24, compares the result to 15, and branches to 0x1180ed24 when unequal. The field meaning and live value are unknown.',
            'The 0x1180ed24 branch reaches 0x1180c610 with B4 formed as saved B10+288 and A4 as the current routine stack+40 address; B3 is set to return at 0x1180ed38. This proves argument-address formation, not the memory contents or returned coefficient.',
            'On the ordinary path, 0x1180ed48 loads B14+24 and 0x1180ed50/0x1180ed58 multiply local values by it; 0x1180ed70 calls 0x1180cc44. The required B14 and command state is not in the target capture.',
        ],
        'runtime_inputs_not_in_capture': [
            'Caller A4 argument nullness/address and pointee values, plus local values at stack+40 consumed by 0x1180c610.',
            'DSP B14 state used by the gates/helper paths, including live values at +24, +72, +760, +765 and +1564; the compared selector word at 0x11807b2c is also absent.',
            'Live command/control words including 0x11817b20, 0x11817b38 and 0x11817ba8, plus filter history and callback state.',
            'Frame-aligned DSP serializer-4 output words paired in time with the CPU SSIF0 A/B extraction.',
        ],
        'limits': [
            'Static instruction-word/dataflow verification only; no C674x execution or new return value is synthesized.',
            'Control and sample memory are runtime state; cinit templates do not prove current values.',
            'The v2 recording observes CPU streams after SSIF0 extraction and cannot select the physical serializer phase.',
        ],
    }


def analyze_image(container):
    target = require_target(container, 'trace')
    if digest(container) != CONTAINER_SHA256:
        raise ValueError('Require the pinned original IC-7300 v1.42 image')
    part = next(row for row in parse(container) if row['name'] == 'dsp_program')
    encoded = container[part['offset']:part['offset'] + part['size']]
    program, consumed = lzss(encoded, part['decoded_size'])
    if consumed != len(encoded):
        raise ValueError('DSP program did not decode completely')
    result = _analyze_program(program)
    result.update({
        'container_sha256': digest(container),
        'target': {'model': target['model'], 'version': target['version']},
    })
    return result


def analyze_restored_program(program, manifest):
    """Analyze a restored decoded program after checking its manifest identity."""
    image = manifest.get('independent_clean_image_report', {})
    if (image.get('dirty') is not False or
            image.get('container_sha256') != CONTAINER_SHA256 or
            image.get('decoded_program_sha256') != PROGRAM_SHA256):
        raise ValueError('Restoration manifest does not identify the pinned clean image/program')
    restored = [item for item in manifest.get('restored_files', [])
                if Path(item.get('restored_as', '')).name == 'dsp_program.decoded.bin']
    if len(restored) != 1:
        raise ValueError('Restoration manifest must identify one decoded DSP program')
    item = restored[0]
    if (item.get('verified') is not True or item.get('bytes') != len(program) or
            item.get('sha256') != digest(program)):
        raise ValueError('Decoded program does not match its restored-file manifest entry')
    input_item = manifest.get('input_file_hashes', {}).get('dsp_program.decoded.bin', {})
    if (input_item.get('sha256') != digest(program) or
            input_item.get('bytes') != len(program)):
        raise ValueError('Decoded program does not match the manifest input hash')
    result = _analyze_program(program)
    result.update({
        'container_sha256': CONTAINER_SHA256,
        'source_evidence': {
            'kind': 'restored decoded program verified against restoration manifest',
            'restored_program_sha256': digest(program),
            'image_report_source_revision': image.get('source_revision'),
            'disassembly_provenance': manifest.get('disassembly_provenance'),
        },
    })
    return result


def report(image):
    container = read_image(image)
    return analyze_image(container)


def report_restored_program(program_path, manifest_path):
    program_path, manifest_path = Path(program_path), Path(manifest_path)
    program = program_path.read_bytes()
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    if not isinstance(manifest, dict):
        raise ValueError('Restoration manifest must be a JSON object')
    result = analyze_restored_program(program, manifest)
    result['source_evidence']['restoration_manifest_file_sha256'] = digest(manifest_bytes)
    result['source_evidence']['restoration_manifest_path'] = str(manifest_path)
    result['source_evidence']['restored_program_path'] = str(program_path)
    if program_path.read_bytes() != program or manifest_path.read_bytes() != manifest_bytes:
        raise ValueError('Evidence input changed during caller-map analysis')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path, nargs='?', help='pinned original image container')
    parser.add_argument('--restored-program', type=Path,
                        help='hash-verified decoded DSP program from a restoration bundle')
    parser.add_argument('--restoration-manifest', type=Path,
                        help='manifest accompanying --restored-program')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output already exists')
    if args.restored_program:
        if args.image or not args.restoration_manifest:
            parser.error('--restored-program requires --restoration-manifest and no image argument')
        result = report_restored_program(args.restored_program, args.restoration_manifest)
    else:
        if not args.image or args.restoration_manifest:
            parser.error('Supply an image, or both --restored-program and --restoration-manifest')
        result = report(args.image)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(args.output, result)
    print(args.output)


if __name__ == '__main__':
    main()
