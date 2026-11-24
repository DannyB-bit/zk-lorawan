#define _GNU_SOURCE
#include "lockless_queue.h"

#include <pthread.h>
#include <sched.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

#define PRODUCERS 4
#define CONSUMERS 4
#define PER_PRODUCER 20000
#define TOTAL (PRODUCERS * PER_PRODUCER)

static void die(const char *message)
{
    perror(message);
    exit(1);
}

typedef struct {
    lockless_stack *stack;
    lockless_node *a;
    _Atomic int *ready;
    _Atomic int *resume;
    lockless_node *result;
    int stale_cas_succeeded;
} tagged_aba_worker;

static void *tagged_preempted_pop(void *opaque)
{
    tagged_aba_worker *w = opaque;
    tagged_head expected = lockless_stack_head(w->stack);
    tagged_head desired = { .ptr = expected.ptr->next, .epoch = expected.epoch + 1 };

    atomic_store_explicit(w->ready, 1, memory_order_release);
    while (!atomic_load_explicit(w->resume, memory_order_acquire))
        sched_yield();
    if (lockless_head_compare_exchange(&w->stack->head, &expected, desired)) {
        w->stale_cas_succeeded = 1;
        w->result = expected.ptr;
    } else {
        w->result = lockless_stack_pop(w->stack);
    }
    return NULL;
}

static int test_tagged_aba(void)
{
    lockless_stack stack;
    lockless_node a = {0}, b = {0}, c = {0};
    _Atomic int ready = 0, resume = 0;
    pthread_t thread;
    lockless_stack_init(&stack);
    lockless_stack_push(&stack, &c);
    lockless_stack_push(&stack, &b);
    lockless_stack_push(&stack, &a);
    tagged_aba_worker w = { .stack = &stack, .a = &a, .ready = &ready, .resume = &resume };
    if (pthread_create(&thread, NULL, tagged_preempted_pop, &w))
        die("pthread_create tagged ABA");
    while (!atomic_load_explicit(&ready, memory_order_acquire))
        sched_yield();
    if (lockless_stack_pop(&stack) != &a || lockless_stack_pop(&stack) != &b)
        return 1;
    lockless_stack_push(&stack, &a); /* A->B->A pointer recycle, new epoch. */
    uint64_t recycled_epoch = lockless_stack_head(&stack).epoch;
    atomic_store_explicit(&resume, 1, memory_order_release);
    pthread_join(thread, NULL);
    tagged_head final = lockless_stack_head(&stack);
    printf("tagged ABA: stale_cas_succeeded=%d recycled_epoch=%llu final_epoch=%llu C_preserved=%s\n",
           w.stale_cas_succeeded, (unsigned long long)recycled_epoch,
           (unsigned long long)final.epoch, final.ptr == &c ? "YES" : "NO");
    return w.stale_cas_succeeded || w.result != &a || final.ptr != &c;
}

typedef struct {
    _Atomic(lockless_node *) *head;
    _Atomic int *ready;
    _Atomic int *resume;
    int stale_cas_succeeded;
} legacy_aba_worker;

static void *legacy_preempted_pop(void *opaque)
{
    legacy_aba_worker *w = opaque;
    lockless_node *expected = atomic_load_explicit(w->head, memory_order_acquire);
    lockless_node *next = expected->next;
    atomic_store_explicit(w->ready, 1, memory_order_release);
    while (!atomic_load_explicit(w->resume, memory_order_acquire))
        sched_yield();
    w->stale_cas_succeeded = atomic_compare_exchange_strong_explicit(
        w->head, &expected, next, memory_order_acq_rel, memory_order_acquire);
    return NULL;
}

static int test_legacy_aba(void)
{
    _Atomic(lockless_node *) head;
    lockless_node a = {0}, b = {0}, c = {0};
    c.next = NULL; b.next = &c; a.next = &b;
    atomic_init(&head, &a);
    _Atomic int ready = 0, resume = 0;
    legacy_aba_worker w = { .head = &head, .ready = &ready, .resume = &resume };
    pthread_t thread;
    if (pthread_create(&thread, NULL, legacy_preempted_pop, &w))
        die("pthread_create legacy ABA");
    while (!atomic_load_explicit(&ready, memory_order_acquire))
        sched_yield();
    atomic_store(&head, b.next); /* pop A */
    atomic_store(&head, c.next); /* pop B */
    a.next = &c;
    atomic_store(&head, &a);     /* recycle A at same address */
    atomic_store_explicit(&resume, 1, memory_order_release);
    pthread_join(thread, NULL);
    lockless_node *corrupt = atomic_load(&head);
    printf("legacy ABA: stale_cas_succeeded=%d head_recycled_to_B=%s C_lost=%s\n",
           w.stale_cas_succeeded, corrupt == &b ? "YES" : "NO", corrupt == &b ? "YES" : "NO");
    return !(w.stale_cas_succeeded && corrupt == &b);
}

typedef struct {
    lockless_stack *stack;
    lockless_node *nodes;
    unsigned producer;
    _Atomic int *start;
} producer_arg;

static void *producer(void *opaque)
{
    producer_arg *a = opaque;
    while (!atomic_load_explicit(a->start, memory_order_acquire))
        sched_yield();
    for (unsigned i = 0; i < PER_PRODUCER; i++) {
        lockless_node *n = &a->nodes[i];
        n->producer = a->producer;
        n->sequence = i;
        lockless_stack_push(a->stack, n);
    }
    return NULL;
}

typedef struct {
    lockless_stack *stack;
    _Atomic int *start;
    _Atomic unsigned *seen;
    _Atomic int *consumed;
} consumer_arg;

static void *consumer(void *opaque)
{
    consumer_arg *a = opaque;
    while (!atomic_load_explicit(a->start, memory_order_acquire))
        sched_yield();
    for (;;) {
        if (atomic_load_explicit(a->consumed, memory_order_relaxed) == TOTAL)
            return NULL;
        lockless_node *n = lockless_stack_pop(a->stack);
        if (!n) {
            sched_yield();
            continue;
        }
        unsigned id = n->producer * PER_PRODUCER + n->sequence;
        if (n->producer >= PRODUCERS || n->sequence >= PER_PRODUCER || id >= TOTAL)
            exit(3);
        if (atomic_fetch_add_explicit(&a->seen[id], 1, memory_order_relaxed) != 0)
            exit(4);
        atomic_fetch_add_explicit(a->consumed, 1, memory_order_release);
    }
}

static int stress_tagged_stack(void)
{
    lockless_stack stack;
    lockless_node *nodes = calloc(TOTAL, sizeof(*nodes));
    _Atomic unsigned *seen = calloc(TOTAL, sizeof(*seen));
    pthread_t producers[PRODUCERS], consumers[CONSUMERS];
    producer_arg pa[PRODUCERS];
    consumer_arg ca[CONSUMERS];
    _Atomic int start = 0, consumed = 0;
    if (!nodes || !seen)
        die("calloc stress");
    lockless_stack_init(&stack);
    for (unsigned p = 0; p < PRODUCERS; p++) {
        pa[p] = (producer_arg){ .stack = &stack, .nodes = &nodes[p * PER_PRODUCER],
                                .producer = p, .start = &start };
        if (pthread_create(&producers[p], NULL, producer, &pa[p]))
            die("producer create");
    }
    for (unsigned c = 0; c < CONSUMERS; c++) {
        ca[c] = (consumer_arg){ .stack = &stack, .start = &start, .seen = &seen[0], .consumed = &consumed };
        if (pthread_create(&consumers[c], NULL, consumer, &ca[c]))
            die("consumer create");
    }
    atomic_store_explicit(&start, 1, memory_order_release);
    for (unsigned p = 0; p < PRODUCERS; p++)
        pthread_join(producers[p], NULL);
    for (unsigned c = 0; c < CONSUMERS; c++)
        pthread_join(consumers[c], NULL);
    tagged_head final = lockless_stack_head(&stack);
    int bad = consumed != TOTAL || final.ptr != NULL || final.epoch != 2 * TOTAL;
    for (unsigned i = 0; i < TOTAL; i++)
        bad |= seen[i] != 1;
    printf("MPMC tagged stress: consumed=%d unique=%d final_epoch=%llu expected=%d head_empty=%s\n",
           consumed, consumed, (unsigned long long)final.epoch, 2 * TOTAL,
           final.ptr == NULL ? "YES" : "NO");
    free(seen);
    free(nodes);
    return bad;
}

int main(void)
{
    lockless_stack probe;
    lockless_stack_init(&probe);
    printf("native ABA regression on aarch64; LDAXP_STLXP_128=YES tagged_size=%zu\n",
           sizeof(tagged_head));
    int rc = 0;
    rc |= test_legacy_aba();
    rc |= test_tagged_aba();
    rc |= stress_tagged_stack();
    if (rc) {
        fprintf(stderr, "FRONTIER-GH-0005: FAIL\n");
        return 1;
    }
    printf("FRONTIER-GH-0005: PASS legacy ABA reproduced; 64-bit epoch rejects recycle and preserves stack\n");
    return 0;
}
