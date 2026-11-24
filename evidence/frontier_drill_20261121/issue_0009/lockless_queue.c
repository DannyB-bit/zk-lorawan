#define _GNU_SOURCE
#include <inttypes.h>
#include <pthread.h>
#include <sched.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct node {
    struct node *next;
    unsigned id;
} node_t;

typedef struct {
    node_t *ptr;
    uint64_t tag;
} tagged_head_t;

static _Atomic(node_t *) legacy_head;
static tagged_head_t fixed_head __attribute__((aligned(16)));
static _Atomic int legacy_stage, fixed_stage;
static node_t deterministic_nodes[3];

/* The legacy path deliberately models the ABA defect as a negative control. */
static void *legacy_victim(void *unused) {
    (void)unused;
    node_t *expected = atomic_load_explicit(&legacy_head, memory_order_acquire);
    node_t *next = expected->next;
    atomic_store_explicit(&legacy_stage, 1, memory_order_release);
    while (atomic_load_explicit(&legacy_stage, memory_order_acquire) < 2)
        sched_yield();
    if (!atomic_compare_exchange_weak_explicit(&legacy_head, &expected, next,
            memory_order_acq_rel, memory_order_acquire)) {
        fprintf(stderr, "legacy control unexpectedly rejected ABA\n");
        return (void *)(uintptr_t)1;
    }
    return NULL;
}

static int run_legacy(void) {
    node_t *a = &deterministic_nodes[0], *b = &deterministic_nodes[1], *c = &deterministic_nodes[2];
    a->id = 0; b->id = 1; c->id = 2; a->next = b; b->next = c; c->next = NULL;
    atomic_store(&legacy_head, a); atomic_store(&legacy_stage, 0);
    pthread_t thread;
    if (pthread_create(&thread, NULL, legacy_victim, NULL)) return 90;
    while (atomic_load_explicit(&legacy_stage, memory_order_acquire) < 1) sched_yield();
    /* Other activity: pop A, pop B, then recycle A at the head: A->C. */
    atomic_store(&legacy_head, b);
    atomic_store(&legacy_head, c);
    atomic_store(&legacy_head, a);
    atomic_store_explicit(&legacy_stage, 2, memory_order_release);
    void *rc = NULL;
    pthread_join(thread, &rc);
    if (rc) return 91;
    node_t *head = atomic_load(&legacy_head);
    printf("LEGACY_INTERLEAVING=A_B_A LEGACY_FINAL_HEAD=%c EXPECTED_HEAD=C\n",
           head == a ? 'A' : head == b ? 'B' : head == c ? 'C' : '?');
    if (head != b) {
        puts("LEGACY_ABA_NOT_REPRODUCED");
        return 4;
    }
    puts("LEGACY_ABA_REPRODUCED=YES: already-popped B resurrected as head");
    return 2;
}

#if !defined(__aarch64__)
#error "This physical regression requires AArch64 LDAXP/STLXP"
#endif

static tagged_head_t tagged_load(void) {
    tagged_head_t observed;
    __asm__ volatile("ldaxp %0, %1, [%2]\n\tclrex"
                     : "=&r"(observed.ptr), "=&r"(observed.tag)
                     : "r"(&fixed_head) : "memory");
    return observed;
}

static void tagged_store(tagged_head_t desired) {
    uint32_t status;
    do {
        tagged_head_t observed;
        __asm__ volatile("ldaxp %0, %1, [%2]"
                         : "=&r"(observed.ptr), "=&r"(observed.tag)
                         : "r"(&fixed_head) : "memory");
        __asm__ volatile("stlxp %w0, %2, %3, [%1]"
                         : "=&r"(status)
                         : "r"(&fixed_head), "r"(desired.ptr), "r"(desired.tag)
                         : "memory");
    } while (status != 0);
}

static bool tagged_cas(tagged_head_t *expected, tagged_head_t desired) {
    for (;;) {
        tagged_head_t observed;
        __asm__ volatile("ldaxp %0, %1, [%2]"
                         : "=&r"(observed.ptr), "=&r"(observed.tag)
                         : "r"(&fixed_head) : "memory");
        if (observed.ptr != expected->ptr || observed.tag != expected->tag) {
            __asm__ volatile("clrex" ::: "memory");
            *expected = observed;
            return false;
        }
        uint32_t status;
        __asm__ volatile("stlxp %w0, %2, %3, [%1]"
                         : "=&r"(status)
                         : "r"(&fixed_head), "r"(desired.ptr), "r"(desired.tag)
                         : "memory");
        if (status == 0) return true;
        /* Exclusive-store contention: retry against the same expected value. */
    }
}

static void tagged_push(node_t *n) {
    tagged_head_t expected = tagged_load();
    tagged_head_t desired;
    do {
        n->next = expected.ptr;
        desired = (tagged_head_t){.ptr = n, .tag = expected.tag + UINT64_C(1)};
    } while (!tagged_cas(&expected, desired));
}

static node_t *tagged_pop(void) {
    tagged_head_t expected = tagged_load();
    tagged_head_t desired;
    do {
        if (!expected.ptr) return NULL;
        desired = (tagged_head_t){.ptr = expected.ptr->next, .tag = expected.tag + UINT64_C(1)};
    } while (!tagged_cas(&expected, desired));
    return expected.ptr;
}

static void *fixed_victim(void *unused) {
    (void)unused;
    tagged_head_t expected = tagged_load();
    tagged_head_t desired = {.ptr = expected.ptr->next, .tag = expected.tag + UINT64_C(1)};
    atomic_store_explicit(&fixed_stage, 1, memory_order_release);
    while (atomic_load_explicit(&fixed_stage, memory_order_acquire) < 2)
        sched_yield();
    /* Same recycled address, different epoch: first CAS must fail, then retry. */
    bool first = tagged_cas(&expected, desired);
    if (first) {
        fprintf(stderr, "fixed tagged CAS incorrectly accepted ABA\n");
        return (void *)(uintptr_t)1;
    }
    node_t *popped = tagged_pop();
    return popped == &deterministic_nodes[0] ? NULL : (void *)(uintptr_t)2;
}

static int run_fixed_deterministic(void) {
    if (sizeof(tagged_head_t) != 16 || sizeof(uint64_t) * 8 != 64) return 92;
    printf("TAGGED_HEAD_BYTES=%zu TAG_WIDTH_BITS=64 TAGGED_LOCK_FREE=1 TAGGED_CAS_ISA=LDAXP_STLXP\n",
           sizeof(tagged_head_t));
    node_t *a = &deterministic_nodes[0], *b = &deterministic_nodes[1], *c = &deterministic_nodes[2];
    a->id = 0; b->id = 1; c->id = 2; a->next = b; b->next = c; c->next = NULL;
    tagged_head_t initial = {.ptr = a, .tag = 0};
    tagged_store(initial);
    atomic_store(&fixed_stage, 0);
    pthread_t thread;
    if (pthread_create(&thread, NULL, fixed_victim, NULL)) return 90;
    while (atomic_load_explicit(&fixed_stage, memory_order_acquire) < 1) sched_yield();
    if (tagged_pop() != a || tagged_pop() != b) return 94;
    tagged_push(a);
    atomic_store_explicit(&fixed_stage, 2, memory_order_release);
    void *rc = NULL;
    pthread_join(thread, &rc);
    if (rc) return 91;
    tagged_head_t head = tagged_load();
    printf("FIXED_INTERLEAVING=A_B_A FIXED_FINAL_HEAD=%c FINAL_EPOCH=%" PRIu64 "\n",
           head.ptr == a ? 'A' : head.ptr == b ? 'B' : head.ptr == c ? 'C' : '?', head.tag);
    if (head.ptr != c || head.tag != 4) return 95;
    puts("TAGGED_PTR_ABA_PASS=YES: recycled address rejected by epoch; retry popped A and preserved C");
    return 0;
}

#define STRESS_NODES 128
#define STRESS_THREADS 4
#define STRESS_ITERS 50000
static node_t stress_nodes[STRESS_NODES];
static _Atomic unsigned long stress_pops, stress_pushes;

static void *stress_worker(void *unused) {
    (void)unused;
    for (unsigned i = 0; i < STRESS_ITERS; ++i) {
        node_t *n = tagged_pop();
        if (n) {
            atomic_fetch_add_explicit(&stress_pops, 1, memory_order_relaxed);
            tagged_push(n);
            atomic_fetch_add_explicit(&stress_pushes, 1, memory_order_relaxed);
        } else {
            sched_yield();
        }
    }
    return NULL;
}

static int run_stress(void) {
    for (unsigned i = 0; i < STRESS_NODES; ++i) {
        stress_nodes[i].id = i;
        stress_nodes[i].next = i + 1 < STRESS_NODES ? &stress_nodes[i + 1] : NULL;
    }
    tagged_head_t initial = {.ptr = &stress_nodes[0], .tag = 0};
    tagged_store(initial);
    atomic_store(&stress_pops, 0); atomic_store(&stress_pushes, 0);
    pthread_t threads[STRESS_THREADS];
    for (unsigned i = 0; i < STRESS_THREADS; ++i)
        if (pthread_create(&threads[i], NULL, stress_worker, NULL)) return 90;
    for (unsigned i = 0; i < STRESS_THREADS; ++i) pthread_join(threads[i], NULL);
    bool seen[STRESS_NODES] = {false};
    unsigned count = 0;
    node_t *n;
    while ((n = tagged_pop()) != NULL) {
        if (n < stress_nodes || n >= stress_nodes + STRESS_NODES || seen[n->id]) {
            printf("STRESS_CORRUPTION=YES BAD_ID=%u\n", n->id);
            return 2;
        }
        seen[n->id] = true;
        ++count;
    }
    unsigned long pops = atomic_load(&stress_pops), pushes = atomic_load(&stress_pushes);
    printf("STRESS_THREADS=%d STRESS_ITERATIONS_PER_THREAD=%d POPS=%lu PUSHES=%lu UNIQUE_FINAL=%u FINAL_EPOCH=%" PRIu64 "\n",
           STRESS_THREADS, STRESS_ITERS, pops, pushes, count, tagged_load().tag);
    if (count != STRESS_NODES || pops != pushes || pops == 0) return 3;
    for (unsigned i = 0; i < STRESS_NODES; ++i) if (!seen[i]) return 4;
    printf("STRESS_EXACTLY_ONCE=%u STRESS_PASS=YES\n", count);
    return 0;
}

int main(int argc, char **argv) {
    if (argc != 2) {
        fprintf(stderr, "usage: %s legacy|fixed|stress\n", argv[0]);
        return 64;
    }
    if (!strcmp(argv[1], "legacy")) return run_legacy();
    if (!strcmp(argv[1], "fixed")) return run_fixed_deterministic();
    if (!strcmp(argv[1], "stress")) return run_stress();
    return 64;
}
