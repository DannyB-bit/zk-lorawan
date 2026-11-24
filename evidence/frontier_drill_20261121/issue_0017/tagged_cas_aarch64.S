// Real ARMv8 128-bit tagged-head CAS: pointer + 64-bit epoch.
// bool atomic_cas_tagged_asm(head=x0, expected=x1, desired=x2)
// expected is refreshed on comparison failure, matching C11 CAS semantics.
.text
.align 2
.global atomic_cas_tagged_asm
.type atomic_cas_tagged_asm, %function
atomic_cas_tagged_asm:
    mov     x9, x0
    ldp     x3, x4, [x1]
    ldp     x5, x6, [x2]
1:
    ldaxp   x7, x8, [x9]
    cmp     x7, x3
    ccmp    x8, x4, #0, eq
    b.ne    3f
    stlxp   w10, x5, x6, [x9]
    cbnz    w10, 1b
    mov     w0, #1
    ret
3:
    stp     x7, x8, [x1]
    clrex
    mov     w0, #0
    ret
.size atomic_cas_tagged_asm, .-atomic_cas_tagged_asm
.section .note.GNU-stack,"",@progbits
