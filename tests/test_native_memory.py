"""Original allocator exhaustion, reuse/coalescing and image/source guards."""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import native_memory as probe


class SyntheticMemoryTests(unittest.TestCase):
    def test_unknown_image_never_constructs_heap(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(probe,'HeapTrial') as heap:
            image=Path(directory)/'image'; image.write_bytes(b'unknown')
            with self.assertRaises(ValueError):
                probe.report(image)
            heap.assert_not_called()
        with self.assertRaisesRegex(ValueError,'exact pinned'):
            probe.HeapTrial(b'unknown')

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
class FirmwareMemoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result=probe.report(Path(IMAGE))

    def test_shared_arena_bound_reuse_coalescing_and_exhaustion(self):
        result=self.result
        self.assertEqual(result['heap']['managed_bytes'],348152)
        self.assertIsNone(result['heap']['available_on_radio'])
        rows=result['sequence']
        self.assertEqual(rows[1]['pointer'],rows[4]['pointer'])
        self.assertEqual(rows[5]['pointer'],'0x0')
        self.assertEqual(rows[5]['state'],rows[4]['state'])
        self.assertEqual(rows[8]['state']['free_blocks'],[{'offset':0,'size':348152}])
        self.assertEqual(rows[9]['requested'],348148)
        self.assertEqual(rows[9]['state']['free_blocks'],[])
        self.assertEqual(rows[10]['pointer'],'0x0')
        self.assertEqual(rows[11]['state'],rows[8]['state'])

    def test_decoded_tail_is_not_preserved_by_startup(self):
        rows=self.result['startup']['initialization_entries']
        tail=int(self.result['startup']['decoded_end'],16)
        zero=rows[1];start=int(zero['destination'],16)
        self.assertLess(start,tail)
        self.assertLess(tail,start+zero['size'])
        padding=self.result['startup']['padding_candidate']
        self.assertTrue(padding['all_ff'])
        self.assertEqual(padding['bytes'],190868)
        self.assertFalse(padding['runtime_ownership_established'])


if __name__=='__main__':unittest.main()
