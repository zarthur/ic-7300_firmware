/* Offline recorder integration: no firmware writer or target installation.
 * Code 20363000; capture20364000, live2038f000, export2038f040.
 * First nonzero recorder submission arms once, only with idle initialized state.
 * Serialize recorder calls. Lifecycle boundaries never reset frozen captures.
 */
.syntax unified
.arch armv7-a
.arm
.text
.balign 4
.Lrecorder_bundle:
.word 0x32523733, 2
.word .Lrecorder_arm-.Lrecorder_bundle, .Lrecorder_carrier-.Lrecorder_bundle
.word .Lrecorder_transport-.Lrecorder_bundle, .Lrecorder_end-.Lrecorder_bundle

/* Replace BL at 200497f0, retain all inputs/flags/masks for original submit. */
.Lrecorder_arm:
    push {r0-r3, ip, lr}
    mrs ip, cpsr
    push {r3, ip}
    cpsid if
    cmp r1, #0
    beq .Lrecorder_arm_done
    ldr r2, =0x20364000
    ldr r0, [r2]
    ldr r3, [r2, #4]
    orrs r0, r0, r3
    bne .Lrecorder_arm_done
    ldr r0, [r2, #8]
    movw r3, #0x434e
    movt r3, #0x3252
    cmp r0, r3
    bne .Lrecorder_arm_done
    ldr r0, [r2, #12]
    cmp r0, #2
    bne .Lrecorder_arm_done
    ldr ip, =0x2038f000
    ldm ip, {r0, r1, r3}
    orr r0, r0, r1
    orr r0, r0, r3
    ldr r1, [ip, #12]
    orrs r0, r0, r1
    bne .Lrecorder_arm_done
    ldr ip, =0x2038f040
    ldr r0, [ip]
    ldr r1, [ip, #4]
    orrs r0, r0, r1
    bne .Lrecorder_arm_done
    dmb sy
    mov r0, #1
    str r0, [r2]
    dmb sy
.Lrecorder_arm_done:
    pop {r3, ip}
    msr cpsr_c, ip
    msr apsr_nzcvqg, ip
    pop {r0-r3, ip, lr}
    ldr pc, =0x2006a354

/* Replace BLX memcpy at 20066f80. Other lengths/states keep original memcpy. */
.Lrecorder_carrier:
    cmp r2, #216
    bne .Lrecorder_original
    ldr r3, =0x20364000
    ldr ip, [r3]
    cmp ip, #2
    beq .Lrecorder_frozen
    cmp ip, #5
    beq .Lrecorder_frozen
    cmp ip, #6
    bne .Lrecorder_original
.Lrecorder_frozen:
    ldr ip, =0x2038f040
    ldr ip, [ip, #4]
    cmp ip, #1
    bhi .Lrecorder_original
    mov r2, r3
    ldr r3, =0x2038f040
    adr ip, .Lrecorder_transport
    bx ip
.Lrecorder_original:
    ldr pc, =0x2017c711

.ltorg
.Lrecorder_transport:
#include "transport_v2.S"
.ltorg
.Lrecorder_end:
