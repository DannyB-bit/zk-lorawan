#include "lockless_queue.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

int main(void) {
    lq_node_t a = {.value = 11}, b = {.value = 22}, c = {.value = 33}, *out = NULL;
    lq_queue_t q;
    lq_init(&q, &a);
    a.next = &b; b.next = NULL;

    /* Deterministic A -> B -> A address recycle. */
    lq_tagged_t stale = atomic_load_explicit(&q.head, memory_order_acquire);
    assert(stale.ptr == &a && stale.epoch == 0);
    assert(lq_pop(&q, &out) && out == &a);       /* head B, epoch 1 */
    lq_push(&q, &a);                             /* head A, epoch 2 */
    lq_tagged_t now = atomic_load_explicit(&q.head, memory_order_acquire);
    assert(now.ptr == stale.ptr && now.epoch == 2);

    /* Pointer-only CAS accepts the stale ABA state: reproduce the old bug. */
    _Atomic(lq_node_t *) legacy = &a;
    lq_node_t *legacy_stale = &a;
    assert(atomic_compare_exchange_strong(&legacy, &legacy_stale, &b));

    /* Tagged CAS rejects exactly that stale state. */
    lq_tagged_t desired = {.ptr = &c, .epoch = 1};
    bool swapped = atomic_compare_exchange_strong_explicit(
        &q.head, &stale, desired, memory_order_acq_rel, memory_order_acquire);
    assert(!swapped);
    assert(stale.ptr == &a && stale.epoch == 2);

    /* Baseline: rejected CAS did not mutate the stack; normal LIFO still works. */
    assert(lq_pop(&q, &out) && out == &a);
    assert(lq_pop(&q, &out) && out == &b);
    assert(!lq_pop(&q, &out));
    lq_push(&q, &c);
    assert(lq_pop(&q, &out) && out == &c && out->value == 33);
    printf("PASS: legacy ABA reproduced; 128-bit ptr+64-bit-epoch CAS rejected stale generation; LIFO baseline passed\n");
    return 0;
}
