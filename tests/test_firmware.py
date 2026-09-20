import hashlib
import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('firmware', Path(__file__).resolve().parents[1] / 'tools/firmware.py')
fw = importlib.util.module_from_spec(spec); spec.loader.exec_module(fw)


def fixture():
    payloads = [b'ARM!', b'\x07ABC', b'\x07DEF', b'\x07GHI']
    header = b'3wfU' + b'3.112.003.16' + struct.pack('<7I', 4, 4, 3, 4, 3, 4, 3)
    return header + b''.join(p + hashlib.md5(p).digest() for p in payloads) + b'\x37\x65'


class FirmwareTests(unittest.TestCase):
    def test_parse_integrity(self):
        b = fixture()
        self.assertEqual(len(fw.parse(b)), 4)
        for bad in (b[:10], b[:-1], b+b'x', b'BAD!'+b[4:], b[:44]+b'x'+b[45:]):
            with self.assertRaises(ValueError): fw.parse(bad)

    def test_declared_size_bound(self):
        b = bytearray(fixture()); struct.pack_into('<I', b, 16, 0xffffffff)
        with self.assertRaises(ValueError): fw.parse(b)

    def test_literals_overlap_zero_history_and_truncation(self):
        self.assertEqual(fw.lzss(b'\x07ABC', 3), (b'ABC', 4))
        self.assertEqual(fw.lzss(b'\x01A\xee\xf3', 7)[0], b'A'*7)
        self.assertEqual(fw.lzss(b'\x00\x00\x00', 3)[0], bytes(3))
        self.assertEqual(fw.lzss(b'\x01A\xee\xf3', 4)[0], b'A'*4)
        for data, size in ((b'',1), (b'\x01',1), (b'\x00\x00',3), (b'\x00\xff\xf0',3), (b'x',0), (b'x',fw.MAX_IMAGE+1)):
            with self.assertRaises(ValueError): fw.lzss(data,size)

    def test_roundtrip_preserves_opaque_trailer(self):
        b=fixture()
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp); (d/'header.bin').write_bytes(b[:44]); (d/'trailer.bin').write_bytes(b[-2:])
            for part in fw.parse(b):
                start=part['offset']; size=part['size']; name=part['name']
                (d/(name+'.stored.bin')).write_bytes(b[start:start+size])
                (d/(name+'.md5.bin')).write_bytes(b[start+size:start+size+16])
            (d/'extraction.json').write_text('{"original_sha256":"'+fw.digest(b)+'"}')
            self.assertEqual(fw.rebuild(d), b)
            (d/'trailer.bin').write_bytes(b'xx')
            with self.assertRaises(ValueError): fw.rebuild(d)

    def test_deterministic_report(self):
        self.assertEqual(fw.analyze(fixture()),fw.analyze(fixture()))


if __name__ == '__main__': unittest.main()
