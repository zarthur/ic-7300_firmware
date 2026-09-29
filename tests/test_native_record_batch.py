"""Original recorder selection preserves a carrier across real batch boundaries."""
import importlib.util
import os
from pathlib import Path
import struct
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from emulate_platform import inputs
from native_record_batch import BatchTrial
from native_capture import STORAGE_SIZE
from native_transport import TransportTrial, FRAME_COUNT, recover

IMAGE = os.environ.get('IC7300_TEST_IMAGE')
@unittest.skipUnless(IMAGE and importlib.util.find_spec('unicorn'), 'Pinned image and Unicorn required')
class RecordBatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, _, cls.app, _ = inputs(Path(IMAGE))

    def test_full_carrier_survives_partial_batches_and_ring_wrap(self):
        # Valid frozen storage; synthetic clock/channel values are deliberately
        # distinctive. The already-tested ARM carrier generates all fragments.
        storage = struct.pack('<4I', 2, 512, 0, 0) + b''.join(
            struct.pack('<8I72h', i, i, 32000-i, 0, i, 31999-i, 0,
                        0x203fb180 if i%2 == 0 else 0x203fb3c0,
                        *[((i*137+j*97)%65536)-32768 for j in range(72)]) for i in range(512))
        self.assertEqual(len(storage), STORAGE_SIZE)
        writer = TransportTrial(storage)
        payloads = [bytes([0x33])*216] + [writer.run(bytes(216)) for _ in range(FRAME_COUNT)] + [bytes([0x55])*216]
        for index, first_header in ((0, False), (1913, True)):
            with self.subTest(index=index, first_header=first_header):
                trial = BatchTrial(self.app, payloads, index=index, first_header=first_header)
                chunks = []; partials = []
                for _ in range(30):
                    row = trial.select()
                    if not row['submitted']:
                        break
                    chunks.append(row['payload']); partials.append(row['remaining'])
                    self.assertEqual(row['file_change'], 0)
                    trial.advance()
                else:
                    self.fail('Recorder did not drain')
                self.assertTrue(any(partials))
                self.assertEqual(len(chunks[0]), 4052 if first_header else 4096)
                data = b''.join(chunks)
                self.assertEqual(data, b''.join(payloads))
                self.assertEqual(recover(data), storage)
                self.assertEqual(row['consumer'], (index+len(payloads))%1914)

    def test_tag_change_stops_before_other_file(self):
        trial = BatchTrial(self.app, [bytes([i])*216 for i in range(3)],
                           index=1913, tags=[0x5a, 0x5a, 0x5b])
        row = trial.select()
        self.assertEqual(row['payload'], bytes(216)+bytes([1])*216)
        self.assertEqual((row['consumer'], row['file_change']), (1, 1))
        trial.advance()
        row = trial.select()
        self.assertFalse(row['submitted'])
        self.assertEqual(row['file_change'], 1)

    def test_pause_and_partial_initial_slot(self):
        trial = BatchTrial(self.app, [bytes(range(216))]*2, paused=True)
        self.assertFalse(trial.select()['submitted'])
        trial = BatchTrial(self.app, [bytes(range(216))]*2, remaining=100)
        row = trial.select()
        self.assertEqual(row['payload'], bytes(range(116,216))+bytes(range(216)))
        self.assertEqual(row['consumer'], 2)

if __name__ == '__main__':
    unittest.main()
