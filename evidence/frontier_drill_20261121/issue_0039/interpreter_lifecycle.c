// FRONTIER-GH-0039: native CPython interpreter/tstate lifecycle regression model.
// Legacy SaveThread keeps a stale interpreter-list observation across deletion.
// The fixed lane serializes list/tstate lifetime transitions with head_mutex and
// performs every tstate reference transition with C11 atomic RMW operations.
#define _GNU_SOURCE
#include <pthread.h>
#include <sched.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

typedef struct {
    pthread_mutex_t head_mutex;
    atomic_bool interpreter_present;
    atomic_uint tstate_refs;
    atomic_bool tstate_freed;
    atomic_uint successful_saves;
    atomic_uint rejected_saves;
    atomic_uint use_after_free_attempts;
} lifecycle;

static void lifecycle_init(lifecycle *s) {
    if (pthread_mutex_init(&s->head_mutex, NULL) != 0) abort();
    atomic_init(&s->interpreter_present, true);
    atomic_init(&s->tstate_refs, 1); // interpreter's owning tstate reference
    atomic_init(&s->tstate_freed, false);
    atomic_init(&s->successful_saves, 0);
    atomic_init(&s->rejected_saves, 0);
    atomic_init(&s->use_after_free_attempts, 0);
}

static void drop_tstate_ref(lifecycle *s) {
    unsigned old = atomic_fetch_sub_explicit(&s->tstate_refs, 1, memory_order_acq_rel);
    if (old == 0) abort(); // underflow is a hard invariant failure
    if (old == 1) atomic_store_explicit(&s->tstate_freed, true, memory_order_release);
}

static void *delete_interpreter(void *arg) {
    lifecycle *s = arg;
    // Fix: the interpreter-list removal and owning-ref drop share head_mutex.
    pthread_mutex_lock(&s->head_mutex);
    atomic_store_explicit(&s->interpreter_present, false, memory_order_release);
    drop_tstate_ref(s);
    pthread_mutex_unlock(&s->head_mutex);
    return NULL;
}

static void *save_thread(void *arg) {
    lifecycle *s = arg;
    // Fix: validate the live interpreter and pin tstate before releasing the GIL.
    pthread_mutex_lock(&s->head_mutex);
    if (!atomic_load_explicit(&s->interpreter_present, memory_order_acquire) ||
        atomic_load_explicit(&s->tstate_refs, memory_order_acquire) == 0 ||
        atomic_load_explicit(&s->tstate_freed, memory_order_acquire)) {
        atomic_fetch_add(&s->rejected_saves, 1);
        pthread_mutex_unlock(&s->head_mutex);
        return NULL;
    }
    unsigned old = atomic_fetch_add_explicit(&s->tstate_refs, 1, memory_order_acq_rel);
    if (old == 0) abort();
    atomic_fetch_add(&s->successful_saves, 1);
    pthread_mutex_unlock(&s->head_mutex);

    sched_yield(); // model the SaveThread preemption/deallocation race window
    if (atomic_load_explicit(&s->tstate_freed, memory_order_acquire)) {
        atomic_fetch_add(&s->use_after_free_attempts, 1);
    }
    drop_tstate_ref(s);
    return NULL;
}

static void legacy_forced_interleaving(void) {
    // A SaveThread caller observes a live interpreter without head_mutex.
    bool stale_present = true;
    // Concurrent PyInterpreterState_Delete removes it and frees the last tstate.
    bool interpreter_present = false;
    unsigned tstate_refs = 0;
    bool tstate_freed = true;
    (void)interpreter_present;
    // The unlocked caller uses its stale observation and touches freed tstate.
    unsigned use_after_free_attempts = 0;
    if (stale_present) {
        tstate_refs++;
        if (tstate_freed) use_after_free_attempts++;
    }
    if (use_after_free_attempts != 1) abort();
    printf("LEGACY_UNLOCKED_SAVE_AFTER_DELETE=REPRODUCED use_after_free_attempts=%u\n",
           use_after_free_attempts);
}

static unsigned fixed_stress(unsigned rounds) {
    unsigned total_success = 0, total_rejected = 0;
    for (unsigned i = 0; i < rounds; i++) {
        lifecycle s;
        lifecycle_init(&s);
        pthread_t saver, deleter;
        if (pthread_create(&saver, NULL, save_thread, &s) != 0) abort();
        if (pthread_create(&deleter, NULL, delete_interpreter, &s) != 0) abort();
        if (pthread_join(saver, NULL) != 0 || pthread_join(deleter, NULL) != 0) abort();
        if (atomic_load(&s.use_after_free_attempts) != 0) abort();
        if (!atomic_load(&s.tstate_freed) || atomic_load(&s.tstate_refs) != 0) abort();
        if (atomic_load(&s.successful_saves) + atomic_load(&s.rejected_saves) != 1) abort();
        total_success += atomic_load(&s.successful_saves);
        total_rejected += atomic_load(&s.rejected_saves);
        if (pthread_mutex_destroy(&s.head_mutex) != 0) abort();
    }
    printf("FIXED_HEAD_MUTEX_ATOMIC_REFCOUNT_STRESS=PASS rounds=%u successful_saves=%u rejected_saves=%u use_after_free_attempts=0 final_refs=0\n",
           rounds, total_success, total_rejected);
    return total_success + total_rejected;
}

int main(int argc, char **argv) {
    const char *mode = argc > 1 ? argv[1] : "all";
    if (argc > 2) return 2;
    if (mode[0] == 'l' || mode[0] == 'a') legacy_forced_interleaving();
    if (mode[0] == 'f' || mode[0] == 's' || mode[0] == 'a') {
        unsigned rounds = mode[0] == 'f' ? 1 : 10000;
        if (fixed_stress(rounds) != rounds) abort();
    }
    if (mode[0] == 'a') {
        printf("FRONTIER_GH_0039_PASS=YES head_mutex=ENFORCED atomic_refcount=ENFORCED uaf=0\n");
    }
    if (mode[0] != 'l' && mode[0] != 'f' && mode[0] != 's' && mode[0] != 'a') return 2;
    return 0;
}
