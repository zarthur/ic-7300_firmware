/* Original bounded capture core. No absolute radio addresses or external calls.
 * r0: writable control (16 bytes) followed by 512 records of 176 bytes
 * r1: two contiguous 72-byte streams, halfword aligned
 * r2: seven raw observation words (28 bytes), word aligned
 * Control: status, count, reserved[2]. Single producer; consumer waits for FULL.
 * status: 0 disabled, 1 armed, 2 full, 3 invalid count, 4 busy.
 * Record: sequence, seven observations, 72 signed halfwords (A then B).
 * Return: 1 copied, 0 inactive/busy, -1 invalid count. AAPCS ARM, no VFP use.
 * Caller owns initialization, lifetime, serialization and observation coherence.
 */
.syntax unified
.arch armv7-a
.arm
.text
.balign 4
.global receive_capture
.type receive_capture,%function
receive_capture:
    push {r4-r8, lr}
    mov r4, r0
    ldr r3, [r4]
    cmp r3, #1
    bne inactive
    ldr r7, [r4, #4]
    cmp r7, #512
    bhs invalid
    mov r3, #4
    str r3, [r4]
    /* 176 = 128 + 32 + 16. */
    add r5, r7, r7, lsl #1
    add r5, r5, r7, lsl #3
    add r5, r4, r5, lsl #4
    add r5, r5, #16
    str r7, [r5], #4
    mov r6, #7
observations:
    ldr r8, [r2], #4
    str r8, [r5], #4
    subs r6, r6, #1
    bne observations
    mov r6, #72
samples:
    ldrh r8, [r1], #2
    strh r8, [r5], #2
    subs r6, r6, #1
    bne samples
    dmb sy
    add r7, r7, #1
    str r7, [r4, #4]
    cmp r7, #512
    moveq r3, #2
    movne r3, #1
    dmb sy
    str r3, [r4]
    mov r0, #1
    pop {r4-r8, pc}
inactive:
    mov r0, #0
    pop {r4-r8, pc}
invalid:
    mov r3, #3
    str r3, [r4]
    mvn r0, #0
    pop {r4-r8, pc}
.size receive_capture, .-receive_capture
