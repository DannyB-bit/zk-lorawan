// FRONTIER-GH-0017: native aarch64 tagged-pointer ABA regression model.
// This is not presented as an upstream CPython source patch.
#define _GNU_SOURCE
#include <assert.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

typedef struct node {
    struct node *next;
    unsigned value;
} node_t;

typedef struct __attribute__((aligned(16))) {
    node_t *ptr;
    uint64_t epoch;
} tagged_head_t;

typedef struct {
    tagged_head_t head;
    pthread_mutex_t gate_lock;
    pthread_cond_t gate_cv;
    int armed;
    int release;
    int stale_cas_rejected;
    node_t *worker_result;
} aba_fixture_t;

// ARMv8 exclusive doubleword-pair load/store gives a real lock-free 128-bit
// CAS on Cortex-A72: pointer + full 64-bit epoch are one atomic primitive.
static inline tagged_head_t atomic_load_tagged(tagged_head_t *head) {
    uint64_t ptr, epoch;
    __asm__ volatile(
        "ldaxp %x0, %x1, %2\n\t"
        "clrex"
        : "=&r"(ptr), "=&r"(epoch), "+Q"(*head)
        :
        : "memory");
    tagged_head_t out = {(node_t *)(uintptr_t)ptr, epoch};
    return out;
}

extern int atomic_cas_tagged_asm(tagged_head_t *head,
                                 tagged_head_t *expected,
                                 const tagged_head_t *desired);

static inline bool atomic_cas_tagged(tagged_head_t *head,
                                     tagged_head_t *expected,
                                     tagged_head_t desired) {
    return atomic_cas_tagged_asm(head, expected, &desired) == 1;
}

static void tagged_push(tagged_head_t *head, node_t *n) {
    tagged_head_t old = atomic_load_tagged(head);
    for (;;) {
        tagged_head_t desired = {n, old.epoch + 1};
        n->next = old.ptr;
        if (atomic_cas_tagged(head, &old, desired)) return;
    }
}

static void aba_gate_wait(aba_fixture_t *f) {
    pthread_mutex_lock(&f->gate_lock);
    f->armed = 1;
    pthread_cond_broadcast(&f->gate_cv);
    while (!f->release) pthread_cond_wait(&f->gate_cv, &f->gate_lock);
    pthread_mutex_unlock(&f->gate_lock);
}

static node_t *tagged_pop_gated(aba_fixture_t *f, bool use_epoch) {
    tagged_head_t old = atomic_load_tagged(&f->head);
    for (;;) {
        if (!old.ptr) return NULL;
        node_t *next = old.ptr->next;
        aba_gate_wait(f);
        // Legacy ignores the epoch; fixed CAS compares pointer AND epoch and
        // increments the generation on every successful head mutation.
        tagged_head_t desired = {next, use_epoch ? old.epoch + 1 : old.epoch};
        tagged_head_t expected = old;
        if (!use_epoch) expected.epoch = atomic_load_tagged(&f->head).epoch;
        if (atomic_cas_tagged(&f->head, &expected, desired)) return old.ptr;
        if (use_epoch) f->stale_cas_rejected++;
        old = expected;
    }
}

static void *aba_worker(void *arg, bool use_epoch) {
    aba_fixture_t *f = arg;
    f->worker_result = tagged_pop_gated(f, use_epoch);
    return NULL;
}

static void *legacy_worker(void *arg) { return aba_worker(arg, false); }
static void *fixed_worker(void *arg) { return aba_worker(arg, true); }

static void release_aba_worker(aba_fixture_t *f, pthread_t thread) {
    pthread_mutex_lock(&f->gate_lock);
    while (!f->armed) pthread_cond_wait(&f->gate_cv, &f->gate_lock);
    pthread_mutex_unlock(&f->gate_lock);
    // Recycle A after removing A and B while the worker holds A,B.
    node_t *a = f->head.ptr;
    tagged_head_t h = atomic_load_tagged(&f->head);
    tagged_head_t d = {a->next, h.epoch + 1};
    assert(atomic_cas_tagged(&f->head, &h, d));
    node_t *b = f->head.ptr;
    h = atomic_load_tagged(&f->head);
    d = (tagged_head_t){b->next, h.epoch + 1};
    assert(atomic_cas_tagged(&f->head, &h, d));
    tagged_push(&f->head, a);
    pthread_mutex_lock(&f->gate_lock);
    f->release = 1;
    pthread_cond_broadcast(&f->gate_cv);
    pthread_mutex_unlock(&f->gate_lock);
    pthread_join(thread, NULL);
    (void)b;
}

static int run_aba(bool fixed) {
    node_t a = {0}, b = {0};
    aba_fixture_t f;
    memset(&f, 0, sizeof(f));
    pthread_mutex_init(&f.gate_lock, NULL);
    pthread_cond_init(&f.gate_cv, NULL);
    tagged_push(&f.head, &b);
    tagged_push(&f.head, &a);
    pthread_t thread;
    assert(!pthread_create(&thread, NULL, fixed ? fixed_worker : legacy_worker, &f));
    release_aba_worker(&f, thread);
    bool legacy_aba = !fixed && f.worker_result == &a && f.head.ptr == &b;
    bool fixed_safe = fixed && f.worker_result == &a && f.head.ptr == NULL &&
                      f.stale_cas_rejected >= 1;
    printf("mode=%s worker=%s head=%s stale_cas_rejected=%d\n",
           fixed ? "fixed" : "legacy", f.worker_result == &a ? "A" : "other",
           f.head.ptr == &b ? "B(dangling)" : f.head.ptr == NULL ? "NULL" : "other",
           f.stale_cas_rejected);
    pthread_cond_destroy(&f.gate_cv);
    pthread_mutex_destroy(&f.gate_lock);
    if (fixed) {
        printf("TAGGED_EPOCH_ABA_REJECTED=%s\n", fixed_safe ? "YES" : "NO");
        return fixed_safe ? 0 : 2;
    }
    printf("LEGACY_ABA_REPRODUCED=%s\n", legacy_aba ? "YES" : "NO");
    return legacy_aba ? 0 : 3;
}

#define PRODUCERS 4
#define PER_PRODUCER 10000
#define TOTAL (PRODUCERS * PER_PRODUCER)
static tagged_head_t stress_head;
static node_t stress_nodes[TOTAL];
static atomic_uchar seen[TOTAL];
static atomic_int consumed;

static void *producer(void *arg) {
    unsigned p = (unsigned)(uintptr_t)arg;
    for (unsigned i = 0; i < PER_PRODUCER; i++) {
        unsigned id = p * PER_PRODUCER + i;
        stress_nodes[id].value = id;
        tagged_push(&stress_head, &stress_nodes[id]);
    }
    return NULL;
}

static void *consumer(void *arg) {
    (void)arg;
    for (;;) {
        tagged_head_t old = atomic_load_tagged(&stress_head);
        if (!old.ptr) {
            if (atomic_load_explicit(&consumed, memory_order_relaxed) == TOTAL) return NULL;
            sched_yield();
            continue;
        }
        tagged_head_t desired = {old.ptr->next, old.epoch + 1};
        if (!atomic_cas_tagged(&stress_head, &old, desired)) continue;
        unsigned id = old.ptr->value;
        if (id >= TOTAL || atomic_exchange_explicit(&seen[id], 1, memory_order_relaxed)) {
            fprintf(stderr, "duplicate/corrupt node id=%u\n", id);
            abort();
        }
        atomic_fetch_add_explicit(&consumed, 1, memory_order_relaxed);
    }
}

static int run_stress(void) {
    pthread_t producers[PRODUCERS], consumers[PRODUCERS];
    for (uintptr_t i = 0; i < PRODUCERS; i++)
        assert(!pthread_create(&producers[i], NULL, producer, (void *)i));
    for (unsigned i = 0; i < PRODUCERS; i++)
        assert(!pthread_create(&consumers[i], NULL, consumer, NULL));
    for (unsigned i = 0; i < PRODUCERS; i++) pthread_join(producers[i], NULL);
    for (unsigned i = 0; i < PRODUCERS; i++) pthread_join(consumers[i], NULL);
    int count = atomic_load(&consumed);
    bool pass = count == TOTAL && stress_head.ptr == NULL;
    for (unsigned i = 0; i < TOTAL; i++) pass &= atomic_load(&seen[i]) == 1;
    printf("stress_produced=%d stress_consumed=%d final_epoch=%llu duplicates=0\n",
           TOTAL, count, (unsigned long long)stress_head.epoch);
    printf("TAGGED_STRESS_PASS=%s\n", pass ? "YES" : "NO");
    return pass ? 0 : 4;
}

int main(int argc, char **argv) {
    const char *mode = argc > 1 ? argv[1] : "all";
    if (!strcmp(mode, "legacy")) return run_aba(false);
    if (!strcmp(mode, "fixed")) {
        int rc = run_aba(true);
        if (rc) return rc;
        return run_stress();
    }
    if (!strcmp(mode, "all")) {
        int a = run_aba(false), b = run_aba(true), c = b ? b : run_stress();
        return a || b || c;
    }
    fprintf(stderr, "usage: %s [legacy|fixed|all]\n", argv[0]);
    return 64;
}
