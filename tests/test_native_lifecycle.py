"""Distinguish shared transport restart from native consumer backlog discard."""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import native_lifecycle as lifecycle
from emulate_platform import inputs


class SyntheticLifecycleTests(unittest.TestCase):
    def test_unknown_inputs_rejected(self):
        with self.assertRaisesRegex(ValueError,'exact pinned'):
            lifecycle.decision_probe(b'unknown','receive_ch3',[0])
        for channel, statuses in (('other',[0]),('receive_ch3',[]),('receive_ch3',[True]),('receive_ch3',[-1]),('receive_ch3',[1<<32])):
            with self.assertRaises(ValueError):lifecycle.decision_probe(b'unknown',channel,statuses)
        with self.assertRaises(ValueError):lifecycle.queue_reset_probe(b'unknown','flush',8,0)

    def test_source_mutation_invalidates_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            image=Path(directory)/'image';image.write_bytes(b'input')
            with patch.object(lifecycle,'_report',return_value={'image_sha256':lifecycle.digest(b'input')}), \
                 patch.object(lifecycle,'tool_hashes',side_effect=[{'t':'before'},{'t':'after'}]):
                with self.assertRaisesRegex(ValueError,'changed'):lifecycle.report(image)


IMAGE=os.environ.get('IC7300_TEST_IMAGE')
@unittest.skipUnless(IMAGE and importlib.util.find_spec('unicorn'),'Pinned image and Unicorn required')
class FirmwareLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):_,_,cls.app,_=inputs(Path(IMAGE))

    def test_all_status_decisions_of_all_three_handlers(self):
        statuses=list(range(256))+[0x80000000|s for s in range(256)]
        for channel in lifecycle.HANDLERS:
            for row in lifecycle.decision_probe(self.app,channel,statuses):
                status=row['status']
                expected='restart' if not status&1 else 'idle' if not status&0x40 else 'ready'
                self.assertEqual(row['decision'],expected,(channel,status))
                self.assertEqual(row['bank'],(0 if status&0x80 else 1) if expected=='ready' else None)

    def test_flush_discards_backlog_without_clearing_samples(self):
        for w in range(8):
            for r in range(8):
                row=lifecycle.queue_reset_probe(self.app,'flush',w,r)
                self.assertEqual((row['producer'],row['consumer']),(w,w))
                self.assertTrue(row['payload_unchanged'])
                self.assertEqual(row['writes'],[{'offset':577,'size':1}])

    def test_initialization_resets_cursors_without_clearing_payload(self):
        for w in range(8):
            for r in range(8):
                row=lifecycle.queue_reset_probe(self.app,'initialize',w,r)
                self.assertEqual((row['producer'],row['consumer']),(0,0))
                self.assertTrue(row['payload_unchanged'])
                self.assertEqual(row['writes'],[{'offset':576,'size':1},{'offset':577,'size':1}])

if __name__=='__main__':unittest.main()
