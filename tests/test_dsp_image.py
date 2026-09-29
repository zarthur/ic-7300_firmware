"""Malformed-image boundaries and original DSP structural evidence."""
import os
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import dsp_image as dsp


def words(*values):
    return struct.pack('<' + 'I' * len(values), *values)


def section(address, payload):
    return words(0x58535901, address, len(payload)) + payload + bytes((-len(payload)) % 4)


class SyntheticDSPImageTests(unittest.TestCase):
    def test_ais_offsets_trailer_and_function_arguments(self):
        prefix = words(0x41504954, 0x58535963, 0x5853590d, 0x20005, 7, 9)
        data = prefix + section(0x1000, b'abc') + words(0x58535906, 0x1002) + b'trailer'
        result = dsp.ais(data)
        self.assertEqual(result['commands'][1]['arguments'], [7, 9])
        self.assertEqual(result['sections'][0]['data_offset'], len(prefix) + 12)
        self.assertEqual(result['sections'][0]['sha256'], dsp.digest(b'abc'))
        self.assertEqual(result['entry'], 0x1002)
        self.assertEqual(result['trailer_bytes'], 7)
        self.assertEqual(result['trailer_sha256'], dsp.digest(b'trailer'))

    def test_ais_rejects_truncation_unknown_commands_padding_and_missing_close(self):
        valid = words(0x41504954) + section(0x1000, b'abc') + words(0x58535906, 0x1000)
        for length in range(len(valid)):
            with self.subTest(length=length), self.assertRaises(ValueError):
                dsp.ais(valid[:length])
        for data in (words(0, 0), words(0x41504954, 0x58535909),
                     words(0x41504954, 0x5853590d, 0xffff0005),
                     valid[:19] + b'X' + valid[20:]):
            with self.subTest(data=data), self.assertRaises(ValueError): dsp.ais(data)

    def test_ais_rejects_overlap_wrap_and_unloaded_entry(self):
        cases = [(section(0x1000, b'abcd') + section(0x1003, b'abcd'), 0x1000),
                 (section(0xffffffff, b'abcd'), 0xffffffff),
                 (section(0x1000, b'abcd'), 0x1004),
                 (section(0x1000, b''), 0x1000)]
        for body, entry in cases:
            with self.subTest(entry=entry), self.assertRaises(ValueError):
                dsp.ais(words(0x41504954) + body + words(0x58535906, entry))

    def test_initialization_padding_terminator_and_destinations(self):
        first = words(1, 0x2000) + b'A' + bytes(7)
        second = words(8, 0x3000) + b'12345678'
        valid = first + second + words(0)
        rows = dsp.initialization_records(valid)
        self.assertEqual([r['offset'] for r in rows], [0, 16])
        self.assertEqual([r['size'] for r in rows], [1, 8])
        self.assertEqual(rows[1]['sha256'], dsp.digest(b'12345678'))
        malformed = [valid[:-1], valid + b'x', first[:-1] + b'x' + second + words(0),
                     first + first + words(0), words(8, 0xfffffffc) + b'12345678' + words(0)]
        for data in malformed:
            with self.subTest(data=data), self.assertRaises(ValueError): dsp.initialization_records(data)

    def test_report_rejects_mutated_source_and_unknown_image(self):
        with self.assertRaises(ValueError): dsp.analyze(b'unknown')
        with patch.object(dsp, 'checked_image', return_value=b'input'), \
             patch.object(dsp, 'analyze', return_value={}), \
             patch.object(dsp, 'read_image', return_value=b'input'), \
             patch.object(dsp, 'tool_hashes', side_effect=[{}, {'changed': True}]):
            with self.assertRaisesRegex(ValueError, 'changed'): dsp.report(Path('unused'))


IMAGE = os.environ.get('IC7300_TEST_IMAGE')
@unittest.skipUnless(IMAGE, 'Pinned image required')
class OriginalDSPImageTests(unittest.TestCase):
    def test_original_sections_and_command_table(self):
        result = dsp.report(Path(IMAGE))
        self.assertEqual(result['program_sha256'], dsp.PROGRAM_SHA)
        self.assertEqual(result['layout']['entry'], 0x118177a0)
        self.assertEqual(result['layout']['ais_bytes'], 134272)
        self.assertEqual(result['layout']['trailer_bytes'], 29320)
        self.assertEqual(len(result['layout']['sections']), 7)
        self.assertEqual(len(result['initialization']['records']), 463)
        self.assertEqual(result['initialization']['initialized_bytes'], 4520)
        self.assertEqual(result['command_table']['command_0x42_target'], 0x11805ee4)
