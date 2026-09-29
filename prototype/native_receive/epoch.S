/* Private transport epoch counter, offline prototype; no installed hooks.
 * r0: initialized, aligned {epoch, last_reason, exhausted, reserved} (16 bytes).
 * r1: 1 cold-start entry, 2 shared-restart entry, 3 stop entry, 4 start entry.
 * Return 1: advanced; 0: permanently exhausted/invalid. AAPCS ARM.
 * Caller MUST serialize all readers/writers; DMB is not a lock. This marks
 * boundaries only, never declares valid samples or successful hardware start.
 * Epoch zero means unobserved. Never wrap/reuse an epoch within this lifetime.
 * State is separate from capture/export storage, including frozen captures.
 */
.syntax unified
.arch armv7-a
.arm
.text
.balign 4
.global receive_epoch_boundary
.type receive_epoch_boundary,%function
receive_epoch_boundary:
    ldr r2, [r0, #8]
    cmp r2, #0
    bne .Lepoch_inactive
    cmp r1, #1
    blo .Lepoch_exhaust
    cmp r1, #4
    bhi .Lepoch_exhaust
.Lepoch_reason_ok:
    ldr r2, [r0]
    cmn r2, #1
    beq .Lepoch_exhaust
    add r2, r2, #1
    str r1, [r0, #4]
    dmb sy
    str r2, [r0]
    dmb sy
    mov r0, #1
    bx lr
.Lepoch_exhaust:
    mov r2, #1
    str r2, [r0, #8]
    dmb sy
.Lepoch_inactive:
    mov r0, #0
    bx lr
.size receive_epoch_boundary, .-receive_epoch_boundary
