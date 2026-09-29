"""Execute v2 ARM export and distinguish complete transport from full capture."""
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from native_capture_v2 import CaptureTrial, decode_storage
import native_transport as legacy
import native_transport_v2 as transport


class NativeTransportV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = bytes(range(216))
        full = CaptureTrial()
        for _ in range(512):
            full.call('begin'); full.call('finish')
        aborted = CaptureTrial()
        aborted.call('begin'); aborted.call('begin')
        aborted.call('finish'); aborted.call('finish')
        empty = CaptureTrial()
        empty.call('begin'); empty.call('begin')
        empty.call('cancel'); empty.call('cancel')
        cls.fixtures = []
        for capture in (full, aborted, empty):
            storage = capture.storage()
            writer = transport.TransportTrial(storage)
            frames = [writer.run(cls.original) for _ in range(transport.FRAME_COUNT)]
            cls.fixtures.append((storage, frames, writer))

    def test_full_and_aborted_roundtrips_keep_capture_status(self):
        self.assertEqual(transport.FRAME_COUNT, 598)
        for (storage, frames, writer), expected in zip(self.fixtures, ((2,512),(5,1),(6,0))):
            with self.subTest(status=expected):
                recovered = transport.recover(b'prefix'+b'audio'.join(frames)+b'suffix')
                self.assertEqual(recovered, storage)
                decoded = decode_storage(recovered)
                self.assertEqual((decoded['status'], decoded['count']), expected)
                self.assertEqual(writer.control(), (598,2))
                self.assertEqual(writer.run(self.original), self.original)
                self.assertEqual(writer.control(), (598,2))
                self.assertEqual(struct.unpack_from('<I', frames[-1],16)[0], 80)
                self.assertEqual(frames[-1][104:], bytes(112))

    def test_inactive_capture_and_terminal_export_preserve_audio(self):
        base = self.fixtures[0][0]
        for status in (0,1,3,4,0xffffffff):
            data = struct.pack('<I',status)+base[4:]
            writer = transport.TransportTrial(data)
            self.assertEqual(writer.run(self.original), self.original)
            self.assertEqual(writer.control(), (0,0))
        for status in (2,3,0xffffffff):
            writer = transport.TransportTrial(base,status=status)
            self.assertEqual(writer.run(self.original), self.original)
            self.assertEqual(writer.control(), (0,status))

    def test_inconsistent_frozen_headers_and_indices_fail_closed(self):
        base = self.fixtures[0][0]
        for offset,value in ((4,1),(8,0),(12,1)):
            bad = bytearray(base); struct.pack_into('<I',bad,offset,value)
            writer = transport.TransportTrial(bytes(bad))
            self.assertEqual(writer.run(self.original), self.original)
            self.assertEqual(writer.control(), (0,3))
        for status,count in ((5,0),(5,513),(6,512),(2,513)):
            bad = struct.pack('<2I',status,count)+base[8:]
            writer = transport.TransportTrial(bad)
            self.assertEqual(writer.run(self.original), self.original)
            self.assertEqual(writer.control(), (0,3))
        for index in (598,599,0xffffffff):
            writer = transport.TransportTrial(base,index=index)
            self.assertEqual(writer.run(self.original), self.original)
            self.assertEqual(writer.control(), (index,3))

    def test_corruption_and_cross_file_assembly_rejected(self):
        frames = self.fixtures[0][1]
        complete = b''.join(frames)
        corrupt = bytearray(complete); corrupt[24] ^= 1
        padding = bytearray(complete); padding[-1] = 1
        for bad in (bytes(corrupt),bytes(padding),complete[:-1],b''.join(frames[1:]),
                    frames[1]+frames[0]+b''.join(frames[2:]),frames[0]+complete,
                    complete+complete,b''.join(frames[:200]),b''.join(frames[200:]),b''):
            with self.assertRaises(ValueError): transport.recover(bad)

    def test_version_one_decoder_does_not_accept_version_two(self):
        self.assertEqual(legacy.MAGIC, b'IC73RX01')
        self.assertEqual(legacy.FRAME_COUNT, 470)
        with self.assertRaises(ValueError): legacy.recover(b''.join(self.fixtures[0][1]))


if __name__ == '__main__': unittest.main()
