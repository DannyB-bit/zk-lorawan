// FRONTIER-GH-0019 native regression model; not an upstream CPython patch.
// Models interpreter-list retirement versus daemon-thread tstate acquisition.
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

typedef struct {
    _Atomic int refs;
    _Atomic int retired;
    _Atomic int freed;
    _Atomic int phase;
    int observed_refs_after_retire;
} TState;

static pthread_mutex_t head_mutex = PTHREAD_MUTEX_INITIALIZER;

static void *legacy_deleter(void *arg) {
    TState *t = arg;
    while (atomic_load_explicit(&t->phase, memory_order_acquire) != 1) sched_yield();
    // Legacy defect: retire without head_mutex or a reference-lifetime barrier.
    atomic_store_explicit(&t->retired, 1, memory_order_release);
    atomic_store_explicit(&t->refs, 0, memory_order_release);
    atomic_store_explicit(&t->freed, 1, memory_order_release);
    atomic_store_explicit(&t->phase, 2, memory_order_release);
    return NULL;
}

static void *legacy_saver(void *arg) {
    TState *t = arg;
    // PyEval_SaveThread-like daemon acquisition has read the old tstate.
    atomic_store_explicit(&t->phase, 1, memory_order_release);
    while (atomic_load_explicit(&t->phase, memory_order_acquire) != 2) sched_yield();
    t->observed_refs_after_retire = atomic_fetch_add_explicit(&t->refs, 1, memory_order_acq_rel);
    return NULL;
}

static int legacy(void) {
    TState t = { .refs = 1 };
    pthread_t a, b;
    if (pthread_create(&a, NULL, legacy_deleter, &t) || pthread_create(&b, NULL, legacy_saver, &t)) return 2;
    pthread_join(a, NULL); pthread_join(b, NULL);
    int reproduced = atomic_load(&t.freed) && t.observed_refs_after_retire == 0 && atomic_load(&t.refs) == 1;
    printf("LEGACY_TSTATE_RACE_REPRODUCED=%s retired=%d old_refs=%d refs_after_invalid_acquire=%d\n",
           reproduced ? "YES" : "NO", atomic_load(&t.retired), t.observed_refs_after_retire, atomic_load(&t.refs));
    return reproduced ? 0 : 1;
}

typedef struct {
    TState *t;
    _Atomic int start;
    _Atomic int acquired;
    _Atomic int rejected;
    _Atomic int freed_count;
} FixedShared;

static void *fixed_saver(void *arg) {
    FixedShared *s = arg;
    while (!atomic_load_explicit(&s->start, memory_order_acquire)) sched_yield();
    int acquired = 0;
    pthread_mutex_lock(&head_mutex);
    if (!atomic_load_explicit(&s->t->retired, memory_order_relaxed)) {
        // List lock validates membership before atomic daemon-reference acquire.
        atomic_fetch_add_explicit(&s->t->refs, 1, memory_order_acq_rel);
        atomic_fetch_add_explicit(&s->acquired, 1, memory_order_relaxed);
        acquired = 1;
    } else {
        atomic_fetch_add_explicit(&s->rejected, 1, memory_order_relaxed);
    }
    pthread_mutex_unlock(&head_mutex);
    if (acquired) atomic_fetch_sub_explicit(&s->t->refs, 1, memory_order_acq_rel);
    return NULL;
}

static void *fixed_deleter(void *arg) {
    FixedShared *s = arg;
    while (!atomic_load_explicit(&s->start, memory_order_acquire)) sched_yield();
    pthread_mutex_lock(&head_mutex);
    atomic_store_explicit(&s->t->retired, 1, memory_order_relaxed);
    pthread_mutex_unlock(&head_mutex);
    atomic_fetch_sub_explicit(&s->t->refs, 1, memory_order_acq_rel); // drop interpreter-list ref
    while (atomic_load_explicit(&s->t->refs, memory_order_acquire) != 0) sched_yield();
    atomic_store_explicit(&s->t->freed, 1, memory_order_release);
    free(s->t); // real deallocation occurs only after every reference is gone
    atomic_fetch_add_explicit(&s->freed_count, 1, memory_order_relaxed);
    return NULL;
}

static int fixed(int iterations) {
    int total_acquired = 0, total_rejected = 0;
    for (int i = 0; i < iterations; ++i) {
        TState *t = calloc(1, sizeof(*t));
        if (!t) return 2;
        atomic_init(&t->refs, 1);
        FixedShared s = { .t = t };
        pthread_t a, b;
        if (pthread_create(&a, NULL, fixed_saver, &s) || pthread_create(&b, NULL, fixed_deleter, &s)) return 2;
        atomic_store_explicit(&s.start, 1, memory_order_release);
        pthread_join(a, NULL); pthread_join(b, NULL);
        if (atomic_load(&s.freed_count) != 1) return 1;
        total_acquired += atomic_load(&s.acquired);
        total_rejected += atomic_load(&s.rejected);
    }
    printf("FIXED_TSTATE_LIFETIME_PASS=YES iterations=%d acquired=%d rejected=%d freed=%d head_mutex=1 atomic_refcount=1\n",
           iterations, total_acquired, total_rejected, iterations);
    return 0;
}

int main(int argc, char **argv) {
    if (argc == 2 && strcmp(argv[1], "legacy") == 0) return legacy();
    if (argc == 2 && strcmp(argv[1], "fixed") == 0) return fixed(1);
    if (argc == 2 && strcmp(argv[1], "stress") == 0) return fixed(2000);
    fprintf(stderr, "usage: %s legacy|fixed|stress\n", argv[0]);
    return 2;
}
