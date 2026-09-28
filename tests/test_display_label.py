"""Synthetic site preimages plus opt-in original-image desktop tracing."""
import os
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from display_label import BASE, LABEL, TABLE, INDEX, TEXT, describe_site, investigate, probe_original_menu
import display_label
from firmware import checked_image


class DisplayLabelModelTests(unittest.TestCase):
    def fixture(self):
        app = bytearray(LABEL - BASE + len(TEXT) + 1)
        app[LABEL - BASE:] = TEXT + b'\0'
        struct.pack_into('<6I', app, TABLE + INDEX * 24 - BASE,
                         0x20042F3C, 0x01010009, 0x2035A3CC, LABEL, 0x2035AA24, 0x2035AA24)
        return app

    def test_same_length_label_and_descriptor_relationship(self):
        site = describe_site(self.fixture())
        self.assertEqual(site['byte_length'], 11)
        self.assertEqual(site['descriptor']['subtype'], 0)
        self.assertEqual(site['pointer_occurrences'][hex(LABEL)], ['0x20190208'])
        self.assertEqual(site['terminator'], '0x2035a777')

    def test_modified_text_terminator_descriptor_and_truncation_rejected(self):
        for location in (LABEL - BASE, LABEL - BASE + len(TEXT), TABLE + INDEX * 24 - BASE):
            app = self.fixture(); app[location] ^= 1
            with self.subTest(location=location), self.assertRaises(ValueError):
                describe_site(app)
        with self.assertRaises(ValueError):
            describe_site(self.fixture()[:-1])

    def test_structural_fixture_cannot_authorize_original_execution(self):
        with self.assertRaisesRegex(ValueError, 'exact pinned'):
            probe_original_menu(self.fixture())
        with self.assertRaises(ValueError):
            investigate(b'synthetic unknown image')


    def test_provenance_changes_during_analysis_prevent_report(self):
        for changed in ('tools', 'revision', 'dependencies'):
            with self.subTest(changed=changed), \
                    patch.object(display_label, '_investigate', return_value={'outcome': 'PASS'}), \
                    patch.object(display_label, 'tool_hashes', side_effect=[{'tool': 'before'}, {'tool': 'after' if changed == 'tools' else 'before'}]), \
                    patch.object(display_label, 'revision', side_effect=[{'commit': 'before'}, {'commit': 'after' if changed == 'revision' else 'before'}]), \
                    patch.object(display_label, 'dependency_versions', side_effect=[{'unicorn': 'before'}, {'unicorn': 'after' if changed == 'dependencies' else 'before'}]):
                with self.assertRaisesRegex(ValueError, 'changed during'):
                    investigate(b'fixture')

    def test_provenance_wrapper_records_stable_helpers_and_dependencies(self):
        with patch.object(display_label, '_investigate', return_value={'outcome': 'PASS'}), \
                patch.object(display_label, 'tool_hashes', return_value={'tool': 'hash'}), \
                patch.object(display_label, 'revision', return_value={'commit': 'same'}), \
                patch.object(display_label, 'dependency_versions', return_value={'unicorn': 'fixture'}):
            result = investigate(b'fixture')
        self.assertTrue(result['source_unchanged'])
        self.assertEqual(result['tool_sha256'], {'tool': 'hash'})
        self.assertEqual(result['dependencies'], {'unicorn': 'fixture'})


@unittest.skipUnless(os.environ.get('IC7300_TEST_IMAGE'), 'opt-in pinned original image required')
class DisplayLabelImageTests(unittest.TestCase):
    def test_original_label_path_and_dispatch_remain_unqualified(self):
        report = investigate(checked_image(Path(os.environ['IC7300_TEST_IMAGE']), 'trace'))
        self.assertEqual(report['outcome'], 'PASS')
        self.assertFalse(report['patch_qualified'])
        self.assertIsNone(report['approved_patch_interval'])
        self.assertEqual(report['probe']['renderer_arguments']['r2'], '0x2035a76c')
        self.assertEqual(report['probe']['renderer_arguments']['r3'], '0xb')
        self.assertEqual(report['probe']['subtype_dispatch'], '0x2008a70c')
        self.assertFalse(report['probe']['renderer_executed'])
        self.assertEqual(len(report['probe']['label_reads']), 12)
