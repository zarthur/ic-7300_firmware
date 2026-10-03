"""Exact-image regression checks for the bounded CI-V transport map."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import civ_transport_map as transport


IMAGE = ROOT / "artifacts/original/7300_142.dat"


class CivTransportMapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.container, cls.app = transport.load_app(IMAGE)
        cls.report = transport.evidence(cls.app, cls.container)

    def test_usb_and_separate_civ_settings_are_pinned(self):
        settings = self.report["settings"]["descriptor_fields"]
        self.assertEqual(settings["CI-V Baud Rate"]["field_address"], "0x203de524")
        self.assertEqual(settings["CI-V USB Port"]["field_address"], "0x203de52a")
        self.assertEqual(settings["CI-V USB Baud Rate"]["field_address"], "0x203de52b")
        self.assertEqual(settings["CI-V USB Echo Back"]["field_address"], "0x203de52c")
        self.assertEqual(settings["USB Serial Function"]["field_address"], "0x203de52d")
        usb = self.report["usb_transport"]
        self.assertEqual(usb["selector_setup"]["controller_register_base"], "0xe8007800")
        self.assertEqual(self.report["receive"]["register_base"], "0xe8007000")

    def test_usb_receive_callback_stages_complete_frames_for_dispatch(self):
        usb = self.report["usb_transport"]
        self.assertEqual(
            [(row["event_id"], row["callback_pointer"]) for row in usb["event_callback_registrations"]],
            [("0xe3", "0x20011964"), ("0xe1", "0x20011964"),
             ("0xe2", "0x20011964"), ("0xe4", "0x20011b98")],
        )
        self.assertEqual(usb["receive"]["rx_data_register"], "0xe8007814")
        self.assertEqual(usb["receive"]["frame_parser"], "0x20011618")
        self.assertEqual(usb["receive"]["completed_frame_state"], "0x20396bc8")
        self.assertEqual(usb["foreground_handoff"]["dispatcher_input"], "0x20396cbc")

    def test_response_ready_copy_reaches_usb_transmit_register(self):
        usb = self.report["usb_transport"]
        self.assertEqual(self.report["response"]["ready_flag_address"], "0x20390034")
        self.assertEqual(usb["foreground_handoff"]["response_payload_destination"], "0x20396c2e")
        self.assertEqual(usb["foreground_handoff"]["response_pending_byte"], "0x20396c92")
        self.assertEqual(usb["transmit"]["staging_buffer"], "0x20396eaf")
        self.assertEqual(usb["transmit"]["event_id"], "0xe4")
        self.assertEqual(usb["transmit"]["tx_data_register"], "0xe800780c")
        self.assertIn("must be zero", usb["transmit"]["service_gate"])

    def test_foreground_context_is_distinguished_from_byte_callbacks(self):
        context = self.report["dispatch"]["foreground_context"]
        self.assertEqual(context["control_loop_entry"], "0x20029914")
        self.assertEqual(context["interrupt_enable"], "0x20029b00")
        self.assertEqual(context["wait_instruction"], "0x20029b14")
        self.assertIn("value 3", context["post_wait_service_branch"])
        self.assertEqual(context["dispatcher_copy_call"], "0x20029b60")
        self.assertFalse(context["local_interrupt_mask_between_wait_and_dispatch"])
        self.assertEqual(context["task_identity"], "unresolved")
        self.assertEqual(context["event_callback_execution_context"], "unresolved")

    def test_1a05_setting_and_response_callbacks_are_separate(self):
        dispatch = self.report["dispatch"]
        row = dispatch["command_1a_subcommand_05"]
        self.assertEqual(
            row["callback_roles"],
            {
                "plus4_input_or_setting_callback": "0x2000dcb4",
                "plus8_response_serializer": "0x2000ffb0",
                "plus12_response_preflight": "0x2000f1c0",
            },
        )
        separation = dispatch["command_1a05_callback_separation"]
        self.assertIn("direct STRB", separation["setting_or_input_route"])
        self.assertIn("does not call row +4", separation["response_route"])
        self.assertIn("not a proof", separation["read_only_scope"])

    def test_reply_capacity_is_conservative_and_requires_an_explicit_cap(self):
        capacity = self.report["response"]["capacity"]
        self.assertEqual(capacity["generic_output_to_adjacent_receive_buffer_distance_bytes"], 100)
        self.assertEqual(capacity["usb_queue_copy_bytes"], 100)
        self.assertEqual(capacity["usb_tx_staging_to_rx_assembly_distance_bytes"], 100)
        self.assertEqual(capacity["conservative_complete_response_body_cap_including_fd"], 98)
        self.assertFalse(capacity["cap_is_enforced_by_existing_firmware"])
        self.assertEqual(
            capacity["callback_encoded_payload_budget_1a05_style"]["max_encoded_bytes_after_those_prefixes"],
            91,
        )
        self.assertEqual(capacity["status_payload_worst_case_encoded_bytes"], 32)
        self.assertTrue(capacity["status_reply_16_byte_payload_fits"])
        self.assertEqual(capacity["bounded_read_encoded_record_budget"], 84)
        self.assertEqual(capacity["bounded_read_worst_case_raw_record_budget"], 42)
        self.assertEqual(
            capacity["bounded_read_max_records_formula"],
            "floor(42 / fixed_record_size_bytes); count is also clamped to available records",
        )
        self.assertIn("no independent length counter", capacity["tx_copy_loop_termination"])
        self.assertIn("backpressure guarantee", capacity["pending_slot_observation"])
        self.assertIn("clears the marker", capacity["pending_marker_clear"])

    def test_callback_branch_change_invalidates_the_map(self):
        changed = bytearray(self.app)
        offset = 0x20011964 - transport.APP_BASE
        changed[offset:offset + 4] = b"\0\0\0\0"
        with self.assertRaisesRegex(ValueError, "Expected B"):
            transport.evidence(bytes(changed), self.container)


if __name__ == "__main__":
    unittest.main()
