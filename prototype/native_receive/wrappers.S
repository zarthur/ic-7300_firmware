/* Exact-v1.42 offline wrapper bundle. No installer in this source.
 * State ranges must be initialized to zero before any hook becomes reachable.
 * Header holds relative entry offsets; absolute placement is 0x20362000.
 */
.syntax unified
.arch armv7-a
.arm
.text
.balign 4
.Lbundle:
.word 0x584e3733, 1
.word .Ldma_entry-.Lbundle, .Lcarrier_entry-.Lbundle, .Larm_entry-.Lbundle
.word .Lcapture_core-.Lbundle, .Ltransport_core-.Lbundle, .Lend-.Lbundle

/* Replace BL 2005fb28 at 200606d8. Preserve original inputs and flags before
 * tail-calling the original queue producer. Observe only while armed. */
.Ldma_entry:
    push {r0-r3, ip, lr}
    mrs ip, apsr
    push {r3, ip}
    ldr r0, =0x20364000
    ldr r1, [r0]
    cmp r1, #1
    bne .Ldma_done
    sub sp, sp, #32
    dmb sy
    ldr r1, =0x20390a78
    ldr r2, [r1]
    str r2, [sp]
    dmb sy
    ldr r1, =0xfcfec004
    ldr r2, [r1]
    str r2, [sp, #4]
    dmb sy
    ldr r1, =0xe8201210
    ldr r2, [r1]
    str r2, [sp, #8]
    dmb sy
    ldr r1, =0x20390a78
    ldr r2, [r1]
    str r2, [sp, #12]
    dmb sy
    ldr r1, =0xfcfec004
    ldr r2, [r1]
    str r2, [sp, #16]
    dmb sy
    ldr r1, =0xe8201210
    ldr r2, [r1]
    str r2, [sp, #20]
    dmb sy
    /* Saved r2 is the source-end pointer left by original DMA extraction. */
    ldr r2, [sp, #48]
    str r2, [sp, #24]
    ldr r1, [sp, #40]
    mov r2, sp
    adr lr, .Ldma_after_capture
    adr ip, .Lcapture_core
    bx ip
.Ldma_after_capture:
    add sp, sp, #32
.Ldma_done:
    pop {r3, ip}
    msr apsr_nzcvq, ip
    pop {r0-r3, ip, lr}
    ldr pc, =0x2005fb28

/* Replace BLX memcpy at 20066f80. Normal copies still use original memcpy. */
.Lcarrier_entry:
    cmp r2, #216
    bne .Lcarrier_original
    ldr r3, =0x20364000
    ldr ip, [r3]
    cmp ip, #2
    bne .Lcarrier_original
    ldr ip, =0x2037a020
    ldr ip, [ip, #4]
    cmp ip, #1
    bhi .Lcarrier_original
    mov r2, r3
    ldr r3, =0x2037a020
    adr ip, .Ltransport_core
    bx ip
.Lcarrier_original:
    ldr pc, =0x2017c711

/* Replace BL submit at 200497f0. A nonzero actual recorder write arms once;
 * a watermark gate or boot-time publisher call cannot arm this capture. */
.Larm_entry:
    push {r0-r3, ip, lr}
    mrs ip, apsr
    push {r3, ip}
    cmp r1, #0
    beq .Larm_done
    ldr r2, =0x20364000
    ldr r3, [r2]
    cmp r3, #0
    bne .Larm_done
    ldr r3, [r2, #4]
    cmp r3, #0
    bne .Larm_done
    ldr ip, =0x2037a020
    ldr r3, [ip]
    ldr r0, [ip, #4]
    orrs r3, r3, r0
    bne .Larm_done
    dmb sy
    mov r3, #1
    str r3, [r2]
    dmb sy
.Larm_done:
    pop {r3, ip}
    msr apsr_nzcvq, ip
    pop {r0-r3, ip, lr}
    ldr pc, =0x2006a354

.Lcapture_core:
#include "capture.S"
.Ltransport_core:
#include "transport.S"
.ltorg
.Lend:
