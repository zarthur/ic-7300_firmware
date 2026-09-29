/* Read-only SSI0 observation: r0=output[5], r1=live flags word.
 * Requires privileged single-CPU execution and maskable clock-state writers.
 * Never accesses SSI while MSTP115 is set; marks unavailable flag16 instead.
 * Output order: SSICR, SSIFCR, SSISR, SSIFSR, SSITDMR. No FIFO data reads.
 * Return 1 observed, 0 unavailable. AAPCS; restores incoming IRQ/FIQ masks.
 */
.syntax unified
.arch armv7-a
.arm
.text
.balign 4
.Lssi_base:
.word .Lssi_code_end-.Lssi_base, .Lssi_end-.Lssi_base
.Lssif_observe:
    push {r4-r8, lr}
    mov r4, r0
    mov r8, r1
    mrs r5, cpsr
    cpsid if
    ldr r6, =0xfcfe0440
    ldrb r6, [r6]
    dmb sy
    tst r6, #0x20
    bne .Lssi_unavailable
    ldr r7, =0xe820b000
    ldr r0, [r7]
    str r0, [r4]
    ldr r0, [r7, #0x10]
    str r0, [r4, #4]
    ldr r0, [r7, #4]
    str r0, [r4, #8]
    ldr r0, [r7, #0x14]
    str r0, [r4, #12]
    ldr r0, [r7, #0x20]
    str r0, [r4, #16]
    mov r0, #1
    b .Lssi_return
.Lssi_unavailable:
    mvn r0, #0
    str r0, [r4]
    str r0, [r4, #4]
    str r0, [r4, #8]
    str r0, [r4, #12]
    str r0, [r4, #16]
    ldr r0, [r8]
    orr r0, r0, #16
    str r0, [r8]
    mov r0, #0
.Lssi_return:
    dmb sy
    msr cpsr_c, r5
    pop {r4-r8, pc}
.Lssi_code_end:
.ltorg
.Lssi_end:
