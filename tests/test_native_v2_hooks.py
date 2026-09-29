"""Keep native decisions/queues unchanged through the actual v2 hook sites."""
import importlib.util
import os
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from emulate_platform import inputs, STACK
from native_capture_v2 import decode_storage
from native_receive import DMA
import native_v2_hooks as hooks


class SyntheticV2HookTests(unittest.TestCase):
    def test_bundle_contains_identical_standalone_components(self):
        code, entries = hooks.build_bundle()
        self.assertEqual(set(entries), set(hooks.SITES))
        self.assertLess(len(code), 8192)

    def test_unknown_image_is_rejected_before_substitution(self):
        with self.assertRaisesRegex(ValueError, 'exact pinned'):
            hooks.offline_edits(b'unknown')


IMAGE = os.environ.get('IC7300_TEST_IMAGE')
@unittest.skipUnless(IMAGE and importlib.util.find_spec('unicorn'), 'Pinned image and Unicorn required')
class FirmwareV2HookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, _, cls.app, _ = inputs(Path(IMAGE))
        cls.words = b''.join(struct.pack('<4I', ((i*97)&65535)<<16 | 0xabcd,
                                         ((65535-i*113)&65535)<<16 | 0x1234,
                                         0xdeadbeef, 0xcafefeed) for i in range(36))

    def test_all_original_decisions_and_exit_state_are_preserved(self):
        baseline, trial = hooks.HookTrial(self.app, False), hooks.HookTrial(self.app)
        for status in range(256):
            for masks in (0, 0x40, 0x80, 0xc0):
                for armed in (0, 1):
                    baseline.configure(status=armed); trial.configure(status=armed)
                    before = baseline.decision(status, masks)
                    after = trial.decision(status, masks)
                    self.assertEqual(after, before, (status, masks, armed))
                    ready = after['boundary'] == 0x2006064c
                    self.assertEqual(trial.live()[:2], (int(ready), int(ready and armed)))
                    self.assertEqual(struct.unpack_from('<2I', trial.storage()), (4 if ready and armed else armed, 0))
                    self.assertEqual(trial.ssif_reads, [])

    def test_native_queues_and_raw_observations_for_every_clock_gate_value(self):
        baseline, trial = hooks.HookTrial(self.app, False), hooks.HookTrial(self.app)
        ssif = (0x3c2b0033, 0xcc, 0x08000002, 0x10301, 0x101)
        snapshots = (0xffffffff, 1, 0, 0, 32000, 0x40)
        for gate in range(256):
            for masks in (0, 0x40, 0x80, 0xc0):
                bank = gate & 1
                status = 0x41 | (0 if bank else 0x80)
                baseline.configure(gate=gate, ssif=ssif); trial.configure(gate=gate, ssif=ssif)
                baseline.decision(status, masks); trial.decision(status, masks)
                original, actual = baseline.ready(self.words, snapshots), trial.ready(self.words, snapshots)
                for key in ('queue_a', 'queue_b', 'split', 'registers', 'sp', 'lr', 'cpsr'):
                    self.assertEqual(actual[key], original[key], (gate, masks, key))
                self.assertEqual(actual['sp'], STACK+0xf000)
                # Native queue B leaves its last call address in LR; compare
                # with original behavior above, rather than requiring caller LR.
                self.assertEqual(actual['stack_below_caller'], 144)
                row = decode_storage(trial.storage())['records'][0]
                observed = not gate & 0x20
                self.assertEqual(row['flags'], 0 if observed else 16)
                self.assertEqual(row['observations'], list(snapshots)+[DMA+576*(bank+1)]+(list(ssif) if observed else [0xffffffff]*5))
                self.assertEqual(row['stream_a']+row['stream_b'], list(struct.unpack('<72h', actual['split'])))
                self.assertEqual(actual['ssif_reads'], [hooks.GATE]+(list(hooks.SSI_REGISTERS) if observed else []))
                self.assertEqual(actual['timer_reads'], list(zip((hooks.TICK, hooks.COUNTER, hooks.PENDING)*2, snapshots)))

    def test_epoch_change_after_bank_selection_remains_visible(self):
        trial = hooks.HookTrial(self.app); trial.configure()
        trial.decision(0xc1)
        trial.ready(self.words, epoch_after_selection=(8, 3, 0))
        row = decode_storage(trial.storage())['records'][0]
        self.assertEqual((row['flags'], row['epoch_before'], row['epoch_after']), (1, [7, 4, 0], [8, 3, 0]))

    def test_inactive_or_frozen_capture_skips_all_extra_register_observations(self):
        baseline, trial = hooks.HookTrial(self.app, False), hooks.HookTrial(self.app)
        for status, count in ((0, 0), (2, 512), (5, 1), (6, 0)):
            baseline.configure(status=status, count=count); trial.configure(status=status, count=count)
            before = trial.storage()
            baseline.decision(0xc1); trial.decision(0xc1)
            original, actual = baseline.ready(self.words), trial.ready(self.words)
            for key in ('queue_a', 'queue_b', 'split', 'registers', 'sp', 'lr', 'cpsr'):
                self.assertEqual(actual[key], original[key])
            self.assertEqual(actual['ssif_reads'], [])
            self.assertEqual(actual['timer_reads'], [])
            self.assertEqual(trial.storage(), before)
            self.assertEqual(trial.live()[:2], (0, 0))

    def test_unavailable_flag_preserves_nested_fault_and_observed_all_ones(self):
        trial = hooks.HookTrial(self.app); trial.configure(gate=0x20)
        trial.decision(0xc1)
        trial.uc.mem_write(hooks.LIVE+8, struct.pack('<I', 8))
        trial.ready(self.words)
        decoded = decode_storage(trial.storage())
        self.assertEqual((decoded['status'], decoded['records'][0]['flags']), (5, 24))
        trial = hooks.HookTrial(self.app); trial.configure(ssif=(0xffffffff,)*5)
        trial.decision(0xc1); trial.ready(self.words)
        row = decode_storage(trial.storage())['records'][0]
        self.assertEqual(row['flags'], 0)
        self.assertEqual(row['observations'][7:], [0xffffffff]*5)


if __name__ == '__main__': unittest.main()
