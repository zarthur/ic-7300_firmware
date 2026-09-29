"""Execute the compiled capture core with bounded RAM and adversarial controls."""
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import native_capture as capture


class NativeCaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.code=capture.build_core()

    def test_full_capture_retains_signed_streams_and_raw_rollovers(self):
        trial=capture.CaptureTrial(self.code)
        samples=struct.pack('<72h',*([-32768,-1,0,32767]*18))
        for i in range(capture.CAPACITY):
            observations=[(0xfffffff0+i)&0xffffffff,i,0xffffffff,0,0x40,0x80,i^0xabcd]
            self.assertEqual(trial.run(samples,observations),1)
            self.assertLess(trial.instructions,400)
        data=trial.storage()
        decoded=capture.decode_storage(data)
        self.assertEqual((decoded['status'],decoded['count']),(2,512))
        for i,row in enumerate(decoded['records']):
            self.assertEqual(row['sequence'],i)
            self.assertEqual(row['observations'][0],(0xfffffff0+i)&0xffffffff)
            self.assertEqual(row['stream_a'],[-32768,-1,0,32767]*9)
            self.assertEqual(row['stream_b'],row['stream_a'])
        self.assertEqual(trial.run(bytes(144),[0]*7),0)
        self.assertEqual(trial.storage(),data)
        self.assertEqual(trial.writes,[])

    def test_disabled_full_invalid_busy_and_unknown_states_never_write(self):
        for status in (0,2,3,4,0xffffffff):
            with self.subTest(status=status):
                trial=capture.CaptureTrial(self.code,status=status,count=37)
                before=trial.storage()
                self.assertEqual(trial.run(bytes(144),[0]*7),0)
                self.assertEqual(trial.storage(),before)
                self.assertEqual(trial.writes,[])

    def test_corrupt_count_cannot_overrun_storage(self):
        for count in (512,513,0xffffffff):
            with self.subTest(count=count):
                trial=capture.CaptureTrial(self.code,count=count)
                before=trial.storage()
                self.assertEqual(trial.run(bytes(144),[0]*7),0xffffffff)
                self.assertEqual(trial.storage(),struct.pack('<I',3)+before[4:])
                self.assertEqual(trial.writes,[(capture.STATE,4)])

    def test_append_touches_only_control_and_selected_record(self):
        for count in (0,1,511):
            with self.subTest(count=count):
                trial=capture.CaptureTrial(self.code,count=count)
                before=trial.storage()
                samples=bytes(range(144));observations=list(range(7))
                trial.run(samples,observations)
                after=trial.storage()
                start=capture.CONTROL_SIZE+count*capture.RECORD_SIZE
                self.assertEqual(after[8:start],before[8:start])
                self.assertEqual(after[start+capture.RECORD_SIZE:],before[start+capture.RECORD_SIZE:])
                self.assertEqual(after[start:start+capture.RECORD_SIZE],struct.pack('<8I',count,*observations)+samples)
                self.assertEqual(struct.unpack_from('<2I',after),(2 if count==511 else 1,count+1))

    def test_build_rejects_relocations_and_extra_allocated_data(self):
        for source in ('.syntax unified\n.arm\n.text\n.balign 4\nbl external\n',
                       '.syntax unified\n.arm\n.text\n.balign 4\nbx lr\n.data\n.word 1\n'):
            with tempfile.TemporaryDirectory() as directory:
                path=Path(directory)/'invalid.S';path.write_text(source)
                with patch.object(capture,'SOURCE',path),self.assertRaises(ValueError):capture.build_core()
        for data in (b'',b'\x7fELF'+bytes(60)):
            with self.assertRaises(ValueError):capture.text_section(data)

    def test_decoder_rejects_incomplete_or_corrupt_control_and_sequence(self):
        trial=capture.CaptureTrial(self.code)
        trial.run(bytes(144),[0]*7)
        good=trial.storage()
        self.assertEqual(capture.decode_storage(good)['count'],1)
        for data in (good[:-1],struct.pack('<I',4)+good[4:],
                     struct.pack('<2I',2,1)+good[8:],
                     good[:8]+struct.pack('<I',1)+good[12:],
                     good[:16]+struct.pack('<I',99)+good[20:]):
            with self.assertRaises(ValueError):capture.decode_storage(data)


if __name__=='__main__':unittest.main()
