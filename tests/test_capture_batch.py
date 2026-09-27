"""Capture orchestration contracts; all child processes and devices are mocked."""
from contextlib import redirect_stdout
import io
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
import wave
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import capture_batch


class CaptureBatchTests(unittest.TestCase):
    def run_batch(self, responses):
        """Each response is a child outcome plus optional manifest quality."""
        calls = []
        responses = iter(responses)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'batch'

            def child(command, log, env, timeout):
                calls.append((command, log.name, timeout))
                response = next(responses)
                if isinstance(response, BaseException):
                    raise response
                outcome, quality = response
                folder = Path(command[command.index('--output') + 1])
                if outcome == 'PASS' and quality != 'missing':
                    folder.mkdir()
                    (folder / 'slots').mkdir()
                    slot = folder / 'slots' / '120000.wav'
                    with wave.open(str(slot), 'wb') as wav:
                        wav.setparams((1, 2, 8000 if quality == 'wrong_rate' else 12000, 0, 'NONE', 'not compressed'))
                        wav.writeframes(b'\x00\x00' * 180000)
                    if quality == 'truncated_wav':
                        slot.write_bytes(slot.read_bytes()[:-2])
                    if quality == 'malformed_wav':
                        slot.write_bytes(b'not a WAV')
                    manifest = dict(complete=True, continuity_ok=True, alignment_usable=True,
                                    wav_sha256={'slots/120000.wav': hashlib.sha256(slot.read_bytes()).hexdigest()})
                    if quality == 'empty_slots':
                        slot.unlink()
                        manifest['wav_sha256'] = {}
                    elif quality == 'missing_slot':
                        slot.unlink()
                    elif quality == 'bad_hash':
                        manifest['wav_sha256']['slots/120000.wav'] = '0' * 64
                    elif quality == 'missing_inventory':
                        del manifest['wav_sha256']
                    elif quality == 'malformed_inventory':
                        manifest['wav_sha256'] = []
                    if isinstance(quality, dict):
                        manifest.update(quality)
                    text = '{broken' if quality == 'malformed' else json.dumps([] if quality == 'array' else manifest)
                    (folder / 'capture.json').write_text(text)
                return dict(outcome=outcome)

            with patch.object(sys, 'argv', ['capture_batch.py', '--output', str(output),
                                           '--seconds', '60']), \
                    patch.object(capture_batch, 'run_step', side_effect=child), \
                    patch.object(capture_batch.shutil, 'disk_usage', return_value=SimpleNamespace(free=2 ** 31)), \
                    patch.object(capture_batch.signal, 'signal'), redirect_stdout(io.StringIO()):
                code = capture_batch.main()
            report = json.loads((output / 'report.json').read_text())
            contexts = [json.loads(path.read_text()) for path in sorted(output.glob('*/session-context.json'))]
        self.assertIn('finished_utc', report)
        self.assertEqual([item['role'] for item in report['recordings']], ['development', 'holdout'])
        self.assertNotEqual(report['outcome'], 'RUNNING')
        self.assertEqual(len(report['batch_tool_sha256']), 64)
        return code, report, calls, contexts

    def test_success_uses_only_bounded_input_capture_commands(self):
        code, report, calls, contexts = self.run_batch([('PASS', None), ('PASS', None)])
        self.assertEqual((code, report['outcome']), (0, 'PASS'))
        self.assertEqual(len(calls), 2)
        self.assertEqual([item['slots'] for item in report['recordings']], [1, 1])
        for (command, log, timeout), role in zip(calls, ('development', 'holdout')):
            self.assertEqual(command[:2], [sys.executable, str(capture_batch.ROOT / 'tools/capture_receive.py')])
            self.assertEqual(command[2:7], ['--device-name', 'USB Audio CODEC', '--seconds', '60', '--output'])
            self.assertEqual(len(command), 8)
            self.assertEqual(Path(command[7]).name, role + '-1')
            self.assertEqual(log, role + '-1.log')
            self.assertEqual(timeout, 90)
        self.assertEqual([item['holdout_reserved'] for item in contexts], [False, True])

    def test_one_retry_per_role_then_stop(self):
        code, report, calls, _ = self.run_batch([('FAIL', None)] * 4)
        self.assertEqual((code, report['outcome']), (1, 'INCOMPLETE'))
        self.assertEqual([Path(call[0][-1]).name for call in calls],
                         ['development-1', 'development-2', 'holdout-1', 'holdout-2'])
        self.assertEqual([len(item['attempts']) for item in report['recordings']], [2, 2])
        self.assertEqual([item['outcome'] for item in report['recordings']], ['FAIL', 'FAIL'])

    def test_failed_development_continues_independent_holdout(self):
        code, report, calls, _ = self.run_batch([('TIMEOUT', None), ('FAIL', None), ('PASS', None)])
        self.assertEqual((code, report['outcome']), (1, 'INCOMPLETE'))
        self.assertEqual(len(calls), 3)
        self.assertEqual([item['outcome'] for item in report['recordings']], ['FAIL', 'PASS'])

    def test_each_required_quality_flag_rejects_child_success(self):
        for flag in ('complete', 'continuity_ok', 'alignment_usable'):
            with self.subTest(flag=flag):
                code, report, calls, _ = self.run_batch([
                    ('PASS', {flag: False}), ('PASS', {flag: False}), ('PASS', None)])
                self.assertEqual((code, report['outcome']), (1, 'INCOMPLETE'))
                self.assertEqual(len(calls), 3)
                self.assertEqual(report['recordings'][0]['outcome'], 'FAIL')

    def test_retry_can_recover_without_third_attempt(self):
        code, report, calls, _ = self.run_batch([('FAIL', None), ('PASS', None), ('PASS', None)])
        self.assertEqual((code, report['outcome']), (0, 'PASS'))
        self.assertEqual(len(calls), 3)
        self.assertEqual([len(item['attempts']) for item in report['recordings']], [2, 1])

    def test_interrupt_finalizes_active_and_unexecuted_roles(self):
        for response in (('INTERRUPTED', None), KeyboardInterrupt('test interrupt')):
            with self.subTest(response=str(response)):
                code, report, calls, _ = self.run_batch([response])
                self.assertEqual((code, report['outcome']), (1, 'INTERRUPTED'))
                self.assertEqual(len(calls), 1)
                self.assertEqual([item['outcome'] for item in report['recordings']], ['INTERRUPTED', 'NOT_RUN'])
                self.assertEqual(report['recordings'][1]['attempts'], [])

    def test_invalid_manifest_finalizes_failed_attempts_and_continues(self):
        for quality in ('missing', 'malformed', 'array'):
            with self.subTest(quality=quality):
                code, report, calls, _ = self.run_batch([('PASS', quality), ('PASS', quality), ('PASS', None)])
                self.assertEqual((code, report['outcome']), (1, 'INCOMPLETE'))
                self.assertEqual(len(calls), 3)
                self.assertEqual([item['outcome'] for item in report['recordings']], ['FAIL', 'PASS'])
                self.assertTrue(all(item['outcome'] != 'PASS' for item in report['recordings'][0]['attempts']))

    def test_invalid_slots_retry_and_never_produce_success_context(self):
        for quality in ('empty_slots', 'missing_slot', 'bad_hash', 'malformed_wav',
                        'truncated_wav', 'wrong_rate',
                        'missing_inventory', 'malformed_inventory'):
            with self.subTest(quality=quality):
                code, report, calls, contexts = self.run_batch([
                    ('PASS', quality), ('PASS', quality), ('PASS', None)])
                self.assertEqual((code, report['outcome']), (1, 'INCOMPLETE'))
                self.assertEqual(len(calls), 3)
                self.assertEqual([item['outcome'] for item in report['recordings']], ['FAIL', 'PASS'])
                self.assertEqual(len(contexts), 1)
                self.assertTrue(contexts[0]['holdout_reserved'])
                self.assertTrue(all(item['outcome'] == 'FAIL'
                                    for item in report['recordings'][0]['attempts']))
                self.assertTrue(all('Invalid capture manifest' in item['error']
                                    for item in report['recordings'][0]['attempts']))

    def test_empty_capture_retry_can_recover_with_complete_slot(self):
        code, report, calls, contexts = self.run_batch([
            ('PASS', 'empty_slots'), ('PASS', None), ('PASS', None)])
        self.assertEqual((code, report['outcome']), (0, 'PASS'))
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(contexts), 2)
        self.assertEqual(report['recordings'][0]['attempts'][0]['outcome'], 'FAIL')


if __name__ == '__main__':
    unittest.main()
