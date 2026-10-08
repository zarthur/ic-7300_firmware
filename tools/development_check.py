#!/usr/bin/env python3
"""Unattended desktop validation of the current worktree; never opens radio I/O."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC_TESTS = (
    'test_cli', 'test_civ_clock_measurement', 'test_clock_reference',
    'test_compare_receive', 'test_capture_batch', 'test_cancellation_core',
    'test_study_cancellation', 'test_study_likelihood', 'test_control_flow', 'test_development_check',
    'test_emulation.EngineTests', 'test_firmware',
    'test_platform_evidence', 'test_receive_capture', 'test_targets',
    'test_recorder_interface.SyntheticRecorderTests', 'test_native_receive.SyntheticReceiveTests',
    'test_native_timing.SyntheticTimingTests', 'test_native_memory.SyntheticMemoryTests',
    'test_native_placement.SyntheticPlacementTests', 'test_native_capture', 'test_native_epoch',
    'test_native_epoch_wrappers.SyntheticEpochWrapperTests',
    'test_native_capture_v2',
    'test_native_v2_hooks.SyntheticV2HookTests',
    'test_native_v2_recorder.SyntheticV2RecorderTests',
    'test_native_export.SyntheticExportTests', 'test_native_transport', 'test_native_transport_v2', 'test_native_capture_report', 'test_native_capture_decode', 'test_native_capture_v2_report',
    'test_native_wrappers.SyntheticWrapperTests', 'test_native_lifecycle.SyntheticLifecycleTests',
    'test_native_recorder_controls.SyntheticRecorderControlTests',
    'test_native_dsp_controls.SyntheticDspControlTests',
    'test_controller.ControllerModelTests', 'test_update_footprint.SyntheticFootprintTests',
    'test_updater_stages.ComponentDispatchModelTests',
    'test_label_metrics.LabelMetricsModelTests',
    'test_display_label.DisplayLabelModelTests', 'test_update_dispatch.SyntheticDispatchTests',
)
STRICT_TESTS = '''import unittest
suite = unittest.defaultTestLoader.discover('tests')
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(0 if result.wasSuccessful() and result.testsRun and not result.skipped else 1)
'''


from reporting import atomic_json


def run_step(command, log, env, timeout):
    """Bound the whole process group, including compiler/decoder children."""
    start = time.monotonic()
    with log.open('w') as stream:
        process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=stream,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        try:
            code = process.wait(timeout=timeout)
            outcome = 'PASS' if code == 0 else 'FAIL'
        except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            code = process.returncode
            outcome = 'TIMEOUT' if isinstance(exc, subprocess.TimeoutExpired) else 'INTERRUPTED'
    return dict(command=command, outcome=outcome, returncode=code,
                seconds=round(time.monotonic() - start, 3), log=str(log))


def capture(command, cwd=ROOT):
    return subprocess.check_output(command, cwd=cwd, stderr=subprocess.STDOUT,
                                   timeout=30).decode().strip()


def source_state(root=ROOT):
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=root, timeout=30)
    paths = git('ls-files', '--cached', '--others', '--exclude-standard', '-z')
    hashes = {}
    for raw in paths.split(b'\0'):
        if raw:
            name = os.fsdecode(raw)
            path = root / name
            hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    return dict(commit=git('rev-parse', 'HEAD').decode().strip(),
                status=git('status', '--porcelain').decode(), sha256=hashes)


def dependency_state(root=ROOT):
    states = {}
    issues = []
    for name, spec in json.loads((root / 'research/dependencies.json').read_text()).items():
        target = root / spec['location']
        try:
            head = capture(['git', 'rev-parse', 'HEAD'], target)
            status = capture(['git', 'status', '--porcelain', '--untracked-files=all'], target)
            # Include ignored source modifications too; a clean Git status alone is insufficient.
            ignored = capture(['git', 'ls-files', '--others', '--ignored', '--exclude-standard'], target)
            # Check actual blobs, including files hidden by assume-unchanged/skip-worktree.
            tree = subprocess.check_output(['git', 'ls-tree', '-rz', 'HEAD'], cwd=target, timeout=30)
            mismatches = []
            content_hash = hashlib.sha256()
            for entry in tree.split(b'\0'):
                if not entry:
                    continue
                header, raw_name = entry.split(b'\t', 1)
                mode, kind, expected = header.split()
                path = target / os.fsdecode(raw_name)
                if kind != b'blob':
                    mismatches.append(os.fsdecode(raw_name) + ': unsupported nested Git entry')
                    continue
                try:
                    data = os.fsencode(os.readlink(path)) if mode == b'120000' else path.read_bytes()
                    actual = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest().encode()
                    if actual != expected:
                        mismatches.append(os.fsdecode(raw_name))
                    content_hash.update(raw_name + b'\0' + hashlib.sha256(data).digest())
                except OSError:
                    mismatches.append(os.fsdecode(raw_name))
            states[name] = dict(revision=head, expected_revision=spec['revision'],
                                status=status, ignored_files=ignored, content_mismatches=mismatches,
                                contents_sha256=content_hash.hexdigest())
            if head != spec['revision']:
                issues.append(f'{name}: revision differs from pinned {spec["revision"]}')
            if status or ignored or mismatches:
                issues.append(f'{name}: dependency checkout is not clean')
        except (OSError, subprocess.SubprocessError) as exc:
            issues.append(f'{name}: unavailable dependency checkout: {exc}')
    return states, issues


def preflight(profile, jt9, root=ROOT):
    details = {'packages': {}, 'images': {}}
    issues = []
    for filename in ('requirements-research.txt', 'requirements-audio.txt'):
        for line in (root / filename).read_text().splitlines():
            line = line.split('#', 1)[0].strip()
            if not line:
                continue
            package, expected = line.split('==')
            try:
                actual = importlib.metadata.version(package)
                details['packages'][package] = actual
                if actual != expected:
                    issues.append(f'{package}: expected {expected}, found {actual}')
            except importlib.metadata.PackageNotFoundError:
                issues.append(f'Missing dependency: {package}=={expected}')
    details['source_dependencies'], dependency_issues = dependency_state(root)
    issues.extend(dependency_issues)
    if profile == 'full':
        # Reuse the exact-image registry gate, not the editable acquisition manifest.
        from firmware import checked_image, digest, require_target
        for version in ('140', '141', '142'):
            path = root / f'artifacts/original/7300_{version}.dat'
            try:
                data = checked_image(path, 'analyze')
                if require_target(data, 'analyze')['version'] != version:
                    raise ValueError('Pinned image does not match the expected corpus version')
                details['images'][version] = digest(data)
            except (OSError, ValueError) as exc:
                issues.append(f'Official {version}: {exc}')
        if not jt9.is_file() or not os.access(jt9, os.X_OK):
            issues.append(f'Missing executable reference decoder: {jt9}')
        else:
            details['reference_decoder_sha256'] = hashlib.sha256(jt9.read_bytes()).hexdigest()
    for name in ('cc', 'make'):
        try:
            details[name] = capture([name, '--version']).splitlines()[0]
        except (OSError, subprocess.SubprocessError) as exc:
            issues.append(f'Missing or unusable {name}: {exc}')
    return details, issues


def run_python_tests(profile, output):
    sys.path.insert(0, str(ROOT / 'tests'))
    loader = unittest.TestLoader()
    if profile == 'full':
        suite = loader.discover(str(ROOT / 'tests'))
    else:
        names = ('test_cli',) if profile == 'wav' else SYNTHETIC_TESTS
        suite = loader.loadTestsFromNames(names)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    metrics = dict(tests_run=result.testsRun, failures=len(result.failures),
                   errors=len(result.errors), skipped=[{'test': str(t), 'reason': why} for t, why in result.skipped],
                   expected_failures=len(result.expectedFailures), unexpected_successes=len(result.unexpectedSuccesses))
    atomic_json(output, metrics)
    return 0 if result.wasSuccessful() and result.testsRun and not result.skipped else 1


def planned_steps(profile, output, jt9):
    python = sys.executable
    build = output / 'build'
    sanitize = output / 'sanitize'
    flags = '-std=c11 -D_DEFAULT_SOURCE -D_DARWIN_C_SOURCE -O1 -g -Wall -Wextra -fsanitize=address,undefined -fno-omit-frame-pointer'
    steps = [
        ('build', ['make', '-j4', f'BUILD={build}', 'all']),
        ('python-tests-no-skips', [python, 'tools/development_check.py', '--test-worker', profile, '--test-report', str(output / 'tests.json')]),
        ('qso', [str(build / 'test_qso')]),
        ('codec', [str(build / 'test_codec')]),
        ('station', [str(build / 'test_station')]),
        ('ui-state', [str(build / 'test_ui_state')]),
        ('simulation', [str(build / 'ft8_proto'), 'simulate']),
        ('sanitizer-build', ['make', '-j4', f'BUILD={sanitize}', f'CFLAGS={flags}', 'all']),
        ('sanitizer-qso', [str(sanitize / 'test_qso')]),
        ('sanitizer-codec', [str(sanitize / 'test_codec')]),
        ('sanitizer-station', [str(sanitize / 'test_station')]),
        ('sanitizer-ui-state', [str(sanitize / 'test_ui_state')]),
        ('sanitizer-wav', [python, 'tools/development_check.py', '--test-worker', 'wav', '--test-report', str(output / 'sanitizer-tests.json')]),
    ]
    if profile == 'full':
        steps.extend([
            ('firmware-roundtrips', [python, 'tools/verify_firmware.py', '--output', str(output / 'firmware.json'), '--reports-dir', str(output / 'firmware-details')]),
            ('controller-report', [python, 'tools/controller.py', str(ROOT / 'artifacts/original/7300_142.dat'), '--output', str(output / 'controller.json'), '--verify-repeat']),
            ('reference-comparison', [python, 'tools/validate_codec.py', '--exe', str(build / 'ft8_proto'), '--work', str(output / 'codec-work'), '--jt9', str(jt9), '--output', str(output / 'codec.json')]),
        ])
    steps.append(('diff-check', ['git', 'diff', '--check']))
    return [dict(name=name, command=command, outcome='NOT_RUN') for name, command in steps]


def execute_run(profile, output, jt9, timeout):
    report = dict(schema_version=2, started_utc=datetime.now(timezone.utc).isoformat(),
                  profile=profile, scope='Current worktree, desktop only; no hardware acceptance',
                  python=sys.version, outcome='RUNNING', checks=planned_steps(profile, output, jt9),
                  limitations=['Reference benchmark PASS is not sensitivity parity.',
                               'Recovery, live capture and target runtime feasibility remain unproven.'])
    report_path = output / 'report.json'
    atomic_json(report_path, report)
    try:
        report['source_before'] = source_state()
        report['dependencies'], issues = preflight(profile, jt9)
        if issues:
            report.update(outcome='BLOCKED', blockers=issues)
        else:
            temporary = output / 'tmp'
            temporary.mkdir()
            env = dict(os.environ, FT8_PROTO=str(output / 'build/ft8_proto'), TMPDIR=str(temporary),
                       TMP=str(temporary), TEMP=str(temporary), PYTHONDONTWRITEBYTECODE='1')
            env.pop('IC7300_TEST_IMAGE', None)
            if profile == 'full':
                env['IC7300_TEST_IMAGE'] = str(ROOT / 'artifacts/original/7300_142.dat')
            for step in report['checks']:
                step_env = dict(env)
                if step['name'].startswith('sanitizer-'):
                    step_env.update(FT8_PROTO=str(output / 'sanitize/ft8_proto'),
                                    ASAN_OPTIONS='halt_on_error=1', UBSAN_OPTIONS='halt_on_error=1')
                print(f"{step['name']}: running", flush=True)
                step['outcome'] = 'RUNNING'
                atomic_json(report_path, report)
                step.update(run_step(step['command'], output / (step['name'] + '.log'), step_env, timeout))
                for name, filename in [('python-tests-no-skips', 'tests.json'), ('sanitizer-wav', 'sanitizer-tests.json')]:
                    if step['name'] == name and (output / filename).exists():
                        step['tests'] = json.loads((output / filename).read_text())
                atomic_json(report_path, report)
                print(f"{step['name']}: {step['outcome']}", flush=True)
                if step['outcome'] != 'PASS':
                    report['outcome'] = step['outcome']
                    break
            else:
                report['outcome'] = 'PASS'
    except KeyboardInterrupt:
        report['outcome'] = 'INTERRUPTED'
    except Exception as exc:
        report.update(outcome='FAIL', error=f'{type(exc).__name__}: {exc}')
    finally:
        for step in report['checks']:
            if step['outcome'] == 'RUNNING':
                step['outcome'] = report['outcome']
        try:
            report['source_after'] = source_state()
            report['source_unchanged'] = report.get('source_before') == report['source_after']
            if not report['source_unchanged'] and report['outcome'] == 'PASS':
                report.update(outcome='FAIL', error='Source changed during validation')
            report['dependencies_after'], dependency_issues = dependency_state()
            if 'dependencies' in report and report['dependencies_after'] != report['dependencies'].get('source_dependencies'):
                dependency_issues.append('Dependency state changed during validation')
            if dependency_issues and report['outcome'] == 'PASS':
                report.update(outcome='FAIL', error='; '.join(dependency_issues))
            report['executables'] = {str(path.relative_to(output)): hashlib.sha256(path.read_bytes()).hexdigest()
                                     for folder in ('build', 'sanitize') for name in ('ft8_proto', 'test_qso', 'test_codec', 'test_station')
                                     for path in [output / folder / name] if path.is_file()}
        except Exception as exc:
            report.update(outcome='FAIL', finalization_error=str(exc))
        report['finished_utc'] = datetime.now(timezone.utc).isoformat()
        atomic_json(report_path, report)
    print(f"{report['outcome']}: {report_path}", flush=True)
    return 0 if report['outcome'] == 'PASS' else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=('synthetic', 'full'), default='full')
    parser.add_argument('--output', type=Path, help='New evidence directory (must not contain whitespace; Make limitation)')
    parser.add_argument('--jt9', type=Path, default=Path('/Applications/wsjtx.app/Contents/MacOS/jt9'))
    parser.add_argument('--timeout', type=int, default=600, help='Per-step limit in seconds')
    parser.add_argument('--test-worker', choices=('synthetic', 'full', 'wav'), help=argparse.SUPPRESS)
    parser.add_argument('--test-report', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.test_worker:
        if not args.test_report:
            parser.error('--test-report required')
        return run_python_tests(args.test_worker, args.test_report)
    if args.timeout <= 0:
        parser.error('--timeout must be positive')
    output = (args.output or ROOT / 'artifacts' / datetime.now(timezone.utc).strftime('development-%Y%m%dT%H%M%S%fZ')).resolve()
    if any(c.isspace() for c in str(output)):
        parser.error('Evidence directory must not contain whitespace (Make build-path limitation)')
    output.mkdir(parents=True, exist_ok=False)
    return execute_run(args.profile, output, args.jt9.resolve(), args.timeout)


if __name__ == '__main__':
    def terminate(signum, frame):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, terminate)
    raise SystemExit(main())
