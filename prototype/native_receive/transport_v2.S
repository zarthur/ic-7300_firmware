/* Original recorder-carrier core; replaces only a 216-byte payload copy.
 * r0 destination[216], r1 original[216], r2 frozen capture storage[114704],
 * r3 transport control {frame_index,status}; all buffers non-overlapping.
 * status 0 waiting, 1 exporting, 2 done, 3 invalid. Single serialized caller.
 * Until capture is frozen with a consistent v2 header, and after export, copy original audio unchanged.
 * Frames: magic[8], total, byte_offset, payload_length, FNV1a32, payload[192].
 * This core does not arm capture, call filesystems, or access device registers.
 */
.syntax unified
.arch armv7-a
.arm
.text
.balign 4
.global receive_transport_v2
.type receive_transport_v2,%function
receive_transport_v2:
    push {r4-r11, ip, lr}
    mov r4, r0
    mov r5, r1
    mov r6, r2
    mov r7, r3
    ldr r0, [r7, #4]
    cmp r0, #1
    bhi .Ltransport_passthrough
    ldr r0, [r6]
    mov ip, r0
    cmp r0, #2
    beq .Lv2_frozen
    cmp r0, #5
    beq .Lv2_frozen
    cmp r0, #6
    bne .Ltransport_passthrough
.Lv2_frozen:
    dmb sy
    ldr r0, [r6, #4]
    cmp ip, #2
    beq .Lv2_full
    cmp ip, #5
    beq .Lv2_with_record
    cmp r0, #512
    bhs .Ltransport_invalid
    b .Lv2_identity
.Lv2_with_record:
    cmp r0, #0
    beq .Ltransport_invalid
    cmp r0, #512
    bhi .Ltransport_invalid
    b .Lv2_identity
.Lv2_full:
    cmp r0, #512
    bne .Ltransport_invalid
.Lv2_identity:
    ldr r0, [r6, #8]
    movw r1, #0x434e
    movt r1, #0x3252
    cmp r0, r1
    bne .Ltransport_invalid
    ldr r0, [r6, #12]
    cmp r0, #2
    bne .Ltransport_invalid
    ldr r8, [r7]
    movw r0, #598
    cmp r8, r0
    bhs .Ltransport_invalid
    add r1, r8, r8, lsl #1
    lsl r1, r1, #6
    movw r2, #0xc010
    movt r2, #1
    sub r9, r2, r1
    cmp r9, #192
    movhi r9, #192
    movw r0, #0x4349
    movt r0, #0x3337
    str r0, [r4]
    movw r0, #0x5852
    movt r0, #0x3230
    str r0, [r4, #4]
    str r2, [r4, #8]
    str r1, [r4, #12]
    str r9, [r4, #16]
    add r1, r6, r1
    add r0, r4, #24
    mov r2, r9
    movw r10, #0x9dc5
    movt r10, #0x811c
    movw r11, #0x193
    movt r11, #0x100
.Ltransport_payload:
    ldrb ip, [r1], #1
    strb ip, [r0], #1
    eor r10, r10, ip
    mul r10, r10, r11
    subs r2, r2, #1
    bne .Ltransport_payload
    str r10, [r4, #20]
    rsb r2, r9, #192
    mov r1, #0
    cmp r2, #0
    beq .Ltransport_published
.Ltransport_padding:
    strb r1, [r0], #1
    subs r2, r2, #1
    bne .Ltransport_padding
.Ltransport_published:
    add r8, r8, #1
    str r8, [r7]
    movw r0, #598
    cmp r8, r0
    moveq r0, #2
    movne r0, #1
    dmb sy
    str r0, [r7, #4]
    mov r0, r4
    pop {r4-r11, ip, pc}
.Ltransport_invalid:
    mov r0, #3
    str r0, [r7, #4]
.Ltransport_passthrough:
    mov r0, r4
    mov r1, r5
    mov r2, #216
.Ltransport_original:
    ldrb r3, [r1], #1
    strb r3, [r0], #1
    subs r2, r2, #1
    bne .Ltransport_original
    mov r0, r4
    pop {r4-r11, ip, pc}
.size receive_transport_v2, .-receive_transport_v2
