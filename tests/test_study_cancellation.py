"""Offline study reporting contracts without recording or holdout access."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import study_cancellation as study


class CancellationStudyTests(unittest.TestCase):
    def run_study(self, *, tamper=None, termination='completed', empty=False):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            exe = root / 'decoder'
            exe.write_bytes(b'fake executable, never run')
            audio = root / 'fixture.wav'
            audio.write_bytes(b'fake audio, never decoded')
            source_state = {'prototype/codec.c': 'original'}
            candidate = dict(source_sha256=source_state.copy(), executable=str(exe),
                             executable_sha256=study.sha(exe), dependencies={},
                             versions={'numpy': 'fixture', 'scipy': 'fixture'})
            candidate_path = root / 'candidate.json'
            candidate_path.write_text(json.dumps(candidate))
            fixtures = root / 'fixtures.json'
            fixtures.write_text(json.dumps(dict(cases=[] if empty else [dict(name='synthetic', path=str(audio),
                sha256=study.sha(audio), expected=['CQ K1ABC FN42'], designated_overlap=False)])))
            if tamper == 'source':
                source_state['prototype/codec.c'] = 'modified'
            if tamper == 'executable':
                exe.write_bytes(b'changed executable')
            output = root / 'report'

            def execute(command, log, timeout=150):
                folder = Path(command[command.index('--output') + 1])
                folder.mkdir()
                message = dict(message='CQ K1ABC FN42')
                result = dict(termination=termination, baseline=[message], messages=[message],
                              new_messages=[], fits=[], limits={}, resources={})
                (folder / 'result.json').write_text(json.dumps(result))
                if tamper == 'executable-during-evaluation':
                    exe.write_bytes(b'modified while worker ran')
                return dict(outcome='PASS')

            with patch.object(sys, 'argv', ['study_cancellation.py', '--output', str(output),
                    '--candidate', str(candidate_path), '--fixtures', str(fixtures), '--role', 'synthetic']), \
                    patch.object(study, 'sources', return_value=source_state), \
                    patch.object(study, 'dependency_state', return_value=({'modified': True}, [])
                                 if tamper == 'dependency' else ({}, [])), \
                    patch.object(study.importlib.metadata, 'version', return_value='changed'
                                 if tamper == 'version' else 'fixture'), \
                    patch.object(study, 'execute', side_effect=execute) as command, \
                    redirect_stdout(io.StringIO()):
                code = study.main()
            report = json.loads((output / 'report.json').read_text())
            return code, report, command.call_count

    def test_frozen_source_and_executable_tampering_refused_before_execution(self):
        for tamper in ('source', 'executable'):
            with self.subTest(tamper=tamper):
                code, report, calls = self.run_study(tamper=tamper)
                self.assertEqual((code, report['outcome']), (1, 'FAIL'))
                self.assertEqual(calls, 0)
                self.assertIn('Frozen candidate', report['error'])

    def test_dependency_and_version_tampering_refused_before_execution(self):
        for tamper in ('dependency', 'version'):
            with self.subTest(tamper=tamper):
                code, report, calls = self.run_study(tamper=tamper)
                self.assertEqual((code, report['outcome']), (1, 'FAIL'))
                self.assertEqual(calls, 0)
                self.assertIn('Frozen dependency', report['error'])

    def test_executable_mutation_during_evaluation_prevents_pass(self):
        code, report, calls = self.run_study(tamper='executable-during-evaluation')
        self.assertEqual((code, report['outcome']), (1, 'FAIL'))
        self.assertEqual(calls, 1)
        self.assertIn('changed during evaluation', report['error'])

    def test_empty_fixture_cannot_vacuously_pass(self):
        code, report, calls = self.run_study(empty=True)
        self.assertEqual((code, report['outcome']), (1, 'FAIL'))
        self.assertEqual(calls, 0)
        self.assertEqual(report['slots'], [])

    def test_core_error_or_deadline_cannot_be_successful_study(self):
        for termination in ('error', 'deadline', 'unknown-stop'):
            with self.subTest(termination=termination):
                code, report, calls = self.run_study(termination=termination)
                self.assertEqual((code, report['outcome']), (1, 'FAIL'))
                self.assertEqual(calls, 1)

    def test_completed_core_can_finish_study(self):
        code, report, calls = self.run_study()
        self.assertEqual((code, report['outcome']), (0, 'PASS'))
        self.assertEqual(calls, 1)

    def test_behavioral_repeat_ignores_measurements_but_keeps_search_limits(self):
        first = dict(termination='completed', elapsed_seconds=1.1, resources={'peak_bytes': 100},
                     limits=dict(max_passes=2, max_signals=8, deadline_seconds=120),
                     fits=[dict(start_s=.501, frequency_hz=1000.2, accepted=True)])
        repeated = dict(first, elapsed_seconds=2.2, resources={'peak_bytes': 200})
        self.assertEqual(study.behavioral(first), study.behavioral(repeated))
        changed = dict(repeated, limits=dict(max_passes=2, max_signals=8, deadline_seconds=60))
        self.assertNotEqual(study.behavioral(first), study.behavioral(changed))

    def test_evaluation_deduplicates_and_does_not_hide_losses_with_gains(self):
        result = dict(termination='completed', baseline=[{'message': 'kept'}, {'message': 'lost'}],
                      messages=[{'message': 'kept'}, {'message': 'kept'}, {'message': 'gain'}])
        evaluation = study.evaluate_result(result, dict(expected=['kept', 'lost', 'gain'],
                                                        prior_matched=['kept', 'lost']))
        self.assertEqual(evaluation['matched'], ['gain', 'kept'])
        self.assertEqual(evaluation['gained'], ['gain'])
        self.assertEqual(evaluation['lost'], ['lost'])
        self.assertEqual(evaluation['baseline_messages_lost'], ['lost'])
        self.assertEqual(evaluation['expected_missing'], ['lost'])

    def test_preservation_includes_unconfirmed_baseline_messages(self):
        result = dict(termination='completed', baseline=[{'message': 'old-unconfirmed'}],
                      messages=[{'message': 'new-unconfirmed'}])
        evaluation = study.evaluate_result(result, dict(expected=[]))
        self.assertEqual(evaluation['baseline_messages_lost'], ['old-unconfirmed'])
        self.assertEqual(evaluation['prototype_only'], ['new-unconfirmed'])
        self.assertEqual(evaluation['new_unconfirmed'], ['new-unconfirmed'])
        self.assertEqual(evaluation['gained'], [])

    def test_newly_matching_messages_use_reference_without_feedback_to_fitter(self):
        result = dict(termination='completed', baseline=[{'message': 'first'}],
                      messages=[{'message': 'first'}, {'message': 'second'}, {'message': 'unknown'}])
        evaluation = study.evaluate_result(result, dict(expected=['first', 'second']))
        self.assertEqual(evaluation['baseline_matches'], ['first'])
        self.assertEqual(evaluation['gained'], ['second'])
        self.assertEqual(evaluation['new_unconfirmed'], ['unknown'])
        self.assertEqual(evaluation['baseline_messages_lost'], [])
        self.assertEqual(evaluation['lost'], [])


if __name__ == '__main__':
    unittest.main()
