#include "lockless_queue.h"

void lq_init(lq_queue_t *q, lq_node_t *initial) {
    lq_tagged_t h = { .ptr = initial, .epoch = 0 };
    atomic_store_explicit(&q->head, h, memory_order_release);
}

void lq_push(lq_queue_t *q, lq_node_t *node) {
    lq_tagged_t old = atomic_load_explicit(&q->head, memory_order_acquire);
    lq_tagged_t next;
    do {
        node->next = old.ptr;
        /* Every successful head transition gets a new 64-bit generation. */
        next = (lq_tagged_t){ .ptr = node, .epoch = old.epoch + 1 };
    } while (!atomic_compare_exchange_weak_explicit(
        &q->head, &old, next, memory_order_acq_rel, memory_order_acquire));
}

bool lq_pop(lq_queue_t *q, lq_node_t **out) {
    lq_tagged_t old = atomic_load_explicit(&q->head, memory_order_acquire);
    for (;;) {
        if (old.ptr == NULL)
            return false;
        lq_tagged_t next = {
            .ptr = old.ptr->next,
            .epoch = old.epoch + 1
        };
        if (atomic_compare_exchange_weak_explicit(
                &q->head, &old, next,
                memory_order_acq_rel, memory_order_acquire)) {
            *out = old.ptr;
            return true;
        }
        /* CAS failure reloads old, including its current epoch. */
    }
}
