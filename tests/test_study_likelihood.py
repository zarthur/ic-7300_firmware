"""Likelihood study provenance contracts; no compilers, decoders or radio I/O."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import study_likelihood as study


class LikelihoodStudyTests(unittest.TestCase):
    def run_study(self, mutation=None):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            jt9 = root / 'jt9'; jt9.write_bytes(b'reference decoder')
            original = root / 'third_party/ft8_lib/ft8/decode.c'
            original.parent.mkdir(parents=True)
            original.write_text('    ftx_normalize_logl(log174);\n')
            capture = root / 'capture'; (capture / 'slots').mkdir(parents=True)
            slot = capture / 'slots/120000.wav'; slot.write_bytes(b'recorded fixture')
            manifest = capture / 'capture.json'
            manifest.write_text(json.dumps(dict(complete=True, continuity_ok=True, alignment_usable=True,
                wav_sha256={'slots/120000.wav': study.sha(slot)})))
            reference = root / 'reference.json'
            reference.write_text(json.dumps(dict(outcome='PASS', capture=str(capture),
                capture_manifest_sha256=study.sha(manifest), reference_sha256=study.sha(jt9),
                slots=[dict(file=slot.name, sha256=study.sha(slot))])))
            output = root / 'output'
            state = {'version': 'before'}
            dependencies = {}
            calls = []

            def run(command, log, env, timeout):
                calls.append(log.stem)
                text = ''
                if command[0] == 'make':
                    build = output / 'build'
                    (build / 'lib/ft8').mkdir(parents=True)
                    (build / 'ft8_proto').write_bytes(b'base decoder')
                    (build / 'lib/ft8/decode.o').write_bytes(b'base decode object')
                    (build / 'main.o').write_bytes(b'main object')
                elif '-o' in command:
                    Path(command[command.index('-o') + 1]).write_bytes(b'compiled output')
                elif 'generate' in command:
                    Path(command[3]).write_bytes(b'generated waveform')
                elif '--capture' in command:
                    folder = Path(command[command.index('--output') + 1]); folder.mkdir()
                    (folder / 'report.json').write_text(json.dumps(dict(outcome='PASS',
                        summary=dict(new_reference_matches=0, lost_reference_matches=0))))
                elif '-8' in command:
                    text = '<DecodeFinished>\n'
                elif 'decode' in command:
                    messages = ['CQ W9XYZ EN50'] if 'ideal-residual' in command[-1] else ['CQ K1ABC FN42', 'CQ W9XYZ EN50']
                    text = ''.join(json.dumps(dict(message=m)) + '\n' for m in messages)
                log.write_text(text)
                if log.stem == 'baseline-overlap-50-0.5-ideal-residual':
                    targets = dict(input=slot, manifest=manifest, cache=reference, reference_decoder=jt9,
                        executable=output / 'baseline/ft8_proto', generated_source=output / 'baseline/decode.c',
                        generated_audio=output / 'fixtures/overlap-50-0.5_120000.wav',
                        residual=output / 'fixtures/overlap-50-0.5-ideal-residual_120000.wav',
                        object=output / 'build/main.o', metadata=output / 'baseline/capture-0/report.json')
                    if mutation in targets:
                        targets[mutation].write_bytes(b'changed during final worker')
                    elif mutation == 'source':
                        state['version'] = 'after'
                    elif mutation == 'dependency':
                        dependencies['version'] = 'after'
                    elif mutation == 'extra_slot':
                        (slot.parent / '120015.wav').write_bytes(b'extra')
                return dict(outcome='PASS')

            def write(path, samples):
                path.write_bytes(b'synthetic fixture')
                return False

            dependency_checks = 0
            def dependency_state():
                nonlocal dependency_checks
                dependency_checks += 1
                if dependency_checks == 2:
                    if mutation == 'late_audio':
                        slot.write_bytes(b'changed during final dependency check')
                    elif mutation == 'late_extra_slot':
                        (slot.parent / '120015.wav').write_bytes(b'late extra slot')
                return dependencies.copy(), []

            with patch.object(sys, 'argv', ['study_likelihood.py', '--reference', str(reference),
                    '--output', str(output), '--jt9', str(jt9), '--variant', 'baseline']), \
                    patch.object(study, 'ROOT', root), \
                    patch.object(study, 'source_state', side_effect=lambda: state.copy()), \
                    patch.object(study, 'dependency_state', side_effect=dependency_state), \
                    patch.object(study, 'run_step', side_effect=run), \
                    patch.object(study, 'read_wav', return_value=[0.1] * 4), \
                    patch.object(study, 'write_wav', side_effect=write), redirect_stdout(io.StringIO()):
                code = study.main()
            return code, json.loads((output / 'report.json').read_text()), calls

    def test_unchanged_study_passes_with_artifact_provenance(self):
        code, report, calls = self.run_study()
        self.assertEqual((code, report['outcome']), (0, 'PASS'))
        self.assertTrue(report['artifact_sha256'])
        self.assertEqual(len(report['variants'][0]['synthetic']), 6)
        self.assertIn('baseline-overlap-50-0.5-ideal-residual', calls)

    def test_mutations_during_last_worker_cannot_pass(self):
        for mutation in ('input', 'manifest', 'cache', 'reference_decoder', 'executable',
                         'generated_source', 'generated_audio', 'residual', 'object',
                         'metadata', 'source', 'dependency', 'extra_slot'):
            with self.subTest(mutation=mutation):
                code, report, calls = self.run_study(mutation)
                self.assertEqual((code, report['outcome']), (1, 'FAIL'))
                self.assertIn('error', report)
                self.assertIn('baseline-overlap-50-0.5-ideal-residual', calls)

    def test_mutation_during_final_dependency_check_cannot_pass(self):
        for mutation in ('late_audio', 'late_extra_slot'):
            with self.subTest(mutation=mutation):
                code, report, calls = self.run_study(mutation)
                self.assertEqual((code, report['outcome']), (1, 'FAIL'))
                self.assertIn('dependencies_after', report)
                self.assertIn('error', report)
                self.assertIn('baseline-overlap-50-0.5-ideal-residual', calls)
