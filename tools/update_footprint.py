#!/usr/bin/env python3
"""Bounded official-v1.42 updater footprint evidence; never creates an image."""
import argparse
from pathlib import Path

from reporting import atomic_json
from emulate_platform import inputs, transfer
from firmware import digest, revision
from updater_stages import activation_record, main_update

ERASE_UNIT = 0x10000


def summarize_transfer(result):
    """Preserve erase exposure separately from input bytes and changed flags."""
    comparisons = [event for event in result['events'] if event['operation'] == 'compare']
    erases = [event for event in result['events'] if event['operation'] == 'erase']
    programs = [event for event in result['events'] if event['operation'] == 'program']
    return dict(input_bytes=result['file_bytes_read'], changed_flag=result['changed_flag'],
                return_code=result['return_code'], interrupted=result['interrupted'],
                compared_units=[dict(offset=e['offset'], length=e['length'], different=e['different'])
                                for e in comparisons],
                erase_ranges=[dict(offset=e['offset'], length=e['length']) for e in erases],
                program_ranges=[dict(offset=e['offset'], length=e['length']) for e in programs],
                erase_bytes=sum(e['length'] for e in erases),
                program_bytes=sum(e['length'] for e in programs),
                modeled_payload_equal=result['flash_payload_equal'])


def _report(image):
    # inputs uses the exact version/hash trace registry before any execution.
    data, main, app, _ = inputs(image)
    import capstone
    import unicorn
    scenarios = {}
    for label, payload, destination in (
            ('official_boot', main[:ERASE_UNIT], 0),
            ('stored_application_first_unit', main[ERASE_UNIT:2 * ERASE_UNIT], 0x400000)):
        for equal in (False, True):
            result = transfer(app, payload, destination=destination, initial_equal=equal)
            scenarios[f'{label}:equal={equal}'] = dict(
                initial_flash='payload plus erased padding' if equal else 'erased FF',
                footprint=summarize_transfer(result), evidence=result)
    for label, payload in (('one_byte_change_two_units', b'A' + b'\xff' * (2 * ERASE_UNIT - 1)),
                           ('one_byte_partial_unit', b'A')):
        result = transfer(app, payload, destination=ERASE_UNIT)
        scenarios[label] = dict(initial_flash='erased FF', synthetic=True,
                                footprint=summarize_transfer(result), evidence=result)
    callers, activation = {}, {}
    for selector in (0, 1):
        for boot_changed in (False, True):
            callers[f'selector={selector}:boot_changed={boot_changed}'] = main_update(
                app, data, selector=selector, boot_changed=boot_changed)
        activation[str(selector)] = activation_record(app, main, current_selector=selector)
    return dict(schema_version=1, image_sha256=digest(data), candidate_exists=False,
                dependencies=dict(capstone=capstone.__version__, unicorn=unicorn.__version__),
                stored_application_bytes=len(main) - ERASE_UNIT,
                official_application_units_if_all_differ=(len(main) - 1) // ERASE_UNIT,
                transfer_scenarios=scenarios, main_caller_scenarios=callers,
                selector_scenarios=activation,
                limitations=[
                    'No modified candidate exists; no actual candidate byte diff or write footprint is established.',
                    'A one-byte decoded edit can change many compressed bytes; unknown destination contents require treating every transfer unit as possibly written.',
                    'Transfer equality compares destination contents, not merely unchanged bytes in a source image.',
                    'Initial flash is synthetic: erased FF or exact payload plus erased padding; no bank readback exists.',
                    'Erase/program and file services are models; physical completion and cache effects are unproven.',
                    'Caller transfer flags are substitutions; these scenarios are not a coherent whole-machine update.',
                    'Other-component handler is disabled in the caller model; DSP/FPGA inactivity is unproven.',
                    'Selector erases 64 KiB and programs 16 bytes; remaining block ownership is unresolved.',
                    'No recovery, packing, modified boot, or TX authorization follows.'])


TOOL_FILES = ('update_footprint.py', 'emulate_platform.py', 'updater_stages.py',
              'firmware.py', 'reporting.py')


def tool_hashes():
    hashes = {name: digest(Path(__file__).with_name(name).read_bytes()) for name in TOOL_FILES}
    hashes['research/targets.json'] = digest((Path(__file__).resolve().parents[1] / 'research/targets.json').read_bytes())
    return hashes


def report(image):
    before = tool_hashes()
    source = revision()
    result = _report(image)
    if before != tool_hashes() or source != revision():
        raise ValueError('Source changed during footprint analysis')
    return dict(result, source_revision=source, tool_sha256=before, source_unchanged=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path)
    parser.add_argument('--output', type=Path, required=True, help='New local JSON evidence file')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output exists; choose a new evidence file')
    result = report(args.image)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(args.output, result)
    print(f'Offline footprint evidence: {args.output}')


if __name__ == '__main__':
    main()
