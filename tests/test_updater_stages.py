import hashlib
import importlib.util
import os
from pathlib import Path
import struct
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import updater_stages as stage
from emulate_platform import inputs
from firmware import checked_image, parse

IMAGE=os.environ.get('IC7300_TEST_IMAGE')


def header_spec(container, installed):
    if len(container)<18 or container[:4]!=b'3wfU' or container[-2:]!=b'\x37\x65':
        return False,None
    if any(value not in b'.0123456789' for value in container[4:16]):
        return False,None
    return True,[int(container[4+i*4:8+i*4]!=installed[i]) for i in range(3)]


def payload_spec(container, flags):
    if len(container)<44: return False
    words=struct.unpack_from('<7I',container,16)
    position=44
    for size,selected in zip((words[0],words[1],words[3],words[5]),(1,*flags)):
        end=position+size
        if selected and (end+16>len(container) or hashlib.md5(container[position:end]).digest()!=container[end:end+16]):
            return False
        position=end+16
    return True


@unittest.skipUnless(IMAGE and importlib.util.find_spec('unicorn'),'Opt-in pinned source and Unicorn required')
class UpdaterStageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data,cls.main,cls.app,_=inputs(Path(IMAGE))
        cls.installed=[cls.data[4+i*4:8+i*4] for i in range(3)]

    def test_precheck_matches_independent_spec(self):
        cases=[self.data,b'BAD!'+self.data[4:],self.data[:-2]+b'xx',self.data[:3],self.data[:-1]]
        for identifier in (b'ABCD',b'9.99',b'....',b'0000',b'\0'*4):
            cases.append(self.data[:4]+identifier+self.data[8:])
        for data in cases:
            result=stage.header_precheck(self.app,data,installed_ids=self.installed)
            self.assertEqual((result['accepted'],result['component_change_flags']),header_spec(data,self.installed))
            self.assertEqual(result['events'][-1]['operation'],'close')

    def test_short_reads_and_seek_error_close_file(self):
        for read in range(1,6):
            result=stage.header_precheck(self.app,self.data,read_failure=read)
            self.assertFalse(result['accepted'])
            self.assertEqual(result['events'][-1]['operation'],'close')
        self.assertFalse(stage.header_precheck(self.app,self.data,seek_failure=True)['accepted'])

    def test_payload_hash_checks_and_selection(self):
        cases=[self.data,self.data[:-8]]
        for part in parse(self.data):
            data=bytearray(self.data);data[part['offset']]^=1;cases.append(bytes(data))
        for flags in ((1,1,1),(0,0,0),(1,0,1)):
            for data in cases:
                result=stage.payload_precheck(self.app,data,flags=flags)
                self.assertEqual(result['accepted'],payload_spec(data,flags))
                self.assertEqual(result['events'][-1]['operation'],'close')
        # This phase deliberately does not check the fixed trailer.
        data=self.data[:-2]+b'xx'
        self.assertTrue(stage.payload_precheck(self.app,data)['accepted'])
        self.assertFalse(stage.header_precheck(self.app,data)['accepted'])

    def test_official_corpus_against_142_routines(self):
        for version in ('140','141','142'):
            path=Path(IMAGE).with_name(f'7300_{version}.dat')
            if not path.exists(): self.skipTest(f'Missing optional corpus image {version}')
            data=checked_image(path,'analyze')
            self.assertTrue(stage.header_precheck(self.app,data,installed_ids=self.installed)['accepted'])
            self.assertTrue(stage.payload_precheck(self.app,data)['accepted'])

    def test_activation_and_every_modeled_prefix_interruption(self):
        for selector in (0,1):
            before=stage.activation_record(self.app,self.main,current_selector=selector,before_erase=True)
            self.assertEqual(before['selected_source'],'0x18400004' if selector==0 else '0x18010004')
            for count in range(17):
                result=stage.activation_record(self.app,self.main,current_selector=selector,program_bytes=count)
                self.assertEqual(result['selected_source'],'0x18400004' if selector==1 and count==16 else '0x18010004')
                self.assertEqual(result['interrupted'],count<16)
                self.assertEqual([event['operation'] for event in result['events']][1:3],
                                 ['modeled_block_erase','modeled_record_program'])

    def test_main_update_order_and_failures(self):
        for selector in (0,1):
            for boot_changed in (False,True):
                for corrupt in (False,True):
                    result=stage.main_update(self.app,self.data,selector=selector,
                        boot_changed=boot_changed,corrupt_transfer=corrupt)
                    self.assertEqual(result['accepted'],not corrupt)
                    events=result['events'];names=[event['operation'] for event in events]
                    transfers=[event for event in events if event['operation']=='modeled_main_transfer']
                    self.assertEqual([event['destination'] for event in transfers],
                                     ['0x0','0x10000' if selector==0 else '0x400000'])
                    self.assertEqual(names[-1],'close')
                    if boot_changed:
                        self.assertLess(names.index('activation_call'),names.index('modeled_md5_finalize'))
                    elif corrupt:
                        self.assertNotIn('activation_call',names)
                    else:
                        self.assertGreater(names.index('activation_call'),names.index('modeled_md5_finalize'))
        for index in (1,2):
            result=stage.main_update(self.app,self.data,transfer_failure=index)
            self.assertFalse(result['accepted'])
            self.assertNotIn('activation_call',[e['operation'] for e in result['events']])
        oversized=bytearray(self.data);struct.pack_into('<I',oversized,16,0x380001)
        result=stage.main_update(self.app,bytes(oversized))
        self.assertFalse(result['accepted'])
        self.assertNotIn('modeled_main_transfer',[e['operation'] for e in result['events']])

    def test_invalid_configuration_rejected(self):
        with self.assertRaises(ValueError): stage.payload_precheck(self.app,self.data,flags=(2,0,0))
        with self.assertRaises(ValueError): stage.activation_record(self.app,self.main,current_selector=2)
        with self.assertRaises(ValueError): stage.activation_record(self.app,self.main,current_selector=0,program_bytes=17)
