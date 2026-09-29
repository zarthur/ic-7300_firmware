"""Original recorder batching preserves all v2 frozen capture forms."""
import importlib.util
import os
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from emulate_platform import inputs
from native_capture_v2 import CaptureTrial,decode_storage
from native_transport_v2 import TransportTrial,FRAME_COUNT,recover
from native_record_batch import BatchTrial

IMAGE=os.environ.get('IC7300_TEST_IMAGE')
@unittest.skipUnless(IMAGE and importlib.util.find_spec('unicorn'),'Pinned image and Unicorn required')
class V2RecordBatchTests(unittest.TestCase):
    def test_full_and_aborted_exports_survive_partial_batches_and_wrap(self):
        _,_,app,_=inputs(Path(IMAGE))
        full=CaptureTrial()
        for _ in range(512):full.call('begin');full.call('finish')
        partial=CaptureTrial();partial.call('begin');partial.call('begin');partial.call('finish');partial.call('finish')
        empty=CaptureTrial();empty.call('begin');empty.call('begin');empty.call('cancel');empty.call('cancel')
        for capture in (full,partial,empty):
            storage=capture.storage();writer=TransportTrial(storage)
            payloads=[b'\x33'*216]+[writer.run(bytes(216)) for _ in range(FRAME_COUNT)]+[b'\x55'*216]
            for index,header in ((0,False),(1913,True)):
                with self.subTest(status=decode_storage(storage)['status'],index=index,header=header):
                    trial=BatchTrial(app,payloads,index=index,first_header=header)
                    chunks=[];partials=[]
                    # 129600 bytes require 32 batches; bound the fixture's drain.
                    for _ in range(40):
                        row=trial.select()
                        if not row['submitted']:break
                        chunks.append(row['payload']);partials.append(row['remaining'])
                        self.assertEqual(row['file_change'],0)
                        trial.advance()  # Original bookkeeping only, not I/O success.
                    else:self.fail('Recorder did not drain')
                    data=b''.join(chunks)
                    self.assertEqual(data,b''.join(payloads))
                    self.assertEqual(recover(data),storage)
                    self.assertEqual(len(chunks),32)
                    self.assertTrue(any(partials))
                    self.assertEqual(len(chunks[0]),4052 if header else 4096)
                    self.assertEqual(row['consumer'],(index+len(payloads))%1914)


if __name__=='__main__':unittest.main()
