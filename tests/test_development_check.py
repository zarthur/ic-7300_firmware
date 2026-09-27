import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from development_check import STRICT_TESTS, run_step


class DevelopmentCheckTests(unittest.TestCase):
    def test_failure_and_timeout_are_not_success(self):
        with tempfile.TemporaryDirectory() as temp:
            log = Path(temp) / 'step.log'
            failed = run_step([sys.executable, '-c', 'print("evidence"); raise SystemExit(3)'],
                              log, os.environ.copy(), 5)
            self.assertEqual(failed['outcome'], 'FAIL')
            self.assertEqual(failed['returncode'], 3)
            self.assertIn('evidence', log.read_text())
            timed = run_step([sys.executable, '-c', 'import time; time.sleep(60)'],
                             log, os.environ.copy(), 0.1)
            self.assertEqual(timed['outcome'], 'TIMEOUT')

    def test_skipped_or_empty_suite_cannot_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            tests = Path(temp) / 'tests'
            tests.mkdir()
            for source, expected in [('', 1),
                                     ('import unittest\nclass T(unittest.TestCase):\n @unittest.skip("missing input")\n def test_it(self): pass\n', 1),
                                     ('import unittest\nclass T(unittest.TestCase):\n def test_it(self): pass\n', 0)]:
                (tests / 'test_fixture.py').write_text(source)
                result = subprocess.run([sys.executable, '-B', '-c', STRICT_TESTS],
                                        cwd=temp, capture_output=True, timeout=10)
                self.assertEqual(result.returncode, expected, result.stderr.decode())


class ValidationReportTests(unittest.TestCase):
    def test_dependency_revision_and_dirty_checkout_rejected(self):
        import json
        from development_check import dependency_state
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            dep = root / 'dep'
            dep.mkdir()
            def git(*args):
                return subprocess.check_output(['git', *args], cwd=dep, stderr=subprocess.DEVNULL).decode().strip()
            git('init')
            (dep / 'source.c').write_text('original\n')
            git('add', '.')
            git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-m', 'fixture')
            head = git('rev-parse', 'HEAD')
            (root / 'research').mkdir()
            manifest = root / 'research/dependencies.json'
            manifest.write_text(json.dumps({'fixture': {'location': 'dep', 'revision': head}}))
            self.assertEqual(dependency_state(root)[1], [])
            manifest.write_text(json.dumps({'fixture': {'location': 'dep', 'revision': '0' * 40}}))
            self.assertIn('revision differs', dependency_state(root)[1][0])
            manifest.write_text(json.dumps({'fixture': {'location': 'dep', 'revision': head}}))
            (dep / 'source.c').write_text('changed\n')
            self.assertIn('not clean', dependency_state(root)[1][0])
            git('update-index', '--assume-unchanged', 'source.c')
            self.assertEqual(git('status', '--porcelain'), '')
            self.assertIn('source.c', dependency_state(root)[0]['fixture']['content_mismatches'])

    def test_missing_images_and_reference_only_block_full_profile(self):
        from unittest.mock import patch
        from development_check import preflight
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ('requirements-research.txt', 'requirements-audio.txt'):
                (root / name).write_text('')
            with patch('development_check.dependency_state', return_value=({}, [])), \
                 patch('development_check.capture', return_value='fixture compiler'):
                self.assertEqual(preflight('synthetic', root / 'missing-jt9', root)[1], [])
                details, issues = preflight('full', root / 'missing-jt9', root)
                self.assertEqual(len(issues), 4)
                self.assertEqual(details['images'], {})

    def test_pinned_package_mismatch_is_blocking(self):
        from unittest.mock import patch
        from development_check import preflight
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'requirements-research.txt').write_text('capstone==5.0.3\n')
            (root / 'requirements-audio.txt').write_text('')
            with patch('development_check.dependency_state', return_value=({}, [])), \
                 patch('development_check.capture', return_value='fixture compiler'), \
                 patch('development_check.importlib.metadata.version', return_value='0.0'):
                self.assertIn('expected 5.0.3', preflight('synthetic', root / 'none', root)[1][0])

    def test_atomic_report_preserves_previous_file_on_failed_replace(self):
        import json
        from unittest.mock import patch
        from development_check import atomic_json
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'report.json'
            atomic_json(path, {'outcome': 'RUNNING'})
            with patch('development_check.os.replace', side_effect=OSError('fixture')):
                with self.assertRaises(OSError):
                    atomic_json(path, {'outcome': 'PASS'})
            self.assertEqual(json.loads(path.read_text())['outcome'], 'RUNNING')
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_failed_blocked_interrupted_and_changed_runs_finalize(self):
        import json
        from unittest.mock import patch
        from development_check import execute_run
        for case in ('blocked', 'failed', 'timeout', 'interrupted', 'changed', 'oserror'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temp:
                output = Path(temp)
                initial = {'sha256': {'file': 'original'}}
                final = {'sha256': {'file': 'changed'}} if case == 'changed' else initial
                checks = [{'name': 'first', 'command': ['fixture'], 'outcome': 'NOT_RUN'},
                          {'name': 'second', 'command': ['fixture'], 'outcome': 'NOT_RUN'}]
                def step(*args):
                    if case == 'interrupted': raise KeyboardInterrupt()
                    if case == 'oserror': raise OSError('fixture spawn failure')
                    return {'outcome': {'failed': 'FAIL', 'timeout': 'TIMEOUT'}.get(case, 'PASS')}
                with patch('development_check.planned_steps', return_value=checks), \
                     patch('development_check.preflight', return_value=({'source_dependencies': {}}, ['missing fixture'] if case == 'blocked' else [])), \
                     patch('development_check.source_state', side_effect=[initial, final]), \
                     patch('development_check.dependency_state', return_value=({}, [])), \
                     patch('development_check.run_step', side_effect=step):
                    self.assertEqual(execute_run('synthetic', output, Path('/none'), 10), 1)
                report = json.loads((output / 'report.json').read_text())
                self.assertNotIn(report['outcome'], ('PASS', 'RUNNING'))
                self.assertIn('finished_utc', report)
                if case != 'changed':
                    self.assertEqual(report['checks'][1]['outcome'], 'NOT_RUN')
                if case == 'changed':
                    self.assertFalse(report['source_unchanged'])
                if case == 'blocked':
                    self.assertEqual(report['checks'][0]['outcome'], 'NOT_RUN')

    def test_timeout_terminates_descendants(self):
        import time
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            marker = root / 'survived'
            child = 'import time,pathlib; print("child ready",flush=True); time.sleep(1); pathlib.Path(' + repr(str(marker)) + ').touch(); time.sleep(60)'
            parent = 'import subprocess,sys,time; subprocess.Popen([sys.executable,"-c",' + repr(child) + ']); time.sleep(60)'
            result = run_step([sys.executable, '-c', parent], root / 'log', os.environ.copy(), 0.5)
            self.assertEqual(result['outcome'], 'TIMEOUT')
            self.assertIn('child ready', (root / 'log').read_text())
            time.sleep(0.7)
            self.assertFalse(marker.exists())

    def test_interrupt_terminates_child_process(self):
        from unittest.mock import patch
        real_popen = subprocess.Popen
        children = []
        def interrupted_popen(*args, **kwargs):
            process = real_popen(*args, **kwargs)
            original_wait = process.wait
            first = True
            def wait(*args, **kwargs):
                nonlocal first
                if first:
                    first = False
                    raise KeyboardInterrupt()
                return original_wait(*args, **kwargs)
            process.wait = wait
            children.append(process)
            return process
        with tempfile.TemporaryDirectory() as temp, patch('development_check.subprocess.Popen', side_effect=interrupted_popen):
            result = run_step([sys.executable, '-c', 'import time; time.sleep(60)'], Path(temp) / 'log', os.environ.copy(), 5)
        self.assertEqual(result['outcome'], 'INTERRUPTED')
        self.assertIsNotNone(children[0].poll())
