"""Exercise the original ARM recorder carrier and recover exact capture bytes."""
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from native_capture import CaptureTrial, build_core, STORAGE_SIZE
import native_transport as transport


class NativeTransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        capture=CaptureTrial(build_core())
        for i in range(512):
            capture.run(struct.pack('<72h',*[(i+j*97)%65536-32768 for j in range(72)]),
                        [(0xfffffff0+i)&0xffffffff,i,0,0x40,0x80,9,10])
        cls.storage=capture.storage()
        writer=transport.TransportTrial(cls.storage)
        cls.frames=[];cls.maximum_instructions=0
        for i in range(transport.FRAME_COUNT):
            cls.frames.append(writer.run(bytes([i&255])*216))
            cls.maximum_instructions=max(cls.maximum_instructions,writer.instructions)
        cls.writer=writer

    def test_complete_carrier_roundtrip_and_automatic_stop(self):
        self.assertEqual(transport.FRAME_COUNT,470)
        self.assertEqual(transport.recover(b'carrier prefix'+b''.join(self.frames)+b'trailer'),self.storage)
        self.assertLess(self.maximum_instructions,1300)
        self.assertEqual(self.writer.control(),(470,2))
        original=bytes(range(216))
        self.assertEqual(self.writer.run(original),original)
        self.assertEqual(self.writer.control(),(470,2))
        self.assertEqual(transport.checksum(b'hello'),0x4f9f2cab)

    def test_last_frame_length_and_zero_padding(self):
        total,offset,length,crc=struct.unpack_from('<4I',self.frames[-1],8)
        self.assertEqual((total,offset,length),(STORAGE_SIZE,90048,80))
        self.assertEqual(self.frames[-1][24:104],self.storage[-80:])
        self.assertEqual(self.frames[-1][104:],bytes(112))
        self.assertEqual(crc,transport.checksum(self.storage[-80:]))

    def test_waiting_or_terminal_states_preserve_original_payload(self):
        for capture_status,transport_status in ((0,0),(1,0),(3,0),(4,0),(2,2),(2,3),(2,0xffffffff)):
            with self.subTest(capture_status=capture_status,transport_status=transport_status):
                storage=struct.pack('<I',capture_status)+self.storage[4:]
                trial=transport.TransportTrial(storage,status=transport_status)
                original=bytes(range(216))
                self.assertEqual(trial.run(original),original)
                self.assertEqual(trial.control(),(0,transport_status))

    def test_invalid_index_or_full_count_falls_back_without_overrun(self):
        for index,count in ((470,512),(0xffffffff,512),(0,511),(0,0xffffffff)):
            with self.subTest(index=index,count=count):
                storage=self.storage[:4]+struct.pack('<I',count)+self.storage[8:]
                trial=transport.TransportTrial(storage,index=index)
                original=bytes(range(216))
                self.assertEqual(trial.run(original),original)
                self.assertEqual(trial.control(),(index,3))

    def test_corrupt_missing_reordered_duplicate_and_truncated_frames_rejected(self):
        complete=b''.join(self.frames)
        corrupt=bytearray(complete);corrupt[24]^=1
        padding=bytearray(complete);padding[-1]=1
        for blob in (complete[:-1],complete[216:],self.frames[0]+complete,
                     self.frames[1]+self.frames[0]+b''.join(self.frames[2:]),bytes(corrupt),bytes(padding),b''):
            with self.assertRaises(ValueError):transport.recover(blob)
        # The decoder never combines separate partial captures implicitly.
        for blob in (b''.join(self.frames[:200]),b''.join(self.frames[200:])):
            with self.assertRaises(ValueError):transport.recover(blob)


if __name__=='__main__':unittest.main()
