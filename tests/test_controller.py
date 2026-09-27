import importlib.util
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from controller import BASE, ControllerModel, run_controller, selector_references
from emulate_platform import inputs, transfer
from updater_stages import activation_record


class ControllerModelTests(unittest.TestCase):
    def test_unknown_registers_and_widths_fail_closed(self):
        model = ControllerModel('immediate')
        for address, size in ((BASE + 4, 4), (BASE + 0x48, 1), (BASE - 4, 4)):
            with self.assertRaises(ValueError): model.read(address, size)
        for address, size in ((BASE + 4, 4), (BASE + 0x48, 4), (BASE, 2)):
            with self.assertRaises(ValueError): model.write(address, size, 0)

    def test_scripted_completion_resets_for_each_transfer(self):
        model = ControllerModel('delayed')
        for _ in range(2):
            model.write(BASE + 0x24, 4, 0x60000)
            model.write(BASE + 0x20, 4, 1)
            self.assertEqual([model.read(BASE + 0x48, 4) for _ in range(3)], [0, 0, 1])
        stuck = ControllerModel('transfer_stuck')
        self.assertEqual([stuck.read(BASE + 0x48, 4) for _ in range(10)], [0] * 10)

    def test_invalid_scenario_rejected(self):
        with self.assertRaises(ValueError): ControllerModel('pretend-success')


IMAGE = os.environ.get('IC7300_TEST_IMAGE')
@unittest.skipUnless(IMAGE and importlib.util.find_spec('unicorn'), 'Opt-in pinned source and Unicorn required')
class ControllerFirmwareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, cls.main, cls.app, _ = inputs(Path(IMAGE))

    def test_original_erase_and_program_sequences(self):
        # Independent invariants: inclusive 64 KiB erase destinations, sequential
        # word transfers, data split at 256-byte boundaries, all-FF words skipped.
        erase = run_controller(self.app, 'erase', destination=0x10000, end=0x20000)
        self.assertEqual(erase['outcome'], 'RETURNED')
        self.assertEqual(erase['erase_offsets'], ['0x10000', '0x20000'])
        for scenario in ('immediate', 'delayed', 'status_extra_bits'):
            programmed = run_controller(self.app, 'program', scenario=scenario, payload=b'ABCD' * 70)
            self.assertEqual(programmed['outcome'], 'RETURNED')
            self.assertEqual(programmed['program_word_count'], 70)
            self.assertIn('read_masked_register', programmed['executed_routines'])
            self.assertIn('wait_not_busy', programmed['executed_routines'])
            self.assertEqual(programmed['modeled_helpers'], [])
        empty = run_controller(self.app, 'program', payload=b'\xff' * 16)
        self.assertEqual(empty['outcome'], 'RETURNED')
        self.assertEqual(empty['program_word_count'], 0)

    def test_selector_reference_evidence_retains_bounded_reader(self):
        result = selector_references(self.main, self.app)
        self.assertTrue(result['application_comparison_marker_matches_loader'])
        literals = result['application_reader_window']['literal_loads']
        self.assertEqual([x['value'] for x in literals], ['0x187f0000', '0x20390398'])
        self.assertTrue(any(x['address'] == '0x20062d34' and x['value'] == '0x187f0000' for x in result['candidates']))

    def test_polling_is_bounded_by_harness_not_firmware(self):
        for routine in ('erase', 'program'):
            for scenario in ('transfer_stuck', 'busy_stuck', 'write_enable_stuck'):
                result = run_controller(self.app, routine, scenario=scenario, budget=3000)
                self.assertEqual(result['outcome'], 'LIMIT')
                self.assertIsNone(result['return_register'])
                self.assertEqual(result['instructions'], 3000)
                self.assertNotEqual(result['pc'], '0x8000000')

    def test_runtime_helpers_are_explicit_unresolved_boundaries(self):
        for routine, helper in (('enter_command', '0x200b9008'), ('restore_mapping', '0x200b9098')):
            raw = run_controller(self.app, routine, model_runtime=False)
            self.assertEqual(raw['outcome'], 'UNRESOLVED')
            self.assertEqual(raw['target'], helper)
            modeled = run_controller(self.app, routine, model_runtime=True)
            self.assertEqual(modeled['outcome'], 'RETURNED')
            self.assertEqual(modeled['modeled_helpers'], [helper])

    def test_unknown_mmio_access_halts_original_execution(self):
        from unittest.mock import patch
        with patch('controller.READ_OFFSETS', set()):
            result = run_controller(self.app, 'erase')
        self.assertEqual(result['outcome'], 'UNKNOWN_MMIO')
        self.assertIsNone(result['return_register'])

    def test_transfer_and_activation_do_not_continue_after_controller_stall(self):
        good = transfer(self.app, b'ABCD' * 4, controller_scenario='immediate')
        self.assertEqual(good['return_code'], 0)
        self.assertTrue(good['flash_payload_equal'])
        self.assertEqual([e['routine'] for e in good['events'] if e['operation'] == 'original_controller'],
                         ['enter_command', 'erase', 'program', 'restore_mapping'])
        for scenario in ('transfer_stuck', 'busy_stuck', 'write_enable_stuck'):
            result = transfer(self.app, b'ABCD' * 4, controller_scenario=scenario)
            self.assertEqual(result['interrupted'], 'controller_LIMIT')
            self.assertIsNone(result['return_code'])
            self.assertIsNone(result['flash_payload_equal'])
            self.assertFalse(any(e.get('routine') == 'restore_mapping' for e in result['events']))
            record = activation_record(self.app, self.main, current_selector=1, controller_scenario=scenario)
            self.assertEqual(record['controller_stop'], 'LIMIT')
            self.assertIsNone(record['selected_source'])
            self.assertIsNone(record['final_marker_sha256'])
        record = activation_record(self.app, self.main, current_selector=1, controller_scenario='immediate')
        self.assertFalse(record['interrupted'])
        self.assertEqual(record['selected_source'], '0x18400004')

    def test_mapping_helpers_execute_descriptors_before_coprocessor_boundary(self):
        from runtime_helpers import run_helper
        # Independent static specification: 64 consecutive 1 MiB sections,
        # entry attributes assembled from the helper's packed argument bytes.
        for name, attributes in (('enter_mapping_helper', 0x85016),
                                 ('restore_mapping_helper', 0x8dc06)):
            result = run_helper(self.app, name)
            self.assertEqual(result['outcome'], 'UNRESOLVED_COPROCESSOR')
            self.assertEqual(result['pc'], '0x200052e0')
            self.assertEqual(result['table_words'],
                             [0x18000000 + (i << 20) | attributes for i in range(64)])
            self.assertEqual(result['modeled_helpers'], [])
            self.assertFalse(any(e['operation'].startswith('modeled_') for e in result['events']))

    def test_mapping_cache_stimuli_are_explicit_and_external_wait_is_bounded(self):
        from runtime_helpers import run_helper
        boundary = run_helper(self.app, 'enter_mapping_helper', cache_geometry='one_set_one_way')
        self.assertEqual((boundary['outcome'], boundary['pc'], boundary['address']),
                         ('UNRESOLVED_MMIO', '0x200b92d4', '0x3ffff104'))
        for wide, mask in ((False, 0xff), (True, 0xffff)):
            for scenario, reads in (('immediate', 1), ('delayed', 3)):
                result = run_helper(self.app, 'enter_mapping_helper', cache_geometry='one_set_one_way',
                                    peripheral=scenario, ways16=wide)
                self.assertEqual(result['outcome'], 'RETURNED')
                self.assertEqual(result['polling_reads'], reads)
                writes = [(e['address'], e['value']) for e in result['events'] if e['operation'] == 'mmio_write']
                self.assertEqual(writes, [('0x3ffff7fc', mask), ('0x3ffff730', 0)])
                cp = [e['pc'] for e in result['events'] if e['operation'] == 'modeled_maintenance']
                self.assertIn('0x20005354', cp)  # r0=1 clean-by-set/way branch
                self.assertIn('0x20005344', cp)  # r0=0 invalidate-by-set/way branch
            stuck = run_helper(self.app, 'enter_mapping_helper', cache_geometry='one_set_one_way',
                               peripheral='stuck', ways16=wide, budget=1000)
            self.assertEqual(stuck['outcome'], 'LIMIT')
            self.assertEqual(stuck['instructions'], 1000)
            self.assertFalse(any(e.get('address') == '0x3ffff730' for e in stuck['events']))

    def test_restore_mapping_has_no_external_controller_wait(self):
        from runtime_helpers import run_helper
        for geometry in ('no_data_cache', 'one_set_one_way'):
            result = run_helper(self.app, 'restore_mapping_helper', cache_geometry=geometry)
            self.assertEqual(result['outcome'], 'RETURNED')
            self.assertEqual(result['polling_reads'], 0)
            self.assertFalse(any('mmio' in e['operation'] for e in result['events']))
            self.assertTrue(any(e['operation'] == 'modeled_maintenance' for e in result['events']))

    def test_mapping_helpers_stop_on_unreviewed_memory_write(self):
        from runtime_helpers import run_helper
        # Remove the known table-write allowance by moving the firmware literal;
        # ordinary RAM mapping must not silently authorize a new write target.
        import struct
        altered = bytearray(self.app)
        struct.pack_into('<I', altered, 0x200b925c - 0x20005000, 0x203907a4)
        result = run_helper(bytes(altered), 'enter_mapping_helper')
        self.assertEqual(result['outcome'], 'UNRESOLVED_MEMORY_WRITE')
        self.assertEqual(result['address'], '0x203907a4')
