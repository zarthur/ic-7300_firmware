/* Exact-image offline handler hooks, not an installable candidate.
 * Trial layout: code20362000, capture20364000, live2038f000, epoch2038f080.
 * Entry precedes DMA status read; idle/restart exits cancel the observation.
 * Ready hook preserves the original queue call after bounded capture.
 */
.syntax unified
.arch armv7-a
.arm
.text
.balign 4
.Lhooks:
.word 0x32483733, 2
.word .Lhook_entry-.Lhooks, .Lhook_idle-.Lhooks, .Lhook_restart-.Lhooks
.word .Lhook_ready-.Lhooks, .Lcapture_bundle-.Lhooks, .Lobserver_bundle-.Lhooks, .Lhooks_end-.Lhooks

.macro save_inputs
    push {r0-r3, ip, lr}
    mrs ip, cpsr
    push {r3, ip}
.endm
.macro restore_inputs
    pop {r3, ip}
    msr apsr_nzcvqg, ip
    pop {r0-r3, ip, lr}
.endm
.macro capture_addresses
    ldr r0, =0x20364000
    ldr r1, =0x2038f000
    ldr r2, =0x2038f080
.endm

.Lhook_entry:
    save_inputs
    capture_addresses
    adr lr, .Lhook_entry_done
    b .Lbegin
.Lhook_entry_done:
    restore_inputs
    push {r4-r6, lr}
    ldr pc, =0x20060618

.Lhook_idle:
    save_inputs
    capture_addresses
    adr lr, .Lhook_idle_done
    b .Lcancel
.Lhook_idle_done:
    restore_inputs
    pop {r4-r6, pc}

.Lhook_restart:
    save_inputs
    capture_addresses
    adr lr, .Lhook_restart_done
    b .Lcancel
.Lhook_restart_done:
    restore_inputs
    ldr pc, =0x200605e4

.Lhook_ready:
    save_inputs
    /* Stack argument, saved mask, and twelve observations. */
    sub sp, sp, #56
    mrs ip, cpsr
    str ip, [sp, #4]
    cpsid if
    ldr r1, =0x2038f000
    ldr r0, [r1, #12]
    cmp r0, #0
    bne .Lhook_skip_observe
    ldr r0, [r1]
    cmp r0, #1
    bne .Lhook_skip_observe
    ldr r0, [r1, #4]
    cmp r0, #1
    bne .Lhook_skip_observe
    ldr r0, =0x20364000
    ldr r0, [r0]
    cmp r0, #4
    bne .Lhook_skip_observe
    ldr ip, [sp, #4]
    msr cpsr_c, ip
    .irp offset, 8, 20
        dmb sy
        ldr r0, =0x20390a78
        ldr r1, [r0]
        str r1, [sp, #\offset]
        dmb sy
        ldr r0, =0xfcfec004
        ldr r1, [r0]
        str r1, [sp, #(\offset+4)]
        dmb sy
        ldr r0, =0xe8201210
        ldr r1, [r0]
        str r1, [sp, #(\offset+8)]
    .endr
    dmb sy
    /* Original R2 is the selected source-end pointer after extraction. */
    ldr r0, [sp, #72]
    str r0, [sp, #32]
    add r0, sp, #36
    ldr r1, =0x2038f008
    adr lr, .Lhook_observed
    b .Lssif_observe
.Lhook_skip_observe:
    ldr ip, [sp, #4]
    msr cpsr_c, ip
.Lhook_observed:
    add r0, sp, #8
    str r0, [sp]
    capture_addresses
    /* Original R0 points at the two contiguous extracted streams. */
    ldr r3, [sp, #64]
    adr lr, .Lhook_ready_done
    b .Lfinish
.Lhook_ready_done:
    add sp, sp, #56
    restore_inputs
    ldr pc, =0x2005fb28

.ltorg
.Lcapture_bundle:
#include "capture_v2.S"
.Lobserver_bundle:
#include "ssif_observe.S"
.ltorg
.Lhooks_end:
