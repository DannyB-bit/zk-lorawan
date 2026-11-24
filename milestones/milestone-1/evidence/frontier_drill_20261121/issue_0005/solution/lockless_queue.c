#include "lockless_queue.h"

#include <stddef.h>
#include <stdint.h>

#if !defined(__aarch64__)
#error "This frontier proof requires native AArch64 LDAXP/STLXP 128-bit atomics"
#endif

_Static_assert(sizeof(tagged_head) == 16, "tagged head must be pointer + uint64 epoch");
_Static_assert(_Alignof(tagged_head) == 16, "LDAXP/STLXP head requires 16-byte alignment");

static tagged_head tagged_load(const tagged_head *address)
{
    uintptr_t pointer;
    uint64_t epoch;
    __asm__ volatile(
        "ldaxp %0, %1, [%2]\n\t"
        "clrex"
        : "=&r"(pointer), "=&r"(epoch)
        : "r"(address)
        : "memory");
    return (tagged_head){ .ptr = (lockless_node *)pointer, .epoch = epoch };
}

static void tagged_store(tagged_head *address, tagged_head value)
{
    uintptr_t observed_pointer, new_pointer = (uintptr_t)value.ptr;
    uint64_t observed_epoch, new_epoch = value.epoch;
    uint32_t status;
    __asm__ volatile(
        "1:\n\t"
        "ldaxp %0, %1, [%3]\n\t"
        "stlxp %w2, %4, %5, [%3]\n\t"
        "cbnz %w2, 1b"
        : "=&r"(observed_pointer), "=&r"(observed_epoch), "=&r"(status)
        : "r"(address), "r"(new_pointer), "r"(new_epoch)
        : "memory");
}

int lockless_head_compare_exchange(tagged_head *head, tagged_head *expected,
                                   tagged_head desired)
{
    uintptr_t observed_pointer, old_pointer = (uintptr_t)expected->ptr;
    uintptr_t new_pointer = (uintptr_t)desired.ptr;
    uint64_t observed_epoch, old_epoch = expected->epoch, new_epoch = desired.epoch;
    uint32_t status;

    __asm__ volatile(
        "1:\n\t"
        "ldaxp %0, %1, [%3]\n\t"
        "cmp %0, %4\n\t"
        "b.ne 2f\n\t"
        "cmp %1, %5\n\t"
        "b.ne 2f\n\t"
        "stlxp %w2, %6, %7, [%3]\n\t"
        "cbnz %w2, 1b\n\t"
        "b 3f\n"
        "2:\n\t"
        "mov %w2, #1\n\t"
        "clrex\n"
        "3:"
        : "=&r"(observed_pointer), "=&r"(observed_epoch), "=&r"(status)
        : "r"(head), "r"(old_pointer), "r"(old_epoch),
          "r"(new_pointer), "r"(new_epoch)
        : "cc", "memory");
    if (status) {
        *expected = (tagged_head){ .ptr = (lockless_node *)observed_pointer,
                                   .epoch = observed_epoch };
        return 0;
    }
    return 1;
}

void lockless_stack_init(lockless_stack *stack)
{
    tagged_store(&stack->head, (tagged_head){ .ptr = NULL, .epoch = 0 });
}

tagged_head lockless_stack_head(const lockless_stack *stack)
{
    return tagged_load(&stack->head);
}

void lockless_stack_push(lockless_stack *stack, lockless_node *node)
{
    tagged_head expected = tagged_load(&stack->head), desired;
    do {
        node->next = expected.ptr;
        desired = (tagged_head){ .ptr = node, .epoch = expected.epoch + 1 };
    } while (!lockless_head_compare_exchange(&stack->head, &expected, desired));
}

lockless_node *lockless_stack_pop(lockless_stack *stack)
{
    tagged_head expected = tagged_load(&stack->head), desired;
    for (;;) {
        if (!expected.ptr)
            return NULL;
        lockless_node *next = expected.ptr->next;
        desired = (tagged_head){ .ptr = next, .epoch = expected.epoch + 1 };
        if (lockless_head_compare_exchange(&stack->head, &expected, desired))
            return expected.ptr;
    }
}
