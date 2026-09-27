"""Target policy tests use original synthetic bytes, never vendor payloads."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from test_firmware import fw, fixture

ROOT = Path(__file__).resolve().parents[1]


def extraction(folder, image):
    folder.mkdir()
    (folder / 'header.bin').write_bytes(image[:44])
    (folder / 'trailer.bin').write_bytes(image[-2:])
    for part in fw.parse(image):
        start, size, name = part['offset'], part['size'], part['name']
        (folder / (name + '.stored.bin')).write_bytes(image[start:start + size])
        (folder / (name + '.md5.bin')).write_bytes(image[start + size:start + size + 16])
    (folder / 'extraction.json').write_text(json.dumps({'original_sha256': fw.digest(image)}))


class TargetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.image = fixture()
        self.target = dict(model='IC-7300', version='142', image_sha256=fw.digest(self.image),
                           operations=['analyze', 'extract', 'diff', 'rebuild', 'trace'],
                           trace_payloads={'application': fw.digest(b'application')})
        self.registry = self.root / 'targets.json'
        self.save_registry()
        patcher = patch.object(fw, 'TARGET_REGISTRY', self.registry)
        patcher.start()
        self.addCleanup(patcher.stop)

    def save_registry(self):
        self.registry.write_text(json.dumps({'targets': [self.target]}))

    def cli(self, *args):
        with patch.object(sys, 'argv', ['firmware.py', *map(str, args)]), \
                contextlib.redirect_stdout(io.StringIO()) as out, \
                contextlib.redirect_stderr(io.StringIO()):
            return fw.main(), out.getvalue()

    def test_known_bytes_ignore_filename_and_allow_operations(self):
        source = self.root / 'arbitrary-name.dat'
        source.write_bytes(self.image)
        self.assertEqual(fw.checked_image(source, 'analyze'), self.image)
        report = self.root / 'report'
        self.assertEqual(self.cli('analyze', source, report)[0], 0)
        self.assertTrue(report.with_suffix('.json').exists())
        self.assertEqual(self.cli('diff', source, source)[0], 0)
        folder = self.root / 'extracted'
        extraction(folder, self.image)
        output = self.root / 'rebuilt.dat'
        self.assertEqual(self.cli('rebuild', folder, output)[0], 0)
        self.assertEqual(output.read_bytes(), self.image)

    def test_unknown_and_rechecksummed_images_produce_no_output(self):
        altered = bytearray(self.image)
        altered[44] ^= 1
        altered[48:64] = hashlib.md5(altered[44:48]).digest()
        self.assertEqual(len(fw.parse(altered)), 4)
        known = self.root / 'known.dat'
        known.write_bytes(self.image)
        for data in (b'unknown', bytes(altered)):
            source = self.root / '7300_142.dat'
            source.write_bytes(data)
            for command in ('analyze', 'extract'):
                output = self.root / command / 'output'
                self.assertEqual(self.cli(command, source, output)[0], 1)
                self.assertFalse(output.parent.exists())
            for a, b in ((known, source), (source, known)):
                status, stdout = self.cli('diff', a, b)
                self.assertEqual(status, 1)
                self.assertEqual(stdout, '')

    def test_model_and_operation_restrictions(self):
        self.target['model'] = 'IC-7300MK2'
        self.save_registry()
        with self.assertRaises(ValueError):
            fw.require_target(self.image, 'analyze')
        self.target.update(model='IC-7300', version='141', operations=['analyze'])
        self.save_registry()
        self.assertEqual(fw.require_target(self.image, 'analyze')['version'], '141')
        with self.assertRaises(ValueError):
            fw.require_target(self.image, 'trace')

    def test_tampered_rebuild_manifest_cannot_authorize_image(self):
        folder = self.root / 'extracted'
        extraction(folder, self.image)
        output = self.root / 'out.dat'
        (folder / 'trailer.bin').write_bytes(b'xx')
        self.assertEqual(self.cli('rebuild', folder, output)[0], 1)
        changed = self.image[:-2] + b'xx'
        (folder / 'extraction.json').write_text(json.dumps({'original_sha256': fw.digest(changed)}))
        self.assertEqual(self.cli('rebuild', folder, output)[0], 1)
        self.assertFalse(output.exists())

    def test_trace_checks_source_and_application(self):
        folder = self.root / 'extracted'
        extraction(folder, self.image)
        app = folder / 'application.decoded.bin'
        app.write_bytes(b'application')
        self.assertEqual(fw.trace_inputs(folder), (b'application', b'ARM!'))
        app.write_bytes(b'mismatched application')
        with self.assertRaisesRegex(ValueError, 'Decoded application'):
            fw.trace_inputs(folder)
        app.write_bytes(b'application')
        self.target['operations'].remove('trace')
        self.save_registry()
        with self.assertRaisesRegex(ValueError, 'unsupported'):
            fw.trace_inputs(folder)
        self.target['operations'].append('trace')
        self.save_registry()
        (folder / 'main.stored.bin').write_bytes(b'FAKE')
        with self.assertRaises(ValueError):
            fw.trace_inputs(folder)

    def test_real_cli_has_no_registry_override_or_output_on_rejection(self):
        folder = self.root / 'extracted'
        extraction(folder, self.image)
        output = self.root / 'report.json'
        run = subprocess.run([sys.executable, str(ROOT / 'tools/trace.py'), str(folder), str(output)],
                             capture_output=True, text=True)
        self.assertNotEqual(run.returncode, 0)
        self.assertIn('Unsupported image', run.stderr)
        self.assertFalse(output.exists())
        self.assertFalse((folder / 'assembly').exists())

    def test_registry_matches_pinned_research_and_acquisition(self):
        registry = json.loads((ROOT / 'research/targets.json').read_text())['targets']
        acquired = json.loads((ROOT / 'research/acquisition.json').read_text())['releases']
        results = json.loads((ROOT / 'research/firmware-results.json').read_text())['releases']
        self.assertEqual([r['version'] for r in registry], ['140', '141', '142'])
        for target, acquisition, result in zip(registry, acquired, results):
            self.assertEqual(target['image_sha256'], acquisition['image_sha256'])
            self.assertEqual(target['image_sha256'], result['sha256'])
            self.assertEqual(target['development_base'], target['version'] == '142')
            self.assertEqual('trace' in target['operations'], target['version'] == '142')
            if target['version'] == '142':
                self.assertEqual(target['trace_payloads']['application'], result['decoded']['application']['sha256'])


if __name__ == '__main__':
    unittest.main()
