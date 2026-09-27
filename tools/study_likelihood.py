#!/usr/bin/env python3
"""Offline likelihood experiments; never edits the pinned library or radio state.

Generated copies of MIT-licensed ft8_lib decode.c retain its upstream notices.
Results are research evidence, not a production decoder selection.
"""
import argparse
import json
import os
from pathlib import Path
import sys

from compare_receive import sha
from development_check import ROOT, atomic_json, dependency_state, run_step, source_state
from compare_receive import parse_reference
from validate_codec import read_wav, write_wav


# Values are multipliers after upstream variance normalization and optional
# absolute likelihood caps. Each build changes only this one hypothesis.
VARIANTS = {
    'baseline': (1.0, None),
    'scale_half': (0.5, None),
    'scale_three_quarters': (0.75, None),
    'scale_one_quarter_more': (1.25, None),
    'cap2': (1.0, 2.0),
    'cap4': (1.0, 4.0),
    'cap6': (1.0, 6.0),
    'softmax1': (1.0, None),
    'softmax3': (1.0, None),
    'softmax6': (1.0, None),
}


def experiment_source(source, scale, cap, softmax=None):
    anchor = '    ftx_normalize_logl(log174);\n'
    if source.count(anchor) != 1:
        raise ValueError('Pinned likelihood insertion point changed')
    if softmax is not None:
        old = '    return max2(max2(a, b), max2(c, d));'
        if source.count(old) != 1:
            raise ValueError('Pinned symbol aggregation changed')
        # Stable smooth maximum of four dB scores, deliberately an experimental
        # score model, not a calibrated physical likelihood or power sum.
        new = ('    float m = max2(max2(a, b), max2(c, d));\n'
               f'    return m + {softmax}f * logf(expf((a-m)/{softmax}f) + '
               f'expf((b-m)/{softmax}f) + expf((c-m)/{softmax}f) + expf((d-m)/{softmax}f));')
        source = source.replace(old, new)
    if scale == 1 and cap is None:
        return source
    change = '\n    /* Local offline experiment, after upstream normalization. */\n'
    change += '    for (int i = 0; i < FTX_LDPC_N; ++i) {\n'
    change += f'        log174[i] *= {scale}f;\n'
    if cap is not None:
        change += f'        log174[i] = fmaxf(-{cap}f, fminf({cap}f, log174[i]));\n'
    change += '    }\n'
    return source.replace(anchor, anchor + change)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, action='append', required=True,
                        help='Completed compare_receive report; repeat for independent recordings')
    parser.add_argument('--output', type=Path, required=True, help='New ignored evidence directory')
    parser.add_argument('--jt9', type=Path, default=Path('/Applications/wsjtx.app/Contents/MacOS/jt9'))
    parser.add_argument('--variant', choices=VARIANTS, action='append', help='Defaults to all; baseline always included')
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = dict(outcome='RUNNING', tool_sha256=sha(Path(__file__)),
                  source_before=source_state(), commands=[], variants=[],
                  limitations=['Offline research only; default algorithm and pinned checkout unchanged.',
                               'Reference matches are not ground truth; inspect prototype-only results.',
                               'Host timing and heap are not on-radio qualification.'])

    def run(command, name, timeout=180):
        result = run_step(list(map(str, command)), output / (name + '.log'), os.environ.copy(), timeout)
        report['commands'].append(result)
        atomic_json(output / 'report.json', report)
        if result['outcome'] != 'PASS':
            raise RuntimeError(f'{name}: {result["outcome"]}')

    try:
        report['dependencies'], issues = dependency_state()
        if issues:
            raise ValueError('; '.join(issues))
        references = []
        for path in args.reference:
            path = path.resolve()
            prior = json.loads(path.read_text())
            if prior['outcome'] != 'PASS':
                raise ValueError('Incomplete reference report')
            references.append((path, prior))
        report['reference_reports'] = [{'path': str(p), 'sha256': sha(p)} for p, _ in references]
        run(['cc', '--version'], 'compiler')
        build = output / 'build'
        run(['make', '-j4', f'BUILD={build}', 'all'], 'build')
        fixtures = output / 'fixtures'
        fixtures.mkdir()
        expected = ['CQ K1ABC FN42', 'CQ W9XYZ EN50']
        first = fixtures / 'first.wav'
        run([build / 'ft8_proto', 'generate', expected[0], first, '1000'], 'generate-first')
        samples = read_wav(first)
        cases = []
        for spacing in (14, 25, 50):
            second = fixtures / f'second-{spacing}.wav'
            run([build / 'ft8_proto', 'generate', expected[1], second, str(1000 + spacing)], f'generate-{spacing}')
            other = read_wav(second)
            for ratio in (0.25, 0.5):
                name = f'overlap-{spacing}-{ratio}'
                wav = fixtures / (name + '_120000.wav')
                clipped = write_wav(wav, [0.8 * (a + ratio * b) for a, b in zip(samples, other)])
                if clipped:
                    raise ValueError('Generated overlap fixture clipped')
                residual = fixtures / (name + '-ideal-residual_120000.wav')
                # Oracle control only: exact transmitted waveform/amplitude are
                # known here. This is not a receiver cancellation algorithm.
                if write_wav(residual, [mixed - 0.8 * a for mixed, a in zip(read_wav(wav), samples)]):
                    raise ValueError('Ideal cancellation control clipped')
                sandbox = fixtures / name
                sandbox.mkdir()
                run([args.jt9.resolve(), '-8', '-p', '15', '-d', '3', '-a', sandbox, '-t', sandbox, wav], name + '-reference')
                reference = parse_reference((output / (name + '-reference.log')).read_text())
                cases.append(dict(name=name, path=str(wav), sha256=sha(wav), spacing_hz=spacing,
                                  weaker_amplitude_ratio=ratio, expected=expected, reference=reference,
                                  ideal_residual_path=str(residual), ideal_residual_sha256=sha(residual),
                                  ideal_residual_expected=[expected[1]]))
        report['synthetic_cases'] = cases
        original = ROOT / 'third_party/ft8_lib/ft8/decode.c'
        source = original.read_text()
        report['original_decode_sha256'] = sha(original)
        objects = sorted(build.rglob('*.o'))
        cflags = ['-std=c11', '-D_DEFAULT_SOURCE', '-D_DARWIN_C_SOURCE', '-O2', '-g', '-Wall', '-Wextra']
        selected = set(args.variant or VARIANTS) | {'baseline'}
        for name, (scale, cap) in VARIANTS.items():
            if name not in selected:
                continue
            folder = output / name
            folder.mkdir()
            copied = folder / 'decode.c'
            softmax = float(name.removeprefix('softmax')) if name.startswith('softmax') else None
            copied.write_text(experiment_source(source, scale, cap, softmax))
            obj, exe = folder / 'decode.o', folder / 'ft8_proto'
            run(['cc', *cflags, '-Iprototype', '-Ithird_party/ft8_lib', '-Ithird_party/ft8_lib/ft8',
                 '-c', copied, '-o', obj], name + '-compile')
            linked = [p for p in objects if p != build / 'lib/ft8/decode.o']
            run(['cc', *cflags, *linked, obj, '-lm', '-o', exe], name + '-link')
            variant = dict(name=name, scale=scale, cap=cap, softmax=softmax, source_sha256=sha(copied),
                           executable=str(exe), executable_sha256=sha(exe), comparisons=[], synthetic=[])
            report['variants'].append(variant)
            for index, (path, prior) in enumerate(references):
                comparison = folder / f'capture-{index}'
                run([sys.executable, ROOT / 'tools/compare_receive.py', '--capture', prior['capture'],
                     '--exe', exe, '--reference', path, '--jt9', args.jt9.resolve(),
                     '--output', comparison], f'{name}-capture-{index}')
                result = json.loads((comparison / 'report.json').read_text())
                summary = result['summary']
                if name == 'baseline' and (summary['new_reference_matches'] or summary['lost_reference_matches']):
                    raise ValueError('Fresh baseline does not reproduce prior matched messages')
                variant['comparisons'].append(dict(report=str(comparison / 'report.json'), **summary))
                print(name, index, json.dumps(summary), flush=True)
            for case in cases:
                label = name + '-' + case['name']
                run([exe, 'decode', case['path']], label)
                rows = [json.loads(line) for line in (output / (label + '.log')).read_text().splitlines() if line.startswith('{')]
                decoded = sorted({row['message'] for row in rows if 'message' in row})
                variant['synthetic'].append(dict(name=case['name'], decoded=decoded,
                    unexpected=sorted(set(decoded) - set(expected)),
                    metrics=[row for row in rows if 'message' not in row]))
                residual_label = label + '-ideal-residual'
                run([exe, 'decode', case['ideal_residual_path']], residual_label)
                residual_rows = [json.loads(line) for line in (output / (residual_label + '.log')).read_text().splitlines() if line.startswith('{')]
                residual_messages = sorted({row['message'] for row in residual_rows if 'message' in row})
                variant['synthetic'][-1]['ideal_residual_decoded'] = residual_messages
                variant['synthetic'][-1]['ideal_residual_pass'] = residual_messages == case['ideal_residual_expected']
                if name == 'baseline' and not variant['synthetic'][-1]['ideal_residual_pass']:
                    raise ValueError('Isolated weak-message control failed')
            variant['repeated_gain_without_loss'] = all(
                item['new_reference_matches'] > 0 and item['lost_reference_matches'] == 0
                for item in variant['comparisons'])
            atomic_json(output / 'report.json', report)
        report['source_after'] = source_state()
        report['dependencies_after'], issues = dependency_state()
        if issues or report['source_before'] != report['source_after']:
            raise ValueError('Source/dependency changed during study')
        report['outcome'] = 'PASS'
    except (Exception, KeyboardInterrupt) as exc:
        report['outcome'] = 'FAIL'
        report['error'] = f'{type(exc).__name__}: {exc}'
    finally:
        atomic_json(output / 'report.json', report)
    return 0 if report['outcome'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
