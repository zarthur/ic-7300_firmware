import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from compare_receive import baseline_changes, capture_slots, compare_messages, parse_reference


class ReceiveComparisonTests(unittest.TestCase):
    def test_gains_cannot_hide_lost_baseline_messages(self):
        result=baseline_changes({'matched':['retained','new']},{'matched':['retained','lost']})
        self.assertEqual(result,dict(new_reference_matches=['new'],lost_reference_matches=['lost']))
        self.assertEqual(baseline_changes({'matched':['first']},None),dict(new_reference_matches=[],lost_reference_matches=[]))

    def test_reference_requires_completion_and_recognized_format(self):
        text='120000 -12 0.1 1234 ~  CQ K1ABC FN42\n<DecodeFinished>   0   1 0\n'
        result=parse_reference(text)
        self.assertEqual(result,[dict(message='CQ K1ABC FN42',snr_db=-12,dt_seconds=0.1,frequency_hz=1234)])
        with self.assertRaises(ValueError): parse_reference(text.split('<DecodeFinished>')[0])
        with self.assertRaises(ValueError): parse_reference('garbled ~ data\n<DecodeFinished>')

    def test_matching_is_per_slot_unique_text_and_proximity_is_not_attribution(self):
        reference=[dict(message='CQ K1ABC FN42',snr_db=-12,dt_seconds=0.1,frequency_hz=1000),
                   dict(message='CQ K1ABC FN42',snr_db=-5,dt_seconds=0.1,frequency_hz=1000),
                   dict(message='CQ W9XYZ EN50',snr_db=-20,dt_seconds=0.2,frequency_hz=2300)]
        candidates=[dict(frequency_hz=2300,stage='ldpc',candidate_rank=4)]
        result=compare_messages([dict(message='CQ K1ABC FN42')],reference,candidates)
        self.assertEqual((result['prototype_count'],result['reference_count']),(1,2))
        self.assertEqual(result['matched'],['CQ K1ABC FN42'])
        self.assertEqual(len(result['missed']),1)
        self.assertEqual(result['missed'][0]['category'],'nearby_candidates_without_matching_message')
        self.assertIn('not proof',result['missed'][0]['attribution'])
        absent=compare_messages([],reference,[])
        self.assertEqual(len(absent['missed']),2)
        self.assertEqual(absent['missed'][0]['snr_db'],-20)

    def test_unverified_capture_and_tampered_or_extra_slot_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'slots').mkdir()
            path=root/'slots/120000.wav';path.write_bytes(b'synthetic fixture')
            manifest=dict(complete=True,continuity_ok=True,alignment_usable=True,
                          wav_sha256={'slots/120000.wav':hashlib.sha256(path.read_bytes()).hexdigest()})
            (root/'capture.json').write_text(json.dumps(manifest))
            self.assertEqual(capture_slots(root)[1],[path])
            path.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'hash mismatch'):capture_slots(root)
            path.write_bytes(b'synthetic fixture')
            extra=root/'slots/120015.wav';extra.write_bytes(b'extra')
            with self.assertRaisesRegex(ValueError,'inventory'):capture_slots(root)
            extra.unlink()
            manifest['continuity_ok']=False
            (root/'capture.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError,'continuity'):capture_slots(root)


class ReplayProvenanceTests(unittest.TestCase):
    def test_replay_fails_closed_when_artifacts_or_source_change(self):
        from contextlib import redirect_stdout
        import io
        from unittest.mock import patch
        import compare_receive as module
        for change in (None, 'prototype', 'reference_decoder', 'manifest', 'cache',
                       'slot', 'deleted_slot', 'extra_slot', 'source', 'restored_binary'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                capture = root / 'capture'
                (capture / 'slots').mkdir(parents=True)
                slot = capture / 'slots/120000.wav'
                slot.write_bytes(b'fixture audio')
                exe = root / 'prototype'; exe.write_bytes(b'prototype')
                jt9 = root / 'jt9'; jt9.write_bytes(b'reference')
                manifest = capture / 'capture.json'
                manifest.write_text(json.dumps(dict(complete=True, continuity_ok=True,
                    alignment_usable=True, captured_frames=180000, channel_statistics=[],
                    wav_sha256={'slots/120000.wav': module.sha(slot)})))
                cache = root / 'reference.json'
                cache.write_text(json.dumps(dict(outcome='PASS',
                    capture_manifest_sha256=module.sha(manifest), reference_sha256=module.sha(jt9),
                    slots=[dict(file=slot.name, sha256=module.sha(slot), reference=[],
                                reference_elapsed_seconds=0, matched=[])])))
                cache_sha256 = module.sha(cache)
                paths = dict(prototype=exe, reference_decoder=jt9, manifest=manifest,
                             cache=cache, slot=slot)
                def decoder(command, folder, label):
                    self.assertEqual(label, 'prototype')
                    if change in paths:
                        paths[change].write_bytes(b'changed')
                    elif change == 'deleted_slot':
                        slot.unlink()
                    elif change == 'extra_slot':
                        (slot.parent / '120015.wav').write_bytes(b'extra')
                    elif change == 'restored_binary':
                        original = exe.read_bytes()
                        exe.write_bytes(b'changed')
                        exe.write_bytes(original)
                    return '{"decoded_count":0}\n{"codec_peak_heap_bytes":1}\n', 0
                argv = ['compare_receive.py', '--capture', str(capture), '--exe', str(exe),
                        '--jt9', str(jt9), '--reference', str(cache), '--output', str(root / 'out')]
                states = [{'commit': 'original'}, {'commit': 'changed' if change == 'source' else 'original'}]
                with patch.object(sys, 'argv', argv), patch.object(module, 'source_state', side_effect=states), \
                        patch.object(module, 'run_decoder', side_effect=decoder), redirect_stdout(io.StringIO()):
                    result = module.main()
                report = json.loads((root / 'out/report.json').read_text())
                self.assertEqual(result, 0 if change is None else 1)
                self.assertEqual(report['outcome'], 'PASS' if change is None else 'FAIL')
                self.assertEqual(report['reference_cache_sha256'], cache_sha256)
                if change is not None:
                    self.assertTrue(report['errors'])
