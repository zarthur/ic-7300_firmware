"""Original synthetic font structures; proprietary resources are opt-in only."""
import os
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import label_metrics as metrics
from firmware import checked_image


def synthetic_font():
    head = bytearray(54); struct.pack_into('>H', head, 18, 1000)
    hhea = bytearray(36); struct.pack_into('>H', hhea, 34, 3)
    # Format 4 maps A/B to glyphs 1/2; final segment is the required sentinel.
    mapping = struct.pack('>7H', 4, 32, 0, 4, 4, 1, 0)
    mapping += struct.pack('>2H', 66, 65535) + b'\0\0'
    mapping += struct.pack('>2H', 65, 65535) + struct.pack('>2H', 65472, 1)
    mapping += b'\0' * 4
    tables = {b'head': bytes(head), b'hhea': bytes(hhea),
        b'maxp': struct.pack('>IH', 0x10000, 3),
        b'hmtx': struct.pack('>HhHhHh', 0, 0, 500, 0, 600, 0),
        b'cmap': struct.pack('>HHHHI', 0, 1, 3, 1, 12) + mapping,
        b'loca': struct.pack('>4H', 0, 0, 5, 10),
        b'glyf': struct.pack('>5h', 0, 0, 0, 400, 700) + struct.pack('>5h', 0, 0, 0, 550, 700)}
    output = bytearray(struct.pack('>I4H', 0x10000, len(tables), 0, 0, 0) + bytes(16 * len(tables)))
    for index, (tag, data) in enumerate(tables.items()):
        output.extend(bytes((-len(output)) % 4))
        struct.pack_into('>4sIII', output, 12 + 16 * index, tag, 0, len(output), len(data))
        output.extend(data)
    return bytes(output)


class LabelMetricsModelTests(unittest.TestCase):
    def test_advances_and_ink_are_distinct_measurements(self):
        result = metrics.font_metrics(synthetic_font(), ('AB', 'BA'))
        self.assertEqual(result['runs']['AB']['advance'], 1100)
        self.assertEqual(result['runs']['BA']['advance'], 1100)
        self.assertEqual(result['runs']['AB']['ink'], [0, 0, 1050, 700])
        self.assertEqual(result['runs']['BA']['ink'], [0, 0, 1000, 700])

    def test_truncation_duplicate_tables_and_invalid_dimensions_rejected(self):
        original = synthetic_font()
        duplicate = bytearray(original); duplicate[28:32] = duplicate[12:16]
        overlap = bytearray(original); overlap[36:40] = overlap[20:24]
        bad_count = bytearray(original); struct.pack_into('>H', bad_count, 4, 65535)
        bad_offset = bytearray(original); struct.pack_into('>I', bad_offset, 20, len(original))
        for data in (original[:10], original[:-1], bytes(duplicate), bytes(overlap), bytes(bad_count), bytes(bad_offset)):
            with self.subTest(length=len(data)), self.assertRaises(ValueError):
                metrics.font_metrics(data, ('AB',))

    def test_unsupported_characters_and_resource_lengths_fail(self):
        for texts in ((), ('',), ('C',), ('A\n',), ('A' * 129,)):
            with self.subTest(texts=texts), self.assertRaises(ValueError):
                metrics.font_metrics(synthetic_font(), texts)
        for data in (b'', bytes(4), struct.pack('<I', 100) + b'short'):
            with self.assertRaises(ValueError):
                metrics.font_resource(data, 0)
        with self.assertRaises(ValueError):
            metrics.report(b'unknown application')

    def test_source_change_cannot_produce_report(self):
        with patch.object(metrics, '_report', return_value={'outcome': 'PASS'}), \
                patch.object(metrics, 'tool_hashes', side_effect=[{'tool': 'before'}, {'tool': 'after'}]), \
                patch.object(metrics, 'revision', return_value={'commit': 'same'}):
            with self.assertRaisesRegex(ValueError, 'Source changed'):
                metrics.report(b'fixture')


@unittest.skipUnless(os.environ.get('IC7300_TEST_IMAGE'), 'opt-in pinned official image required')
class LabelMetricsImageTests(unittest.TestCase):
    def test_two_embedded_fonts_support_conservative_proposal(self):
        report = metrics.report(checked_image(Path(os.environ['IC7300_TEST_IMAGE']), 'trace'))
        self.assertEqual(report['outcome'], 'PASS')
        self.assertFalse(report['patch_qualified'])
        self.assertFalse(report['candidate_emitted'])
        self.assertTrue(report['same_glyph_multiset'])
        self.assertTrue(report['same_advance_and_outer_ink_in_both_fonts'])
        self.assertEqual(report['changed_character_indices'], [7, 8])
        self.assertEqual([f['units_per_em'] for f in report['fonts']], [2048, 2048])
        self.assertEqual([f['runs']['Information']['advance'] for f in report['fonts']], [13174, 11264])
        self.assertEqual([f['runs']['Custom info']['advance'] for f in report['fonts']], [13263, 11264])
        for font in report['fonts']:
            old, proposed = font['runs']['Information'], font['runs']['Informaiton']
            self.assertEqual(old['advance'], proposed['advance'])
            self.assertEqual(old['ink'], proposed['ink'])
            self.assertNotEqual(old['placements'], proposed['placements'])
