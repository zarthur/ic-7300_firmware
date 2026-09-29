/* Offline exact-v1.42 entry wrappers, separate from installed v1 diagnostic.
 * Trial placement only: code 20363000, private initialized state 2037e080.
 * Each entry replaces an original PUSH with B (not BL), retaining caller LR.
 * Mask IRQ/FIQ only around the private counter update; restore original masks,
 * general registers and APSR, replay the original PUSH, continue at entry+4.
 * This is not a placement/initialization or complete lifecycle qualification.
 */
#ifndef RX_EPOCH_STATE
#define RX_EPOCH_STATE 0x2037e080
#endif
.syntax unified
.arch armv7-a
.arm
.text
.balign 4
.Lepoch_bundle:
.word 0x45503733, 1
.word .Lcold-.Lepoch_bundle, .Lrestart-.Lepoch_bundle
.word .Lstop-.Lepoch_bundle, .Lstart-.Lepoch_bundle
.word .Lcore-.Lepoch_bundle, .Lend-.Lepoch_bundle

.macro boundary name, reason, continuation, saved
\name:
    push {r0-r3, ip, lr}
    mrs ip, cpsr
    cpsid if
    push {r3, ip}
    ldr r0, =RX_EPOCH_STATE
    mov r1, #\reason
    adr lr, .Lafter_\name
    adr ip, .Lcore
    bx ip
.Lafter_\name:
    pop {r3, ip}
    msr cpsr_c, ip
    msr apsr_nzcvqg, ip
    pop {r0-r3, ip, lr}
    push {\saved}
    ldr pc, =\continuation
.endm

boundary .Lcold, 1, 0x20060600, "r4, lr"
boundary .Lrestart, 2, 0x200605e8, "r4, lr"
boundary .Lstop, 3, 0x200604c8, "r4-r10, lr"
boundary .Lstart, 4, 0x20060040, "r4-r6, lr"

.Lcore:
#include "epoch.S"
.ltorg
.Lend:
