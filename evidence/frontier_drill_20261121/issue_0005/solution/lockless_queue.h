#ifndef FRONTIER_LOCKLESS_QUEUE_H
#define FRONTIER_LOCKLESS_QUEUE_H

#include <stdatomic.h>
#include <stdint.h>

typedef struct lockless_node {
    struct lockless_node *next;
    unsigned producer;
    unsigned sequence;
} lockless_node;

/* 64-bit pointer + 64-bit epoch; 16-byte CAS rejects A->B->A pointer recycling. */
typedef struct __attribute__((aligned(16))) {
    lockless_node *ptr;
    uint64_t epoch;
} tagged_head;

typedef struct {
    tagged_head head;
} lockless_stack;

void lockless_stack_init(lockless_stack *stack);
void lockless_stack_push(lockless_stack *stack, lockless_node *node);
lockless_node *lockless_stack_pop(lockless_stack *stack);
tagged_head lockless_stack_head(const lockless_stack *stack);
/* Exposed for the deterministic stale-CAS regression; same native CAS primitive. */
int lockless_head_compare_exchange(tagged_head *head, tagged_head *expected,
                                   tagged_head desired);

#endif
