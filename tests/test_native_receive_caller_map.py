"""Bounded exact-image checks for the DSP receive caller's static input flow."""
from pathlib import Path
import json
import os
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import native_receive_caller_map as caller_map


class CallerMapInputTests(unittest.TestCase):
    def test_rejects_unknown_program(self):
        with self.assertRaisesRegex(ValueError, 'exact pinned DSP program'):
            caller_map.verify_program_words(b'not a DSP program')

    def test_rejects_unknown_container(self):
        with self.assertRaisesRegex(ValueError, 'Unsupported image SHA-256'):
            caller_map.analyze_image(b'unknown')


IMAGE = os.environ.get('IC7300_TEST_IMAGE')
@unittest.skipUnless(IMAGE and Path(IMAGE).is_file(), 'Pinned original IC-7300 image required')
class PinnedCallerMapTests(unittest.TestCase):
    def test_argument_alias_and_control_branch_words(self):
        report = caller_map.report(Path(IMAGE))
        self.assertEqual(report['program_sha256'], caller_map.PROGRAM_SHA256)
        self.assertEqual(len(report['verified_words']), len(caller_map.CALLER_WORDS))
        self.assertIn('pointee contents are not', report['static_dataflow'][0])
        self.assertIn('Neither live value nor destination-block semantics are established',
                      report['static_dataflow'][2])
        self.assertIn('B14 state', report['runtime_inputs_not_in_capture'][1])
        self.assertIn('cannot select the physical serializer phase', report['limits'][2])


ROOT = Path(__file__).resolve().parents[1]
RESTORED_PROGRAM = ROOT / 'artifacts/restored-dsp-lane-slices-20261001/dsp_program.decoded.bin'
RESTORATION_MANIFEST = ROOT / 'artifacts/restored-dsp-lane-slices-20261001/restoration-manifest.json'


@unittest.skipUnless(RESTORED_PROGRAM.is_file() and RESTORATION_MANIFEST.is_file(),
                     'Restored pinned DSP program bundle required')
class RestoredCallerMapTests(unittest.TestCase):
    def test_exact_decoded_program_words_and_offsets(self):
        report = caller_map.report_restored_program(RESTORED_PROGRAM, RESTORATION_MANIFEST)
        self.assertEqual(report['program_sha256'], caller_map.PROGRAM_SHA256)
        self.assertEqual(len(report['verified_words']), len(caller_map.CALLER_WORDS))
        self.assertEqual(report['source_evidence']['restored_program_sha256'],
                         caller_map.PROGRAM_SHA256)
        words = {row['address']: row for row in report['verified_words']}
        self.assertEqual(words['0x1180e92e']['disassembly'], 'mv a4,a0')
        self.assertEqual(words['0x1180e944']['disassembly'],
                         '[b0] bnop 0x1180e95c,4')
        self.assertEqual(words['0x1180eb88']['encoding'], '0xf4ba')
        self.assertEqual(words['0x1180ed24']['decoded_program_file_offset_bytes'], '0xed4c')
        self.assertIn('0x11807b2c', report['static_dataflow'][3])

    def test_rejects_manifest_for_different_image(self):
        program = RESTORED_PROGRAM.read_bytes()
        manifest = json.loads(RESTORATION_MANIFEST.read_text())
        manifest['independent_clean_image_report']['container_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'pinned clean image/program'):
            caller_map.analyze_restored_program(program, manifest)


if __name__ == '__main__':
    unittest.main()
