#!/usr/bin/env python3
"""Frozen, bounded offline cancellation studies and independent synthetic inputs."""
import argparse
from datetime import datetime, timezone
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import sys

import numpy as np
from scipy.signal import hilbert

from compare_receive import capture_slots, sha
from development_check import ROOT, atomic_json, dependency_state, run_step
from validate_codec import read_wav, write_wav


def sources():
    paths = sorted((ROOT / 'prototype').glob('*.[ch]')) + [ROOT / name for name in
        ('tools/cancellation.py', 'tools/study_cancellation.py', 'tools/compare_receive.py',
         'tools/validate_codec.py', 'tools/development_check.py', 'Makefile')]
    return {str(p.relative_to(ROOT)): sha(p) for p in paths}


def execute(command, log, timeout=150):
    result = run_step(list(map(str, command)), log, os.environ.copy(), timeout)
    if result['outcome'] != 'PASS':
        raise RuntimeError(f'{log.name}: {result["outcome"]}; inspect log')
    return result


def freeze(output):
    state, issues = dependency_state()
    if issues:
        raise ValueError('; '.join(issues))
    before = sources()
    build = output / 'build'
    result = execute(['make', '-j4', f'BUILD={build}', 'all'], output / 'build.log')
    if sources() != before:
        raise ValueError('Source changed during candidate build')
    for name in before:
        target = output / 'source' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    candidate = dict(schema_version=1, frozen_utc=datetime.now(timezone.utc).isoformat(),
                     source_sha256=before, dependencies=state, executable=str(build / 'ft8_proto'),
                     executable_sha256=sha(build / 'ft8_proto'), command=result,
                     versions={p: importlib.metadata.version(p) for p in ('numpy', 'scipy')})
    atomic_json(output / 'candidate.json', candidate)
    return candidate


def make_fixtures(output, exe):
    """Ground truth supplied to evaluation only; never to the cancellation fitter."""
    n = 180000
    messages = ['CQ K1ABC FN42', 'CQ W9XYZ EN50']
    generated = {}
    def signal(message, hz, phase=0, shift=0):
        key = (message, hz)
        if key not in generated:
            path = output / f'generator-{len(generated)}.wav'
            execute([exe, 'generate', message, path, hz], output / f'generator-{len(generated)}.log')
            generated[key] = np.array(read_wav(path))
        x = generated[key]
        if phase:
            x = np.real(hilbert(x) * np.exp(1j * phase))
        if shift:
            x = np.interp(np.arange(n) - shift * 12000, np.arange(n), x, left=0, right=0)
        return x
    cases = []
    def add(name, data, expected, required_gain=False):
        path = output / (name + '_120000.wav')
        if write_wav(path, data):
            raise ValueError('Fixture clipped')
        cases.append(dict(name=name, path=str(path), sha256=sha(path), expected=expected,
                          designated_overlap=required_gain))
    first = signal(messages[0], 1000)
    add('single', 0.8 * first, messages[:1])
    add('silence', np.zeros(n), [])
    for seed in (11, 22, 33):
        add(f'noise-{seed}', np.random.default_rng(seed).normal(0, 0.07, n), [])
    for spacing in (14, 25, 50):
        for ratio in (0.25, 0.5):
            add(f'overlap-{spacing}-{ratio}', 0.8 * (first + ratio * signal(messages[1], 1000 + spacing)),
                messages, spacing in (14, 25))
    add('phase-time', 0.8 * signal(messages[0], 1000, 0.7, -0.03525)
        + 0.4 * signal(messages[1], 1014, -1.2, 0.027125), messages, True)
    add('fractional-frequency', 0.8 * signal(messages[0], 1001.3, 1.1, 0.015125)
        + 0.4 * signal(messages[1], 1026.8, -0.4, -0.01275), messages, True)
    add('seeded-overlap', 0.8 * first + 0.4 * signal(messages[1], 1014)
        + np.random.default_rng(7300).normal(0, 0.005, n), messages, True)
    manifest = dict(generator_sha256=sha(exe), tool_sha256=sha(Path(__file__)), cases=cases,
                    note='Known messages/parameters are evaluation truth, not fitter input. No RF transmission.')
    atomic_json(output / 'fixtures.json', manifest)
    return manifest


def behavioral(value):
    """Select behavior only; omit machine timing, memory measurements and paths."""
    ignored = {'elapsed_seconds', 'resources'}
    if isinstance(value, dict):
        return {k: behavioral(v) for k, v in value.items() if k not in ignored}
    if isinstance(value, list):
        return [behavioral(v) for v in value]
    return value


def evaluate_result(result, item):
    baseline = {r['message'] for r in result['baseline']}
    observed = {r['message'] for r in result['messages']}
    expected = set(item['expected'])
    previous = set(item.get('prior_matched', baseline & expected))
    return dict(completed=result['termination'] == 'completed',
                baseline_matches=sorted(baseline & expected), matched=sorted(observed & expected),
                baseline_reference_changed=bool('prior_matched' in item and baseline & expected != previous),
                gained=sorted((observed & expected) - previous), lost=sorted(previous - observed),
                baseline_messages_lost=sorted(baseline - observed),
                prototype_only=sorted(observed - expected),
                new_unconfirmed=sorted((observed - baseline) - expected),
                expected_missing=sorted(expected - observed))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--freeze', action='store_true')
    parser.add_argument('--make-fixtures', action='store_true')
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--candidate', type=Path)
    parser.add_argument('--fixtures', type=Path)
    parser.add_argument('--reference', type=Path)
    parser.add_argument('--role', choices=('synthetic', 'development', 'holdout'), default='development')
    parser.add_argument('--repeat', type=Path, help='Prior study report for identical-behavior verification')
    parser.add_argument('--worker', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    if args.worker:
        from cancellation import cancel_slot
        samples = np.array(read_wav(args.worker))
        result = cancel_slot(samples, args.exe.resolve(), output, max_passes=2, max_signals=8, deadline_seconds=120)
        atomic_json(output / 'result.json', result)
        return 0
    report = dict(outcome='RUNNING', role=args.role, tool_sha256=sha(Path(__file__)), slots=[], errors=[])
    atomic_json(output / 'report.json', report)
    try:
        if args.freeze:
            report['candidate'] = freeze(output)
        elif args.make_fixtures:
            if not args.exe:
                raise ValueError('--make-fixtures requires --exe')
            report['fixtures'] = make_fixtures(output, args.exe.resolve())
        else:
            if not args.candidate or bool(args.fixtures) == bool(args.reference):
                raise ValueError('Require --candidate and exactly one of --fixtures or --reference')
            candidate = json.loads(args.candidate.read_text())
            exe = Path(candidate['executable'])
            if sources() != candidate['source_sha256'] or sha(exe) != candidate['executable_sha256']:
                raise ValueError('Frozen candidate differs from current source or executable')
            report['candidate_sha256'] = sha(args.candidate)
            report['candidate'] = candidate
            state, issues = dependency_state()
            versions = {p: importlib.metadata.version(p) for p in ('numpy', 'scipy')}
            if issues or state != candidate['dependencies'] or versions != candidate['versions']:
                raise ValueError('Frozen dependency state differs')
            items = []
            if args.fixtures:
                report['fixtures_sha256'] = sha(args.fixtures)
                items = json.loads(args.fixtures.read_text())['cases']
            else:
                prior = json.loads(args.reference.read_text())
                if prior['outcome'] != 'PASS':
                    raise ValueError('Reference report incomplete')
                capture = Path(prior['capture'])
                manifest, slots = capture_slots(capture)
                if sha(capture / 'capture.json') != prior['capture_manifest_sha256']:
                    raise ValueError('Capture manifest changed')
                cached = {row['file']: row for row in prior['slots']}
                if set(cached) != {p.name for p in slots}:
                    raise ValueError('Reference slot inventory differs')
                for path in slots:
                    row = cached[path.name]
                    if sha(path) != row['sha256']:
                        raise ValueError('Reference slot hash differs')
                    items.append(dict(name=path.stem, path=str(path), sha256=sha(path),
                                      expected=sorted({r['message'] for r in row['reference']}),
                                      prior_matched=row['matched']))
                report['reference_sha256'] = sha(args.reference)
                report['capture'] = str(capture)
            if not items:
                raise ValueError('No input slots or fixtures; empty studies cannot pass')
            for item in items:
                path = Path(item['path'])
                if sha(path) != item['sha256']:
                    raise ValueError('Input changed')
                folder = output / item['name']
                command = execute([sys.executable, Path(__file__).resolve(), '--worker', path, '--exe', exe,
                                   '--output', folder], output / (item['name'] + '.log'))
                result = json.loads((folder / 'result.json').read_text())
                row = dict(input=item, result=result, evaluation=evaluate_result(result, item), command=command)
                report['slots'].append(row)
                if not row['evaluation']['completed']:
                    report['errors'].append(dict(slot=item['name'], termination=result['termination']))
                if row['evaluation']['baseline_reference_changed']:
                    report['errors'].append(dict(slot=item['name'], error='Unchanged-decoder baseline differs from reference report'))
                atomic_json(output / 'report.json', report)
                print(item['name'], result.get('termination'), flush=True)
            if sources() != candidate['source_sha256'] or sha(exe) != candidate['executable_sha256']:
                raise ValueError('Candidate source changed during evaluation')
            state, issues = dependency_state()
            if issues or state != candidate['dependencies']:
                raise ValueError('Dependency changed during evaluation')
            report['summary'] = {key: sum(len(row['evaluation'][key]) for row in report['slots']) for key in
                ('baseline_matches', 'matched', 'gained', 'lost', 'baseline_messages_lost',
                 'prototype_only', 'new_unconfirmed', 'expected_missing')}
            report['summary']['slots'] = len(report['slots'])
            report['synthetic_acceptance'] = (not report['errors'] and all(not row['evaluation'][key]
                for row in report['slots'] for key in ('baseline_messages_lost', 'prototype_only', 'expected_missing'))) if args.fixtures else None
            if args.repeat:
                previous = json.loads(args.repeat.read_text())
                if previous.get('outcome') != 'PASS' or previous.get('candidate_sha256') != report['candidate_sha256']:
                    raise ValueError('Repeat requires a completed report on the same candidate')
                def signature(data):
                    return [(row['input']['sha256'], behavioral(row['result']), row['evaluation']) for row in data['slots']]
                report['repeat_identical'] = signature(previous) == signature(report)
                if not report['repeat_identical']:
                    raise ValueError('Repeated behavior differs')
            if report['errors']:
                raise ValueError('One or more slots did not complete')
        report['outcome'] = 'PASS'
    except (Exception, KeyboardInterrupt) as exc:
        report.update(outcome='FAIL', error=f'{type(exc).__name__}: {exc}')
    finally:
        atomic_json(output / 'report.json', report)
    return 0 if report['outcome'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
