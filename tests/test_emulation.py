import importlib.util
import os
from pathlib import Path
import struct
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import emulate_platform as ep
AVAILABLE=importlib.util.find_spec('unicorn') is not None
IMAGE=os.environ.get('IC7300_TEST_IMAGE')


@unittest.skipUnless(AVAILABLE,'Optional pinned Unicorn required')
class EngineTests(unittest.TestCase):
    def test_transfer_rejects_invalid_initial_state_before_execution(self):
        for kwargs in ({'initial_content': b'A'},
                       {'initial_content': bytes(65536), 'initial_equal': True},
                       {'initial_content': bytearray(65536)},
                       {'destination': 0, 'payload': bytes(65537)},
                       {'destination': 0x400000, 'payload': bytes(0x3f0001)}):
            options = dict(payload=b'A'); options.update(kwargs)
            with self.assertRaises(ValueError): ep.transfer(b'', **options)

    def test_return_and_limits(self):
        uc,u,a=ep.engine();uc.mem_map(0x1000,0x1000)
        uc.mem_write(0x1000,struct.pack('<I',0xe12fff1e)) # synthetic bx lr
        ep.execute(uc,0x1000)
        uc.mem_write(0x1010,struct.pack('<I',0xeafffffe)) # synthetic b .
        with self.assertRaisesRegex(ValueError,'limit'): ep.execute(uc,0x1010,budget=20)

    def test_unmapped_peripheral_stops(self):
        uc,u,a=ep.engine();uc.mem_map(0x1000,0x1000)
        uc.mem_write(0x1000,struct.pack('<I',0xe5910000)) # synthetic ldr r0,[r1]
        uc.reg_write(a.UC_ARM_REG_R1,0xf0000000)
        with self.assertRaisesRegex(ValueError,'Emulation stopped'): ep.execute(uc,0x1000)


    def test_loader_rejects_access_hidden_in_page_padding(self):
        def loader(*words):
            return bytes(0x25c) + struct.pack('<' + 'I' * len(words), *words)
        # Write one byte beyond a one-byte output, then return the expected size.
        code = loader(0xe5c02001, 0xe3a00001, 0xe12fff1e)
        with self.assertRaisesRegex(ValueError, 'exact byte bounds'):
            ep.decode_loader(code, b'A', 1)
        # A word store starts in range but crosses the byte-sized output end.
        code = loader(0xe5802000, 0xe3a00001, 0xe12fff1e)
        with self.assertRaisesRegex(ValueError, 'exact byte bounds'):
            ep.decode_loader(code, b'A', 1)
        # Read before the supplied source, inside the mapped prefix padding.
        code = loader(0xe5513001, 0xe3a00001, 0xe12fff1e)
        with self.assertRaisesRegex(ValueError, 'exact byte bounds'):
            ep.decode_loader(code, b'A', 1)
        # Output reads must not consume mapped padding either.
        code = loader(0xe5d03001, 0xe5c03000, 0xe3a00001, 0xe12fff1e)
        with self.assertRaisesRegex(ValueError, 'exact byte bounds'):
            ep.decode_loader(code, b'A', 1)
        # In-range copy still succeeds and reports the observed access extents.
        code = loader(0xe5d13000, 0xe5c03000, 0xe3a00001, 0xe12fff1e)
        result, report = ep.decode_loader(code, b'A', 1)
        self.assertEqual(result, b'A')
        self.assertEqual(report['access_bounds'], {'source_read_end': 1, 'output_write_end': 1, 'output_read_end': 0})


@unittest.skipUnless(AVAILABLE and IMAGE,'Opt-in user-acquired firmware required')
class FirmwareEmulationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _,cls.main,cls.app,_=ep.inputs(Path(IMAGE))

    def test_loader_lookahead_and_roundtrip(self):
        # Original literal-only LZSS fixture; no image packing tooling required.
        data=b'ABCABCABC'
        encoded=b'\xffABCABCAB\x01C'
        actual,report=ep.decode_loader(self.main[0x4000:0x4650],encoded+b'\0'*3,len(data))
        self.assertEqual(actual,data)
        self.assertGreaterEqual(report['source_bytes_advanced'],len(encoded))
        with self.assertRaises(ValueError): ep.decode_loader(self.main[0x4000:0x4650],b'\xff',100)

    def test_full_application_transfer_and_explicit_destination_units(self):
        payload = self.main[0x10000:]
        result = ep.transfer(self.app, payload, destination=0x400000, initial_equal=True)
        self.assertEqual(result['return_code'], 0)
        self.assertEqual(result['file_bytes_read'], len(payload))
        self.assertEqual(len([e for e in result['events'] if e['operation']=='compare']), 37)
        self.assertFalse(any(e['operation']=='erase' for e in result['events']))
        # Payload matches the stock bytes but a destination padding byte differs.
        initial = b'A' + b'\xff' * 65535
        result = ep.transfer(self.app, b'A', initial_content=initial)
        self.assertFalse(any(e['operation']=='erase' for e in result['events']))
        result = ep.transfer(self.app, b'A', initial_content=initial[:-1]+b'B')
        self.assertEqual([e['length'] for e in result['events'] if e['operation']=='erase'], [65536])
        self.assertTrue(result['flash_payload_equal'])
        self.assertEqual(result['initial_state'], 'supplied erase units')

    def test_magic_and_trailer_checker(self):
        self.assertTrue(ep.validate_envelope(self.app,b'3wfU',b'\x37\x65')['accepted'])
        self.assertTrue(ep.validate_envelope(self.app,b'3wfU')['accepted'])
        for header,trailer in ((b'BAD!',b'\x37\x65'),(b'3wfU',b'xx')):
            self.assertFalse(ep.validate_envelope(self.app,header,trailer)['accepted'])

    def test_bank_selection_is_exact_marker_match(self):
        loader=self.main[0x4000:0x4650]
        marker=loader[0x564:0x574]
        self.assertEqual(ep.select_bank(loader,marker)['source'],'0x18400004')
        for value in (bytes(16),b'\xff'*16,bytes([marker[0]^1])+marker[1:]):
            self.assertEqual(ep.select_bank(loader,value)['source'],'0x18010004')

    def test_transfer_and_failure_paths(self):
        payload=b'ABCD'*20000
        good=ep.transfer(self.app,payload)
        self.assertEqual(good['return_code'],0)
        self.assertTrue(good['flash_payload_equal'])
        self.assertEqual(good['changed_flag'],1)
        same=ep.transfer(self.app,payload,initial_equal=True)
        self.assertEqual(same['changed_flag'],0)
        self.assertFalse(any(e['operation']=='erase' for e in same['events']))
        for kwargs in ({'short_read':True},{'read_error':True},{'cancel':True}):
            report=ep.transfer(self.app,payload,**kwargs)
            self.assertNotEqual(report['return_code'],0)
            self.assertFalse(any(e['operation'] in ('erase','program') for e in report['events']))
        for stage in ('before_erase','after_erase','after_program'):
            report=ep.transfer(self.app,payload,interrupt=stage)
            self.assertEqual(report['interrupted'],stage)
            self.assertIsNone(report['return_code'])
        report=ep.transfer(self.app,payload,program_error=True)
        self.assertFalse(report['flash_payload_equal'])
        # This caller does not test the modeled programmer's return value.
        self.assertEqual(report['return_code'],0)
        with self.assertRaises(ValueError): ep.transfer(self.app,payload,destination=0xdead)
