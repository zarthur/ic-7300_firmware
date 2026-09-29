"""Startup mapping permissions, padding survival and fail-closed evidence guards."""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import native_placement as probe


class SyntheticPlacementTests(unittest.TestCase):
    def test_permissions_and_descriptor_kind(self):
        result=probe.section_fields(0x20385c06)
        self.assertEqual(result['physical_base'],'0x20300000')
        self.assertFalse(result['execute_never'])
        self.assertEqual(result['access_permissions'],3)
        self.assertEqual(probe.section_fields(0x2038dc16)['access_permissions'],7)
        self.assertTrue(probe.section_fields(0x2038dc16)['execute_never'])
        for value in (-1,1<<32,True,0,1,3,0x203c5c06):
            with self.subTest(value=value),self.assertRaises(ValueError):probe.section_fields(value)

    def test_unknown_image_and_invalid_fixture(self):
        with self.assertRaisesRegex(ValueError,'exact pinned'):probe.mapping_probe(b'unknown')
        for size in (0,1,5,-4,True,4097):
            with self.subTest(size=size),self.assertRaises(ValueError):probe.zero_helper_probe(b'unknown',size)

    def test_source_mutation_invalidates_evidence(self):
        for change in ('image','restored_image','tool','revision',None):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as directory:
                image=Path(directory)/'image';image.write_bytes(b'initial')
                initial=probe.digest(image.read_bytes())
                def evaluate(path):
                    if change in ('image','restored_image'):
                        path.write_bytes(b'changed')
                        if change=='restored_image':path.write_bytes(b'initial')
                    return {'image_sha256':initial}
                with patch.object(probe,'_report',side_effect=evaluate), \
                        patch.object(probe,'tool_hashes',side_effect=[{'t':'before'},{'t':'after' if change=='tool' else 'before'}]), \
                        patch.object(probe,'revision',side_effect=['before','after' if change=='revision' else 'before']):
                    if change:
                        with self.assertRaisesRegex(ValueError,'changed'):probe.report(image)
                    else:self.assertTrue(probe.report(image)['source_unchanged'])


IMAGE=os.environ.get('IC7300_TEST_IMAGE')
@unittest.skipUnless(IMAGE and importlib.util.find_spec('unicorn'),'Opt-in pinned image and Unicorn required')
class FirmwarePlacementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.result=probe.report(Path(IMAGE))

    def test_completed_table_preserves_application_mapping(self):
        mapping=self.result['mapping']
        self.assertEqual(mapping['padding_section'],'0x20385c06')
        self.assertTrue(mapping['same_attributes_as_application'])
        self.assertEqual(mapping['regular_section_aliases'],['0x20300000'])
        self.assertFalse(mapping['hardware_mapping_executed'])

    def test_scatter_destinations_and_ignored_zero_source(self):
        self.assertEqual(self.result['scatter_destination_overlaps'],[])
        for row in self.result['zero_helper']:
            self.assertTrue(row['all_zero'])
            self.assertTrue(row['guards_preserved'])
            self.assertEqual(row['source_reads'],[])
        self.assertFalse(self.result['placement_ready_for_installation'])


if __name__=='__main__':unittest.main()
