"""Task-ID exhaustion and original file-worker argument/result translation."""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import native_export as probe


class SyntheticExportTests(unittest.TestCase):
    def test_unknown_image_and_invalid_stimuli(self):
        with self.assertRaisesRegex(ValueError,'exact pinned'):probe.task_id_probe(b'unknown',[False]*11)
        with self.assertRaisesRegex(ValueError,'exact pinned'):probe.worker_probe(b'unknown','write',0)
        for occupied in ([],[False]*12,[0]*11):
            with self.assertRaises(ValueError):probe.task_id_probe(b'unknown',occupied)
        for op,value in (('delete',0),('write',True),('write',1<<31)):
            with self.assertRaises(ValueError):probe.worker_probe(b'unknown',op,value)

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
class FirmwareExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.result=probe.report(Path(IMAGE))

    def test_task_ids_do_not_extend_past_eleven_slots(self):
        for n,row in enumerate(self.result['task_id_prefixes']):
            self.assertEqual(row['r0'],n+1 if n<11 else 0)
            self.assertTrue(row['table_unchanged'])
        for n,row in enumerate(self.result['task_id_holes']):
            self.assertEqual(row['r0'],n+1)
            self.assertTrue(row['table_unchanged'])

    def test_worker_argument_abi_and_negative_errors(self):
        for row in self.result['file_workers']:
            args=row['forwarded_arguments']
            if row['operation']=='open':self.assertEqual(args,[probe.SOURCE,0x8400,0x180,0x02200000])
            else:self.assertEqual(args[:3],[7,probe.SOURCE,90128])
            value=row['underlying_result_fixture']
            self.assertEqual(row['output_value'],value)
            self.assertEqual(row['completion_result'],value if value<0 else 0)
            self.assertTrue(row['guards_preserved'])
            self.assertFalse(row['file_operation_executed'])

    def test_publication_gate_is_watermark_hysteresis_not_recording_start(self):
        for row in self.result['publication_gate']:
            distance=row['distance']
            expected=1 if distance<=1879 else 0 if distance>=1909 else row['previous']
            self.assertEqual(row['enabled'],expected)

    def test_carrier_preserves_native_publication_lifecycle(self):
        import struct
        import native_transport as carrier
        for row in self.result['publication']:
            index=row['index_before']
            self.assertEqual(row['copy_arguments'],[0x204a0600+index*220+4,0x203fc76c,216])
            self.assertEqual(row['index_after'],(index+1)%1914)
            self.assertEqual(row['fill_after'],0)
            published=bytes.fromhex(row['published_hex'])
            self.assertEqual(published[:4],b'\xa5\x5a\x01\xa5')
            frame=published[4:]
            self.assertEqual(frame[:8],carrier.MAGIC)
            self.assertEqual(struct.unpack_from('<3I',frame,8),(90128,0,192))
            self.assertEqual(struct.unpack_from('<I',frame,20)[0],carrier.checksum(frame[24:]))
            self.assertEqual(row['next_slot_hex'],bytes(220).hex())
            self.assertEqual(set(row['changed_slots']),{index,(index+1)%1914})
            self.assertTrue(row['scratch_unchanged'])
            self.assertTrue(row['capture_unchanged'])
            self.assertFalse(row['firmware_hook_installed'])

    def test_short_write_has_success_status_but_short_actual_count(self):
        row=next(r for r in self.result['file_workers'] if r['operation']=='write' and r['underlying_result_fixture']==7)
        self.assertEqual(row['completion_result'],0)
        self.assertEqual(row['output_value'],7)
        self.assertLess(row['output_value'],row['forwarded_arguments'][2])


if __name__=='__main__':unittest.main()
