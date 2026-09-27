import importlib.util
from pathlib import Path
import struct
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from control_flow import walk


@unittest.skipUnless(importlib.util.find_spec('capstone'),'Optional Capstone required')
class FlowTests(unittest.TestCase):
    def test_unconditional_branch_skips_data_and_return_stops(self):
        data=struct.pack('<4I',0xea000000,0x12345678,0xe12fff1e,0xeafffffe)
        report=walk(data,0x1000,0x1000,0x1010)
        self.assertEqual(report['reachable_instructions'],2)
        self.assertEqual(report['edges'][-1]['kind'],'return')

    def test_conditional_branch_visits_both_paths(self):
        data=struct.pack('<3I',0x1a000000,0xe12fff1e,0xe12fff1e)
        self.assertEqual(walk(data,0x1000,0x1000,0x100c)['reachable_instructions'],3)

    def test_unresolved_indirect_and_out_of_bounds(self):
        data=struct.pack('<I',0xe12fff10)
        self.assertEqual(walk(data,0x1000,0x1000,0x1004)['edges'][0]['kind'],'unresolved indirect')
        data=struct.pack('<I',0xea000020)
        self.assertTrue(walk(data,0x1000,0x1000,0x1004)['unresolved_exits'])
