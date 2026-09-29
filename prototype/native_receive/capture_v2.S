/* Offline two-phase capture core. No hardware addresses or external calls.
 * Every handler calls begin before status/bank selection, even while inactive.
 * Pair with finish for ready data or cancel for idle/restart exits.
 * begin(r0=storage, r1=live[8], r2=epoch[4]);
 * finish(r0=storage, r1=live[8], r2=epoch[4], r3=samples[144], stack[0]=obs[48]).
 * cancel(r0=storage, r1=live[8]); no sample or epoch access.
 * Storage: {status,count,magic=0x3252434e,version=2}, 512 records of 224 bytes.
 * Record: seq, flags, epoch_before[3], epoch_after[3], obs[12], samples[144].
 * Live: depth, owner, faults, poison, epoch_before[3], reserved. Initially zero.
 * Status: 0 disabled,1 armed,2 full,3 reserved invalid,4 busy,
 * 5 aborted with flagged final record,6 aborted without an outer record.
 * Flags: 1 epoch changed,2 epoch unknown,4 exhausted,8 nested extraction,
 * 16 SSI observations unavailable (only set by the ready-path observer).
 * Commit does NOT prove DMA ownership, physical channel phase or acquisition time.
 * Single CPU privileged ARM; IRQ/FIQ state updates are masked. No rearm API.
 * Poison never publishes a frozen capture. Frozen storage is never changed.
 */
.syntax unified
.arch armv7-a
.arm
.text
.balign 4
.Lv2:
.word 0x3256434e, 2
.word .Lbegin-.Lv2, .Lfinish-.Lv2, .Lcancel-.Lv2, .Lsamples-.Lv2, .Lend-.Lv2

.Lbegin:
    push {r4-r8, lr}
    mov r4, r0
    mov r5, r1
    mov r6, r2
    mrs r7, cpsr
    cpsid if
    ldr r0, [r5, #12]
    cmp r0, #0
    bne .Lbegin_done
    ldr r8, [r5]
    cmn r8, #1
    beq .Lbegin_poison
    add r0, r8, #1
    str r0, [r5]
    cmp r8, #0
    beq .Lbegin_outer
    ldr r0, [r5, #4]
    cmp r0, #0
    beq .Lbegin_done
    ldr r0, [r5, #8]
    orr r0, r0, #8
    str r0, [r5, #8]
    b .Lbegin_done
.Lbegin_outer:
    ldr r0, [r4]
    cmp r0, #1
    bne .Lbegin_done
    ldr r0, [r4, #8]
    movw r1, #0x434e
    movt r1, #0x3252
    cmp r0, r1
    bne .Lbegin_poison
    ldr r0, [r4, #12]
    cmp r0, #2
    bne .Lbegin_poison
    ldr r0, [r4, #4]
    cmp r0, #512
    bhs .Lbegin_poison
    mov r0, #1
    str r0, [r5, #4]
    mov r0, #0
    str r0, [r5, #8]
    ldm r6, {r0-r2}
    add r3, r5, #16
    stm r3, {r0-r2}
    mov r0, #4
    str r0, [r4]
    b .Lbegin_done
.Lbegin_poison:
    mov r0, #1
    str r0, [r5, #12]
.Lbegin_done:
    dmb sy
    msr cpsr_c, r7
    pop {r4-r8, pc}

.Lfinish:
    push {r4-r11, ip, lr}
    mov r4, r0
    mov r5, r1
    mov r6, r2
    mov r7, r3
    ldr r9, [sp, #40]
    mrs r8, cpsr
    cpsid if
    ldr r0, [r5, #12]
    cmp r0, #0
    bne .Lfinish_inactive
    ldr r0, [r5]
    cmp r0, #0
    beq .Lfinish_poison
    cmp r0, #1
    beq .Lfinish_outer
    sub r0, r0, #1
    str r0, [r5]
    b .Lfinish_inactive
.Lfinish_outer:
    ldr r0, [r5, #4]
    cmp r0, #0
    bne .Lfinish_owner
    str r0, [r5]
    b .Lfinish_inactive
.Lfinish_owner:
    ldr r0, [r4]
    cmp r0, #4
    bne .Lfinish_poison
    ldr r11, [r4, #4]
    cmp r11, #512
    bhs .Lfinish_poison
    /* 224 = 7*32. */
    rsb r10, r11, r11, lsl #3
    add r10, r4, r10, lsl #5
    add r10, r10, #16
    str r11, [r10]
    add ip, r5, #16
    ldm ip, {r0-r2}
    add ip, r10, #8
    stm ip, {r0-r2}
    /* The long observation/sample copy runs with the incoming masks. */
    msr cpsr_c, r8
    add ip, r10, #32
    mov r3, #12
.Lobs:
    ldr r0, [r9], #4
    str r0, [ip], #4
    subs r3, r3, #1
    bne .Lobs
    mov r3, #72
.Lsamples:
    ldrh r0, [r7], #2
    strh r0, [ip], #2
    subs r3, r3, #1
    bne .Lsamples
    cpsid if
    /* Order sample/observation accesses before the closing epoch snapshot. */
    dmb sy
    ldr r0, [r5, #12]
    cmp r0, #0
    bne .Lfinish_inactive
    ldr r0, [r5]
    cmp r0, #1
    bne .Lfinish_poison
    ldr r0, [r5, #4]
    cmp r0, #1
    bne .Lfinish_poison
    ldr r0, [r4]
    cmp r0, #4
    bne .Lfinish_poison
    ldr r0, [r4, #4]
    cmp r0, r11
    bne .Lfinish_poison
    ldr r0, [r5, #8]
    bics r0, r0, #24
    bne .Lfinish_poison
    ldm r6, {r0-r2}
    add ip, r10, #20
    stm ip, {r0-r2}
    ldr r3, [r5, #8]
    ldr ip, [r5, #16]
    cmp r0, ip
    orrne r3, r3, #1
    cmp ip, #0
    orreq r3, r3, #2
    cmp r0, #0
    orreq r3, r3, #2
    ldr ip, [r5, #24]
    orrs ip, ip, r2
    orrne r3, r3, #4
    str r3, [r10, #4]
    dmb sy
    add r11, r11, #1
    str r11, [r4, #4]
    mov r0, #0
    str r0, [r5]
    str r0, [r5, #4]
    mov r0, #1
    cmp r11, #512
    moveq r0, #2
    tst r3, #8
    movne r0, #5
    dmb sy
    str r0, [r4]
    mov r0, #1
    b .Lfinish_done
.Lfinish_poison:
    mov r0, #1
    str r0, [r5, #12]
.Lfinish_inactive:
    mov r0, #0
.Lfinish_done:
    dmb sy
    msr cpsr_c, r8
    pop {r4-r11, ip, pc}

.Lcancel:
    push {r4-r8, lr}
    mov r4, r0
    mov r5, r1
    mrs r7, cpsr
    cpsid if
    ldr r0, [r5, #12]
    cmp r0, #0
    bne .Lcancel_done
    ldr r0, [r5]
    cmp r0, #0
    beq .Lcancel_poison
    cmp r0, #1
    beq .Lcancel_outer
    sub r0, r0, #1
    str r0, [r5]
    b .Lcancel_done
.Lcancel_outer:
    ldr r0, [r5, #4]
    cmp r0, #0
    bne .Lcancel_owner
    str r0, [r5]
    b .Lcancel_done
.Lcancel_owner:
    cmp r0, #1
    bne .Lcancel_poison
    ldr r0, [r4]
    cmp r0, #4
    bne .Lcancel_poison
    ldr r0, [r4, #4]
    cmp r0, #512
    bhs .Lcancel_poison
    ldr r6, [r5, #8]
    bics r0, r6, #8
    bne .Lcancel_poison
    mov r0, #0
    str r0, [r5]
    str r0, [r5, #4]
    mov r0, #1
    cmp r6, #0
    movne r0, #6
    dmb sy
    str r0, [r4]
    b .Lcancel_done
.Lcancel_poison:
    mov r0, #1
    str r0, [r5, #12]
.Lcancel_done:
    dmb sy
    msr cpsr_c, r7
    mov r0, #0
    pop {r4-r8, pc}
.Lend:
