#!/usr/bin/env python3
"""Cross-check pinned DSP, CPU-control, and native-receive capture evidence.

This creates a provenance-bound source crosswalk. It does not execute DSP code,
interpret SSI status bits, or identify physical serializer slots as CPU A/B.
"""
import argparse
import hashlib
import json
from pathlib import Path

from reporting import atomic_json

PINNED_CONTAINER = '8cf5324a126f105cd2307c30b191b9dd8183f86b2c8bf229e61bf9a6a8c32f32'
PINNED_DSP_PROGRAM = '3093818ec5716abb00c16dd686a980c00812c88e73d0753b3c19e9f1d15429a1'
PINNED_APPLICATION = '4686728c9d1f7249b6278a29686a40b8fa5e527bd2428a76a33cd9395178c9a4'
PINNED_COMMIT = '119617ddb60bea1ce0f642ef111a68302b6228c6'
PINNED_RECORDING = 'a3f071d17b67d3ee0bd2063f75a109e0c875c7222dd86f029789cfc2ce4c5783'
PINNED_CAPTURE = '41564ca5b439e37045a3f370bc2e4fcd87124a7ee6bef81fc22a1bd273c3e37f'


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def crosscheck(dsp, controls, capture, input_hashes):
    """Verify the exact reviewed reports and summarize their cross-boundary facts."""
    _require(dsp.get('source_unchanged') is True and
             dsp.get('source_revision') == {'commit': PINNED_COMMIT, 'dirty': False},
             'DSP report must be from the clean pinned source revision')
    _require(dsp.get('image_sha256') == PINNED_CONTAINER and
             dsp.get('program_sha256') == PINNED_DSP_PROGRAM,
             'DSP report does not identify the pinned original image/program')
    _require(controls.get('source_unchanged') is True and
             controls.get('source_revision') == {'commit': PINNED_COMMIT, 'dirty': False},
             'CPU-control report must be from the clean pinned source revision')
    _require(controls.get('image_sha256') == PINNED_CONTAINER and
             controls.get('application_sha256') == PINNED_APPLICATION,
             'CPU-control report does not identify the pinned original image/application')
    _require(capture.get('schema_version') == 3 and
             capture.get('recording_sha256') == PINNED_RECORDING and
             capture.get('capture_sha256') == PINNED_CAPTURE and
             capture.get('input_unchanged') is True,
             'Capture report does not identify the preserved schema-3 v2 capture')

    observations = capture.get('raw_observation_summary', {})
    streams = capture.get('raw_streams', {})
    a, b = streams.get('stream_a', {}), streams.get('stream_b', {})
    matches = capture.get('recorder_matches', [])
    _require(capture.get('capture_full') is True and
             observations.get('records') == 512 and capture.get('capture_status') == 2,
             'Expected one complete 512-record v2 capture')
    _require(a.get('samples') == 18432 and b.get('samples') == 18432 and
             b.get('zero_samples') == 18432 and b.get('min') == 0 and b.get('max') == 0,
             'Capture stream summaries differ from the preserved observation')
    _require(len(matches) == 1 and matches[0].get('stream') == 'stream_a' and
             matches[0].get('stride') == 6 and matches[0].get('phase') == 0 and
             matches[0].get('gain') == 'unity' and matches[0].get('matching_samples') == 3024 and
             matches[0].get('matching_records') == 504 and
             (matches[0].get('first_capture_sequence'), matches[0].get('last_capture_sequence')) == (0, 503) and
             matches[0].get('segment_last_capture_sequence') == 511,
             'Recorder match does not match the validated stream-A prefix')

    return {
        'schema_version': 1,
        'evidence_inputs': input_hashes,
        'firmware_identity': {
            'container_sha256': PINNED_CONTAINER,
            'dsp_program_sha256': PINNED_DSP_PROGRAM,
            'application_sha256': PINNED_APPLICATION,
            'source_commit': PINNED_COMMIT,
        },
        'crosswalk': [
            {
                'stage': 'FPGA to DSP receive input',
                'board_net': 'DFR_MOD',
                'dsp_pin': '115 / AXR0[3] / serializer 3 RX',
                'original_image_addresses': ['0x11814954', '0x11814c44', '0x11818bd0', '0x11819de0'],
                'finding': 'Original setup and bounded routing/conversion slices place the input in DSP context; initial FIFO phase and physical frame alignment remain unknown.',
            },
            {
                'stage': 'DSP processing and output contexts',
                'original_image_addresses': ['0x1180e918', '0x1180ed24', '0x1180c610', '0x1180cc44', '0x11810a00', '0x11811250'],
                'finding': 'Qualified slices cover selected ordinary processing and serializer-4 context publication, but do not execute the whole caller or connect every source scalar to every output.',
                'context_384_415': 'main/aux/mix publication, repeated adjacent words; serializer-4 route is documented, FIFO phase is not.',
                'context_416_447': 'separate auxiliary publication, repeated adjacent words; not identified as CPU stream A or B.',
            },
            {
                'stage': 'DSP receive ramp and ordinary gain/bypass controls',
                'original_image_addresses': ['0x200b2f60', '0x1180a00c', '0x11817b24', '0x1180ed24', '0x1180c610', '0x1180cc44', '0x11810a00'],
                'finding': 'The receive ramp/mute command and selected processing/bypass slices are mapped, but the complete coefficient calculation and physical UI/control association are not.',
                'details': 'Command 0x11817b24 bit 0 selects bounded ramp/zero branches; 0x1180c610 writes the ordinary-processing coefficient at B14+24; command 0x11817b20 bit 14 selects replacement output in 0x1180cc44; bit 10 controls the separate output ramp at B14+400.',
            },
            {
                'stage': 'AF-controlled DSP path',
                'original_image_addresses': ['0x11811520', '0x11811708', '0x118117b4', '0x118117e4', '0x1180a2e4'],
                'finding': 'The direct AF-controlled store targets context 352-383, mapped to serializer 2; a subsequent shared-status helper remains unqualified, so global AF independence is not established.',
                'control_state': 'command 0x11817b54; target/smoothed values at B14+464/+460',
            },
            {
                'stage': 'DSP board output to CPU SSIF0',
                'board_net': 'DX_REC',
                'dsp_pin': '116; private configuration map associates this with serializer 4',
                'cpu_pin': '190 / P2_10 / SSIRxD0',
                'cpu_registers_and_addresses': ['SSIF0 FIFO 0xe820b01c', '0x2005ff1c', '0x20060614', '0x20060690..0x200606d4'],
                'finding': 'The board/DSP/CPU source map reaches SSIF0 DMA and two extracted software streams; DSP frame phase is not mapped to those streams.',
            },
            {
                'stage': 'CPU queues to recorder',
                'addresses': ['A array 0x203fc48a', 'B array 0x203fc4d2', 'A queue 0x203fbdc0', 'B queue 0x203fc002', 'recorder stage 0x20067254'],
                'finding': 'CPU extraction retains upper 16 bits at bank offsets 16*i and 16*i+4, then the recorder selects every sixth A sample in the observed path.',
            },
        ],
        'capture_observation': {
            'recording_sha256': PINNED_RECORDING,
            'capture_sha256': PINNED_CAPTURE,
            'records': observations['records'],
            'stream_a_samples': a['samples'],
            'stream_a_rms': a['rms'],
            'stream_b_samples': b['samples'],
            'stream_b_zero_samples': b['zero_samples'],
            'recorder_match': matches[0],
            'raw_ssi_register_counts': observations['ssi_raw_register_counts'],
            'nominal_extracted_rate_hz': capture.get('timing', {}).get('sample_rate_hz'),
            'rate_basis': 'Timer projection assumes 32 MHz and 32,001 cycles; it is not calibrated.',
            'ssi_interpretation': 'Raw non-atomic snapshots only; no SSI status bit or DMA phase is assigned meaning.',
        },
        'unknowns': [
            'No verified DSP serializer-4 FIFO phase or frame alignment to CPU extraction positions A/B.',
            'The observed all-zero stream B has no established purpose or direction.',
            'No end-to-end DSP execution ties a known receive input sample and gain state to the captured CPU queue values.',
            'The minimum-AF, 7.074 MHz USB-D setting is owner-reported; one capture does not establish a gain curve or global AF independence.',
            'The capture and nominal timer projection do not prove live DMA ownership, missed-bank absence, or calibrated timing.',
        ],
        'scope': 'Provenance and crosswalk consistency only; no firmware execution, radio access, SSI bit interpretation, or hardware acceptance is performed.',
    }


def read_json(path):
    raw = Path(path).read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f'Expected JSON object: {path}')
    return value, sha256(raw), raw


def report(dsp_path, controls_path, capture_path):
    paths = [Path(dsp_path), Path(controls_path), Path(capture_path)]
    values = [read_json(path) for path in paths]
    labels = ['dsp_image_report', 'cpu_controls_report', 'capture_report']
    hashes = {label: {'path': str(path), 'sha256': item[1]}
              for label, path, item in zip(labels, paths, values)}
    result = crosscheck(*(item[0] for item in values), hashes)
    result['generator'] = {'path': str(Path(__file__)), 'sha256': sha256(Path(__file__).read_bytes())}
    for path, (_, _, before) in zip(paths, values):
        if path.read_bytes() != before:
            raise ValueError(f'Evidence report changed during cross-check: {path}')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dsp-report', type=Path, required=True)
    parser.add_argument('--controls-report', type=Path, required=True)
    parser.add_argument('--capture-report', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output already exists')
    result = report(args.dsp_report, args.controls_report, args.capture_report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(args.output, result)
    print(args.output)


if __name__ == '__main__':
    main()
