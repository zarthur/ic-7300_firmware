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
        with self.assertRaisesRegex(ValueError, 'exact pinned'):
            lifecycle.configuration_probe(b'unknown', [0])
        for modes in ([], [True], [-1], [1 << 32], ['0']):
            with self.assertRaises(ValueError): lifecycle.configuration_probe(b'unknown', modes)

    def test_start_requires_pinned_image_and_bounded_stimuli(self):
        with self.assertRaisesRegex(ValueError, 'exact pinned'):
            lifecycle.start_probe(b'unknown', [(-1, 0, 0, 0, 0)])
        for cases in ([], [()], [(-2, 0, 0, 0, 0)], [(21, 0, 0, 0, 0)],
                      [(-1, 5, 0, 0, 0)], [(-1, 0, 256, 0, 0)],
                      [(-1, 0, 0, 65536, 0)], [(-1, 0, 0, 0, 2)],
                      [(-1, 0, False, 0, 0)]):
            with self.assertRaises(ValueError):
                lifecycle.start_probe(b'unknown', cases)

    def test_stop_requires_pinned_image_and_bounded_stimuli(self):
        with self.assertRaisesRegex(ValueError, 'exact pinned'):
            lifecycle.stop_probe(b'unknown', [(-1, 0, 0, 0, 0)])
        for cases in ([], [()], [(2, 0, 0, 0, 0)], [(-1, -1, 0, 0, 0)],
                      [(-1, 0, -1, 0, 0)], [(-1, 0, 0, -1, 0)],
                      [(-1, 0, 0, 0, True)]):
            with self.assertRaises(ValueError): lifecycle.stop_probe(b'unknown', cases)

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

    def test_fifo_configuration_does_not_write_tdm_mode(self):
        for row in lifecycle.configuration_probe(self.app, [0, 1, 0x100, 0x101, 0xffffffff]):
            stages = row['stages']
            self.assertEqual([s['name'] for s in stages],
                             ['setup', 'clear_status', 'start_prefix', 'stop_prefix'])
            for stage in stages:
                self.assertEqual(stage['ssitdmr'], row['input_mode'])
                self.assertEqual(stage['other_ssitdmr'], row['input_mode'])
            # Actual stores separate FIFO reset (bits 1:0) from enabling
            # reception, and status +0x14 from TDM mode +0x20.
            self.assertEqual([s['ssifcr'] for s in stages], [0xc3, 0xc3, 0xcc, 0xc0])
            self.assertEqual([s['ssicr'] & 3 for s in stages], [0, 0, 3, 0])
            self.assertEqual(stages[1]['writes'], [
                {'address': a, 'value': 0} for a in
                (0xe820b004, 0xe820b804, 0xe820b014, 0xe820b814)])

    def test_complete_start_timeout_preserves_old_gate_but_still_enables_dma(self):
        cases = [(phase, retries, gate, count, mask)
                 for phase in range(-1, 21) for retries in (0, 2)
                 for gate in (0, 1) for count in (0, 65535) for mask in (0, 1)]
        for row in lifecycle.start_probe(self.app, cases):
            with self.subTest(case=(row['timeout_phase'], row['previous_gate'],
                                   row['retries_per_phase'], row['initial_irq_mask'])):
                self.assertEqual(row['gate'], 1 if row['timeout_phase'] == -1 else row['previous_gate'])
                dma_writes = [w for w in row['writes'] if w['address'] in
                              (0xe82000e8, 0xe8200128, 0xe8200168)]
                self.assertEqual([w['address'] for w in dma_writes],
                                 [0xe8200128, 0xe82000e8, 0xe8200168])
                self.assertTrue(all(w['value'] == 1 for w in dma_writes))
                self.assertEqual(sum(w['address'] == 0x2039038c for w in row['writes']),
                                 int(row['timeout_phase'] == -1))
                self.assertEqual(row['writes'][-1],
                                 {'address': 0x203903ac, 'size': 1, 'value': 0})
                self.assertEqual(row['return_irq_mask'], 0)
                self.assertEqual(len(row['polls']), 20)

    def test_complete_stop_clears_gate_without_dma_disable_command(self):
        cases = [(phase, retries, gate, count, mask)
                 for phase in (-1, 0, 1) for retries in (0, 2) for gate in (0, 1, 255)
                 for count in (0, 65535) for mask in (0, 1)]
        for row in lifecycle.stop_probe(self.app, cases):
            self.assertEqual(row['gate'], 0)
            self.assertEqual(row['return_irq_mask'], row['initial_irq_mask'])
            writes = row['writes']
            controls = [w for w in writes if w['address'] in (0xe82000e8, 0xe8200128, 0xe8200168)]
            self.assertEqual(controls, [{'address': a, 'size': 4, 'value': 0}
                                       for a in (0xe82000e8, 0xe8200128, 0xe8200168)])
            self.assertEqual(writes[-2:], [{'address': a, 'size': 1, 'value': 0}
                                          for a in (0x2039038c, 0x203903ac)])

if __name__=='__main__':unittest.main()
