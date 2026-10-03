#!/usr/bin/env python3
"""Verify a bounded v1.42 CI-V receive/dispatch/response map offline.

This reads one pinned firmware image. It never opens a serial or USB device,
emulates hardware, writes firmware, or modifies the input image.
"""
import argparse
import hashlib
import json
import struct
from pathlib import Path

from firmware import checked_image, digest, lzss, parse, require_target

APP_BASE = 0x20005000
PINNED_VERSION = "142"
COMMAND_TABLE = 0x2018AA2C
HANDLER_TABLE = 0x2018AB84
EXPECTED_APP_SHA256 = "4686728c9d1f7249b6278a29686a40b8fa5e527bd2428a76a33cd9395178c9a4"


def load_app(image_path):
    container = checked_image(image_path, "trace")
    target = require_target(container, "trace")
    if target["version"] != PINNED_VERSION:
        raise ValueError("This map is pinned to official IC-7300 version 1.42")
    main = parse(container)[0]
    payload = container[main["offset"]:main["offset"] + main["size"]]
    output_size = struct.unpack_from("<I", payload, 0x10000)[0]
    app, _ = lzss(payload[0x10004:], output_size)
    app_sha256 = digest(app)
    if app_sha256 != EXPECTED_APP_SHA256:
        raise ValueError("Decoded application does not match the pinned v1.42 image")
    return container, app


def instruction(app, address):
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM

    offset = address - APP_BASE
    if offset < 0 or offset + 4 > len(app):
        raise ValueError(f"Instruction address outside application: {address:#x}")
    engine = Cs(CS_ARCH_ARM, CS_MODE_ARM)
    engine.detail = True
    ins = next(engine.disasm(app[offset:offset + 4], address, count=1), None)
    if ins is None or not ins.id:
        raise ValueError(f"Could not decode ARM instruction at {address:#x}")
    return ins


def immediate(ins, operand_index=0):
    from capstone.arm import ARM_OP_IMM

    operand = ins.operands[operand_index]
    if operand.type != ARM_OP_IMM:
        raise ValueError(f"Expected immediate operand at {ins.address:#x}")
    return operand.imm


def literal_value(app, address):
    from capstone.arm import ARM_OP_MEM, ARM_REG_PC

    ins = instruction(app, address)
    if ins.mnemonic != "ldr" or len(ins.operands) != 2:
        raise ValueError(f"Expected PC-relative LDR at {address:#x}")
    operand = ins.operands[1]
    if operand.type != ARM_OP_MEM or operand.mem.base != ARM_REG_PC:
        raise ValueError(f"Expected PC-relative literal at {address:#x}")
    pool_address = address + 8 + operand.mem.disp
    offset = pool_address - APP_BASE
    if offset < 0 or offset + 4 > len(app):
        raise ValueError(f"Literal pool outside application at {address:#x}")
    return struct.unpack_from("<I", app, offset)[0]


def expect_call(app, site, target):
    ins = instruction(app, site)
    if ins.mnemonic != "bl" or immediate(ins) != target:
        raise ValueError(f"Expected BL {site:#x} -> {target:#x}")


def word(app, address):
    offset = address - APP_BASE
    if offset < 0 or offset + 4 > len(app):
        raise ValueError(f"Word address outside application: {address:#x}")
    return struct.unpack_from("<I", app, offset)[0]


def c_string_bytes(app, address, limit=128):
    offset = address - APP_BASE
    if offset < 0 or offset >= len(app):
        raise ValueError(f"String address outside application: {address:#x}")
    end = app.find(b"\0", offset, min(len(app), offset + limit))
    if end < 0:
        raise ValueError(f"Unterminated string at {address:#x}")
    return app[offset:end]


def c_string(app, address):
    try:
        return c_string_bytes(app, address).decode("ascii")
    except UnicodeDecodeError as exc:
        raise ValueError(f"Expected ASCII setting label at {address:#x}") from exc


def expect_instruction(app, address, mnemonic, op_str):
    ins = instruction(app, address)
    if ins.mnemonic != mnemonic or ins.op_str != op_str:
        raise ValueError(
            f"Unexpected instruction at {address:#x}: {ins.mnemonic} {ins.op_str}"
        )
    return ins


def expect_branch(app, site, target, mnemonic="b"):
    ins = instruction(app, site)
    if ins.mnemonic != mnemonic or immediate(ins) != target:
        raise ValueError(f"Expected {mnemonic.upper()} {site:#x} -> {target:#x}")


def command_1a05(app):
    command_row = COMMAND_TABLE + 0x1A * 8
    base_slot = app[command_row - APP_BASE]
    allowed_pointer = word(app, command_row + 4)
    allowed = []
    for index in range(64):
        value = app[allowed_pointer - APP_BASE + index]
        if value == 0xFD:
            break
        allowed.append(value)
    else:
        raise ValueError("CI-V 1Ah subcommand list exceeded 64-byte bound")
    if 0x05 not in allowed:
        raise ValueError("Pinned command table no longer lists CI-V 1Ah/05h")
    slot = base_slot + allowed.index(0x05)
    handler_address = HANDLER_TABLE + slot * 16
    raw = app[handler_address - APP_BASE:handler_address - APP_BASE + 16]
    if len(raw) != 16:
        raise ValueError("Truncated CI-V handler table row")
    fields = struct.unpack("<IIII", raw)
    return {
        "command": "0x1a",
        "base_slot": base_slot,
        "allowed_subcommands": [f"0x{x:02x}" for x in allowed],
        "subcommand": "0x05",
        "handler_slot": slot,
        "handler_row": hex(handler_address),
        "row_words": [hex(x) for x in fields],
        "callback_words_at_plus4_plus8_plus12": [hex(x) for x in fields[1:]],
        "callback_roles": {
            "plus4_input_or_setting_callback": hex(fields[1]),
            "plus8_response_serializer": hex(fields[2]),
            "plus12_response_preflight": hex(fields[3]),
        },
    }


def foreground_context(app):
    expect_instruction(app, 0x20029B00, "cpsie", "i")
    expect_instruction(app, 0x20029B14, "wfi", "")
    expect_branch(app, 0x20029B5C, 0x20029BB0)
    expect_instruction(app, 0x20029BB0, "ldrb", "r0, [r8]")
    expect_instruction(app, 0x20029BB4, "cmp", "r0, #3")
    expect_branch(app, 0x20029BB8, 0x20029B60, "beq")
    expect_call(app, 0x20029B60, 0x2000B258)
    expect_call(app, 0x20029B68, 0x20012854)
    masked = [
        hex(address) for address in range(0x20029B14, 0x20029B60, 4)
        if instruction(app, address).mnemonic == "cpsid"
    ]
    masked.extend(
        hex(address) for address in range(0x20029BB0, 0x20029BBC, 4)
        if instruction(app, address).mnemonic == "cpsid"
    )
    if masked:
        raise ValueError(f"Interrupt mask found between WFI and dispatcher service: {masked}")
    return {
        "control_loop_entry": "0x20029914",
        "interrupt_enable": "0x20029b00",
        "wait_instruction": "0x20029b14",
        "post_wait_service_branch": "0x20029b5c -> 0x20029bb0; state value 3 branches to the copy call at 0x20029b60",
        "dispatcher_copy_call": "0x20029b60",
        "usb_service_call": "0x20029b68",
        "other_copy_service_callers": ["0x20052f5c", "0x200531fc"],
        "local_interrupt_mask_between_wait_and_dispatch": False,
        "task_identity": "unresolved",
        "event_callback_execution_context": "unresolved",
        "scope": "foreground control-loop callsite evidence; not a global scheduling proof",
    }


def response_capacity(app, output_buffer, receive_buffer, usb_frame_state):
    usb_tx_payload = usb_frame_state + 0x66
    usb_tx_pending = usb_frame_state + 0xCA
    usb_tx_staging = literal_value(app, 0x200128CC)
    usb_rx_assembly = literal_value(app, 0x2001163C)
    usb_tx_span = usb_rx_assembly - usb_tx_staging
    response_copy_span = usb_tx_pending - usb_tx_payload
    output_span = receive_buffer - output_buffer
    if (output_span, response_copy_span, usb_tx_span) != (0x64, 0x64, 0x64):
        raise ValueError("One of the statically derived response-buffer spans changed")
    expect_instruction(app, 0x2000B2F8, "mov", "r2, #0x64")
    expect_instruction(app, 0x2000B2FC, "ldr", "r1, [pc, #-0xd8]")
    expect_instruction(app, 0x2000B300, "add", "r0, r6, #0x66")
    expect_instruction(app, 0x2000B30C, "strb", "r0, [r6, #0xca]")
    expect_instruction(app, 0x20012898, "ldrb", "r3, [r4]")
    expect_instruction(app, 0x2001289C, "tst", "r3, #0x40")
    expect_instruction(app, 0x200128A4, "tst", "r3, #0x20")
    expect_instruction(app, 0x200128BC, "ldrb", "r0, [r7, #0xca]")
    expect_instruction(app, 0x200128F8, "ldrb", "r1, [r1]")
    expect_instruction(app, 0x20012908, "strb", "r5, [r7, #0xca]")
    expect_instruction(app, 0x200128E4, "strb", "r2, [r0], #1")
    expect_instruction(app, 0x200128EC, "ldrb", "r2, [r1]")
    expect_instruction(app, 0x200128F0, "cmp", "r2, #0xfd")
    expect_branch(app, 0x200128F4, 0x200128E4, "bne")
    expect_instruction(app, 0x2000AE00, "cmp", "r4, #0")
    expect_instruction(app, 0x2000AE08, "ldrb", "r1, [r5, #2]")
    expect_instruction(app, 0x2000AE0C, "strb", "r1, [r0], #1")
    expect_instruction(app, 0x2000AE20, "pop", "{r4, r5, r6, lr}")
    expect_branch(app, 0x2000AE24, 0x2000AACC)
    for address, operands in (
        (0x2000AA98, "r2, [r0], #1"),
        (0x2000AAA4, "r2, [r0], #1"),
        (0x2000AAA8, "r1, [r0], #1"),
    ):
        expect_instruction(app, address, "strb", operands)
    return {
        "generic_output_buffer": hex(output_buffer),
        "generic_output_to_adjacent_receive_buffer_distance_bytes": output_span,
        "usb_queue_payload": hex(usb_tx_payload),
        "usb_queue_copy_bytes": response_copy_span,
        "usb_queue_pending_marker": hex(usb_tx_pending),
        "shared_builder_ready_flag": "0x20390034",
        "producer_copy_service": "0x2000b258",
        "consumer_service": "0x20012854",
        "pending_slot_observation": "one 100-byte payload slot and one pending marker; this trace does not establish FIFO depth or a producer backpressure guarantee",
        "consumer_gate": "service checks state bits 0x40 and 0x20 clear, state byte zero, and pending marker nonzero before staging",
        "pending_marker_clear": "0x20012908 clears the marker after staging the response",
        "usb_tx_staging_buffer": hex(usb_tx_staging),
        "usb_tx_staging_to_rx_assembly_distance_bytes": usb_tx_span,
        "usb_tx_prefix_bytes": 2,
        "conservative_complete_response_body_cap_including_fd": usb_tx_span - 2,
        "cap_is_enforced_by_existing_firmware": False,
        "tx_copy_loop_termination": "scans until FD; no independent length counter in the traced loop",
        "generic_builder_capacity_guard": "not established; the traced builder appends FD without comparing its returned output cursor to an end pointer",
        "civ_escape_rule": "bytes 0xfa through 0xff can consume two encoded bytes in the existing response path",
        "callback_encoded_payload_budget_1a05_style": {
            "max_generic_header_bytes": 4,
            "response_command_subcommand_prefix_bytes": 2,
            "terminal_fd_bytes": 1,
            "max_encoded_bytes_after_those_prefixes": usb_tx_span - 2 - 4 - 2 - 1,
            "basis": "98-byte complete body cap minus worst-case 4-byte generic header, 2 response key bytes, and FD",
        },
        "status_payload_bytes": 16,
        "status_payload_worst_case_encoded_bytes": 32,
        "status_reply_16_byte_payload_fits": 32 <= usb_tx_span - 2 - 4 - 2 - 1,
        "bounded_read_response_header_bytes": 7,
        "bounded_read_encoded_record_budget": usb_tx_span - 2 - 4 - 2 - 1 - 7,
        "bounded_read_worst_case_raw_record_budget": (usb_tx_span - 2 - 4 - 2 - 1 - 7) // 2,
        "bounded_read_max_records_formula": "floor(42 / fixed_record_size_bytes); count is also clamped to available records",
    }


def evidence(app, container):
    import capstone

    if capstone.__version__ != "5.0.3":
        raise ValueError("Use the preserved Capstone 5.0.3 analysis runtime")

    # Pin UI descriptors to the configuration bytes used by the two serial paths.
    descriptor_specs = (
        ("CI-V Baud Rate", 0x201924F4, 0x201924CC, 0x203DE524),
        ("CI-V Address", 0x20192534, 0x2019254C, 0x203DE526),
        ("CI-V Transceive", 0x20192574, 0x2019258C, 0x203DE527),
        ("CI-V USB Port", 0x20192634, 0x2019264C, 0x203DE52A),
        ("CI-V USB Baud Rate", 0x20192674, 0x2019268C, 0x203DE52B),
        ("CI-V USB Echo Back", 0x201926B4, 0x201926CC, 0x203DE52C),
        ("USB Serial Function", 0x201926F4, 0x2019270C, 0x203DE52D),
    )
    settings = {}
    for label, label_pointer, field_pointer, expected_field in descriptor_specs:
        actual_label = c_string(app, word(app, label_pointer))
        field = word(app, field_pointer)
        if actual_label != label or field != expected_field:
            raise ValueError(f"Unexpected {label} configuration descriptor")
        settings[label] = {
            "field_address": hex(field),
            "offset_from_config_base": hex(field - 0x203DE4CC),
        }
    group_label = c_string_bytes(app, word(app, 0x201925B4))
    if b"CI-V USB" not in group_label or b"REMOTE" not in group_label:
        raise ValueError("Expected combined CI-V USB/REMOTE settings group label")

    # UART-style receive callback registration and frame parser handoff.
    registrations = []
    for event, move_site, literal_site, call_site in (
        (0xDF, 0x20010DC0, 0x20010DC4, 0x20010DCC),
        (0xDD, 0x20010DF0, 0x20010DF4, 0x20010DFC),
        (0xDE, 0x20010E20, 0x20010E24, 0x20010E2C),
    ):
        mov = instruction(app, move_site)
        if mov.mnemonic != "mov" or immediate(mov, 1) != event:
            raise ValueError(f"Unexpected event ID setup at {move_site:#x}")
        expect_call(app, call_site, 0x200B9490)
        registrations.append({
            "event_id": hex(event),
            "registration_call": hex(call_site),
            "callback_pointer": hex(literal_value(app, literal_site)),
        })
    if any(int(item["callback_pointer"], 16) != 0x20010C64 for item in registrations):
        raise ValueError("Serial callback registration targets changed")

    expect_call(app, 0x20010C5C, 0x2001099C)
    expect_call(app, 0x2000B2E0, 0x2000B03C)
    for site in (0x20029B60, 0x20052F5C, 0x200531FC):
        expect_call(app, site, 0x2000B258)

    rx_store = instruction(app, 0x20010BA0)
    rx_byte = {"mnemonic": rx_store.mnemonic, "operands": rx_store.op_str}
    tx_store = instruction(app, 0x2001159C)
    tx_byte = {"mnemonic": tx_store.mnemonic, "operands": tx_store.op_str}
    if literal_value(app, 0x20010B94) != 0xE8007000:
        raise ValueError("Receive register base changed")
    if literal_value(app, 0x20011598) != 0xE8007000:
        raise ValueError("Transmit register base changed")

    if immediate(instruction(app, 0x200109D0), 1) != 0xFE:
        raise ValueError("Expected FEh frame-start check")
    if immediate(instruction(app, 0x200109E0), 1) != 0xFD:
        raise ValueError("Expected FDh frame-end check")

    command_buffer = literal_value(app, 0x2000B2B8)
    frame_state = literal_value(app, 0x20010A50)
    receive_buffer = literal_value(app, 0x20010AFC)
    output_buffer = literal_value(app, 0x2000AEE0)
    if (frame_state, receive_buffer, command_buffer, output_buffer) != (
        0x20396AD4, 0x20396D84, 0x20396CBC, 0x20396D20
    ):
        raise ValueError("One of the reviewed frame buffers changed")

    command_byte = instruction(app, 0x2000B04C)
    if command_byte.mnemonic != "ldrb" or command_byte.op_str != "r0, [r1, #1]":
        raise ValueError("Expected dispatcher to read command byte at frame +1")
    if immediate(instruction(app, 0x2000B054), 1) != 0xF0:
        raise ValueError("Expected command-range high guard")
    if immediate(instruction(app, 0x2000B05C), 1) != 0x2B:
        raise ValueError("Expected command-table bound 0x2b")
    if literal_value(app, 0x2000B06C) != COMMAND_TABLE:
        raise ValueError("Command table base changed")
    if literal_value(app, 0x2000B114) != HANDLER_TABLE:
        raise ValueError("Handler table base changed")

    # Response-builder and command-specific serializer callback boundary.
    expect_call(app, 0x2000AF88, 0x2000AACC)
    expect_call(app, 0x2000AF8C, 0x2000AA88)
    if literal_value(app, 0x2000AE10) != HANDLER_TABLE:
        raise ValueError("Response builder's handler table reference changed")
    callback_load = instruction(app, 0x2000AE18)
    if callback_load.mnemonic != "ldr" or callback_load.op_str != "r1, [r1, #8]":
        raise ValueError("Expected response callback at handler row +8")
    callback_call = instruction(app, 0x2000AE1C)
    if callback_call.mnemonic != "blx" or callback_call.op_str != "r1":
        raise ValueError("Expected indirect command-specific response callback")
    if immediate(instruction(app, 0x2000AACC), 1) != 0xFD:
        raise ValueError("Expected CI-V frame terminator in response builder")
    serializer_callback = command_1a05(app)
    if serializer_callback["handler_row"] != "0x2018b174":
        raise ValueError("Unexpected 1Ah/05h handler row")
    if serializer_callback["callback_roles"] != {
        "plus4_input_or_setting_callback": "0x2000dcb4",
        "plus8_response_serializer": "0x2000ffb0",
        "plus12_response_preflight": "0x2000f1c0",
    }:
        raise ValueError("Unexpected 1Ah/05h callback role mapping")
    if literal_value(app, 0x2000DCC4) != 0x20396CBF:
        raise ValueError("1Ah/05h input callback no longer parses from dispatcher input +3")
    expect_call(app, 0x2000DCC8, 0x2000D380)
    expect_call(app, 0x2000DD08, 0x2000D470)
    expect_call(app, 0x2000DD1C, 0x2000D3F0)
    expect_instruction(app, 0x2000D580, "strb", "r0, [r2]")
    if literal_value(app, 0x2000FFB4) != command_buffer:
        raise ValueError("1Ah/05h response serializer input context changed")
    expect_call(app, 0x2000FFD0, 0x2000D380)
    expect_call(app, 0x20010000, 0x2000FD48)
    expect_call(app, 0x20010010, 0x2000FCD8)
    expect_instruction(app, 0x2000AE3C, "ldr", "r2, [r0, #0xc]")
    expect_instruction(app, 0x2000AE40, "blx", "r2")
    expect_call(app, 0x2000AE5C, 0x2000ADE0)
    expect_instruction(app, 0x2000AE18, "ldr", "r1, [r1, #8]")
    expect_instruction(app, 0x2000AD10, "ldr", "r2, [r5, #4]")
    expect_instruction(app, 0x2000AD18, "blx", "r2")
    if int(serializer_callback["callback_words_at_plus4_plus8_plus12"][1], 16) != 0x2000FFB0:
        raise ValueError("Unexpected 1Ah/05h response callback")

    # CI-V USB selector -> E8007800 controller -> receive callback/parser.
    if literal_value(app, 0x20011DA0) != 0x203DE4CC:
        raise ValueError("USB setup no longer reads the pinned settings structure")
    for site, operand in (
        (0x20011DA4, "r5, [r3, #0x5f]"),
        (0x20011DB0, "r0, [r3, #0x60]"),
        (0x20011DBC, "r0, [r3, #0x61]"),
        (0x20011DC4, "r0, [r3, #0x5e]"),
    ):
        expect_instruction(app, site, "ldrb", operand)
    if immediate(instruction(app, 0x20011DC8), 1) != 6:
        raise ValueError("USB port selector special-case changed")
    if literal_value(app, 0x20011DDC) != 0x20396BC8:
        raise ValueError("USB port mode is no longer stored beside the USB frame state")
    expect_instruction(app, 0x20011DE0, "strb", "r0, [r1, #0xf3]")
    expect_branch(app, 0x20011DE8, 0x20011C90)
    if literal_value(app, 0x20011C98) != 0xE8007800:
        raise ValueError("USB serial setup controller base changed")
    if literal_value(app, 0x20010E80) != 0x203DE4CC:
        raise ValueError("General CI-V serial setup config pointer changed")
    expect_instruction(app, 0x20010E84, "ldrb", "r0, [r0, #0x58]")
    expect_branch(app, 0x20010E9C, 0x20010C68)

    usb_registrations = []
    for event, move_site, literal_site, call_site, callback in (
        (0xE3, 0x20011EC8, 0x20011ECC, 0x20011ED4, 0x20011964),
        (0xE1, 0x20011EF0, 0x20011EF4, 0x20011EFC, 0x20011964),
        (0xE2, 0x20011F18, 0x20011F1C, 0x20011F24, 0x20011964),
        (0xE4, 0x20011F40, 0x20011F44, 0x20011F4C, 0x20011B98),
    ):
        mov = instruction(app, move_site)
        if mov.mnemonic != "mov" or immediate(mov, 1) != event:
            raise ValueError(f"Unexpected USB event ID setup at {move_site:#x}")
        if literal_value(app, literal_site) != callback:
            raise ValueError(f"Unexpected callback for USB event {event:#x}")
        expect_call(app, call_site, 0x200B9490)
        usb_registrations.append({
            "event_id": hex(event),
            "registration_call": hex(call_site),
            "callback_pointer": hex(callback),
        })
    expect_branch(app, 0x20011964, 0x2001187C)
    if literal_value(app, 0x200118A0) != 0xE8007814:
        raise ValueError("USB receive callback data-register address changed")
    expect_instruction(app, 0x200118AC, "ldrb", "r0, [r4]")
    if literal_value(app, 0x2001163C) != 0x20396F13:
        raise ValueError("USB receive assembly state changed")
    if immediate(instruction(app, 0x20011658), 1) != 0xFE:
        raise ValueError("USB parser frame-start check changed")
    if immediate(instruction(app, 0x2001166C), 1) != 0xFD:
        raise ValueError("USB parser frame-end check changed")
    usb_frame_state = literal_value(app, 0x200117B0)
    usb_frame_source = literal_value(app, 0x200117B4)
    if (usb_frame_state, usb_frame_source) != (0x20396BC8, 0x20396E4C):
        raise ValueError("USB parser completed-frame buffers changed")
    frame_copy_call = instruction(app, 0x200117C0)
    if frame_copy_call.mnemonic != "blx" or immediate(frame_copy_call) != 0x2017C710:
        raise ValueError("USB parser completed-frame copy call changed")
    expect_instruction(app, 0x200117C8, "strb", "r0, [sl, #0x65]")
    expect_instruction(app, 0x200117CC, "strb", "sb, [sl]")

    # Dispatcher output is copied back to the USB state, then drained by the
    # foreground USB service and its event-driven byte transmitter.
    if literal_value(app, 0x2000AA88) != 0x20390031:
        raise ValueError("Response-ready state pointer changed")
    expect_instruction(app, 0x2000AA90, "strb", "r0, [r1, #3]")
    usb_tx_pending = usb_frame_state + 0xCA
    usb_tx_payload = usb_frame_state + 0x66
    if literal_value(app, 0x2000B260) != 0x20396AD4:
        raise ValueError("Foreground copy service primary state changed")
    expect_instruction(app, 0x2000B26C, "add", "r6, r4, #0xf4")
    if literal_value(app, 0x2000B2FC) != output_buffer:
        raise ValueError("Dispatcher response buffer copy source changed")
    expect_instruction(app, 0x2000B300, "add", "r0, r6, #0x66")
    expect_instruction(app, 0x2000B308, "ldrb", "r0, [r5, #3]")
    expect_instruction(app, 0x2000B30C, "strb", "r0, [r6, #0xca]")
    expect_call(app, 0x20029B68, 0x20012854)
    if literal_value(app, 0x20012858) != 0x203DE4CC:
        raise ValueError("USB transmit service config pointer changed")
    expect_instruction(app, 0x2001285C, "ldrb", "r0, [r0, #0x60]")
    expect_branch(app, 0x20012864, 0x20012A4C, "bne")
    if literal_value(app, 0x200128AC) != usb_frame_state:
        raise ValueError("USB transmit service no longer consumes dispatcher USB state")
    if literal_value(app, 0x200128CC) != 0x20396EAF:
        raise ValueError("USB transmit staging buffer changed")
    expect_instruction(app, 0x200128D0, "strb", "r0, [r1, #1]")
    expect_instruction(app, 0x200128D4, "strb", "r0, [r1]")
    expect_instruction(app, 0x200128DC, "add", "r1, r7, #0x66")
    if immediate(instruction(app, 0x200128F0), 1) != 0xFD:
        raise ValueError("USB transmit staging terminator check changed")
    expect_branch(app, 0x20011BAC, 0x20011A68)
    if literal_value(app, 0x20011A70) != 0x20396EAF:
        raise ValueError("USB transmit callback staging buffer changed")
    if literal_value(app, 0x2001196C) != 0xE800780C:
        raise ValueError("USB serial transmit data-register address changed")
    expect_instruction(app, 0x20011970, "strb", "r0, [r1]")

    foreground = foreground_context(app)
    capacity = response_capacity(app, output_buffer, receive_buffer, usb_frame_state)

    return {
        "source": {
            "model": "IC-7300",
            "firmware_version": "1.42",
            "container_sha256": hashlib.sha256(container).hexdigest(),
            "application_sha256": digest(app),
            "capstone_version": capstone.__version__,
        },
        "settings": {
            "config_structure": "0x203de4cc",
            "descriptor_fields": settings,
            "group_label_ascii_fragments": ["CI-V USB", "REMOTE"],
        },
        "receive": {
            "software_path": "separate CI-V serial path; board connector unverified",
            "register_base": "0xe8007000",
            "rx_data_instruction": {"address": "0x20010ba0", **rx_byte},
            "tx_data_instruction": {"address": "0x2001159c", **tx_byte},
            "event_callback_registrations": registrations,
            "callback_entry": "0x20010c64",
            "callback_branch_target": hex(immediate(instruction(app, 0x20010C64))),
            "frame_delimiters": {"start": "0xfe", "end": "0xfd"},
            "buffers": {
                "receive_assembly": hex(receive_buffer),
                "completed_frame_state": hex(frame_state),
                "dispatcher_input": hex(command_buffer),
            },
            "completed_frame_parser_call": "0x20010c5c -> 0x2001099c",
        },
        "usb_transport": {
            "selector": "CI-V USB Port at config +0x5e",
            "selector_setup": {
                "routine": "0x20011d38",
                "port_read": "0x20011dc4",
                "usb_baud_read": "0x20011da4",
                "echo_back_read": "0x20011db0",
                "alternate_usb_serial_function_read": "0x20011dbc",
                "controller_setup": "0x20011c90",
                "controller_register_base": "0xe8007800",
                "port_value_6_maps_to": 1,
            },
            "event_callback_registrations": usb_registrations,
            "receive": {
                "callback_entry": "0x20011964",
                "callback_branch_target": "0x2001187c",
                "rx_data_register": "0xe8007814",
                "rx_byte_instruction": "0x200118ac",
                "frame_parser": "0x20011618",
                "frame_delimiters": {"start": "0xfe", "end": "0xfd"},
                "assembly_state": "0x20396f13",
                "completed_frame_source": hex(usb_frame_source),
                "completed_frame_state": hex(usb_frame_state),
                "copy_call": "0x200117c0",
            },
            "foreground_handoff": {
                "copy_service": "0x2000b258",
                "dispatcher_input": hex(command_buffer),
                "dispatcher": "0x2000b03c",
                "usb_state_selection_marker": "0x20390036",
                "response_payload_destination": hex(usb_tx_payload),
                "response_pending_byte": hex(usb_tx_pending),
            },
            "transmit": {
                "foreground_service": "0x20012854",
                "foreground_call_site": "0x20029b68",
                "service_gate": "CI-V USB Echo Back (config +0x60) must be zero for this traced path; nonzero branches to return at 0x20012a4c",
                "staging_buffer": "0x20396eaf",
                "event_id": "0xe4",
                "event_callback": "0x20011b98",
                "callback_send_branch": "0x20011bac -> 0x20011a68",
                "byte_writer": "0x20011968",
                "tx_data_register": "0xe800780c",
                "tx_byte_instruction": "0x20011970",
            },
        },
        "dispatch": {
            "foreground_copy_service_callers": ["0x20029b60", "0x20052f5c", "0x200531fc"],
            "foreground_context": foreground,
            "copy_service": "0x2000b258",
            "dispatcher": "0x2000b03c",
            "command_table": hex(COMMAND_TABLE),
            "handler_table": hex(HANDLER_TABLE),
            "command_id_guard": "command byte at input +1; IDs >=0x2b rejected",
            "command_1a_subcommand_05": serializer_callback,
            "command_1a05_callback_separation": {
                "setting_or_input_route": "handler row +4 -> 0x2000dcb4 -> 0x2000d470 or 0x2000d3f0; the 0x2000d470 path contains a direct STRB to descriptor-selected storage",
                "response_route": "0x2000ae28 calls handler row +12 preflight, then 0x2000ade0 loads handler row +8 serializer; this route does not call row +4",
                "read_only_scope": "structural route separation only; not a proof that every serializer/helper is side-effect free",
            },
        },
        "response": {
            "frame_output_buffer": hex(output_buffer),
            "command_specific_serializer_callback": "0x2000ffb0",
            "terminator_append_call": "0x2000af88 -> 0x2000aacc",
            "ready_flag_call": "0x2000af8c -> 0x2000aa88",
            "ready_flag_address": "0x20390034",
            "dispatch_to_serializer": "0x2000ae18 loads handler-row +8; 0x2000ae1c calls it",
            "shared_buffer_ownership": "one static builder buffer is marked ready at 0x20390034; 0x2000b258 copies 100 bytes to a transport slot. The USB path exposes one payload slot and a pending marker; FIFO depth/backpressure are not established.",
            "usb_state_copy": "0x2000b2fc copies response buffer to 0x20396bc8+0x66; 0x2000b30c marks 0x20396bc8+0xca pending",
            "usb_transmit_chain": "0x20012854 -> 0x20396eaf -> event 0xe4 callback 0x20011b98 -> data register 0xe800780c",
            "capacity": capacity,
            "physical_usb_endpoint": "board-level endpoint/electrical mapping unverified",
        },
        "limitations": [
            "The CI-V USB configuration, E8007800 receive callbacks, parser, foreground return queue, and E800780c byte writer are statically linked; board-level connector wiring is not.",
            "Callback registration is mapped, but whether callbacks run in interrupt or worker context is not resolved. The byte callbacks poll and touch controller state, so keep diagnostic work out of them.",
            "At 0x20029b60, the mapped control loop at 0x20029914 explicitly enables interrupts at 0x20029b00 and executes WFI at 0x20029b14 before the foreground dispatcher call; task identity and all scheduling modes remain unresolved.",
            "The traced USB response queue path is gated by config +0x60 equal to zero; the alternate nonzero branch returns and its transmit behavior is unresolved.",
            "CI-V USB and separate CI-V serial settings/register paths are distinct in the image. Board connector naming and electrical routing remain unverified.",
            "Static mapping does not qualify a new diagnostic command or establish its read-only behavior.",
            "The generic reply copy and USB transmit staging are each 100 bytes; the transmit loop scans for FD without an independent length guard. A new response must enforce a body cap of at most 98 bytes including FD before it reaches the queue.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path, help="official v1.42 update image")
    args = parser.parse_args()
    container, app = load_app(args.image)
    print(json.dumps(evidence(app, container), indent=2))


if __name__ == "__main__":
    main()
