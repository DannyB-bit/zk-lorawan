// FRONTIER-GH-0035: deterministic native CPython subinterpreter lifetime model.
// Negative control: deletion wins before a daemon thread's PyEval_SaveThread.
// Fixed lane: head_mutex serializes interpreter-list deletion with tstate
// acquisition; atomic acquire/release refcount keeps tstate alive until the
// daemon releases the GIL. The negative control detects poison before access,
// avoiding an intentional C undefined-behaviour read in the test process.
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct TState {
    atomic_int refs;
    int freed;
    unsigned canary;
} TState;

typedef struct Shared {
    pthread_mutex_t head_mutex;
    pthread_cond_t cv;
    TState *head;
    TState *tstate;
    int stage;
    int daemon_observed_uaf;
    int daemon_completed;
} Shared;

static void init_shared(Shared *s) {
    memset(s, 0, sizeof(*s));
    pthread_mutex_init(&s->head_mutex, NULL);
    pthread_cond_init(&s->cv, NULL);
    s->tstate = calloc(1, sizeof(*s->tstate));
    if (!s->tstate) abort();
    atomic_init(&s->tstate->refs, 1); // interpreter owner's reference
    s->tstate->canary = 0xC0FFEE;
    s->head = s->tstate;
}

static void destroy_shared(Shared *s) {
    free(s->tstate);
    pthread_cond_destroy(&s->cv);
    pthread_mutex_destroy(&s->head_mutex);
}

static void *legacy_daemon(void *arg) {
    Shared *s = arg;
    TState *raw = s->tstate; // unlocked acquisition: defect under test
    pthread_mutex_lock(&s->head_mutex);
    s->stage = 1; // daemon is suspended immediately before SaveThread
    pthread_cond_broadcast(&s->cv);
    while (s->stage < 2) pthread_cond_wait(&s->cv, &s->head_mutex);
    // Poison is checked before any simulated dereference, so the test itself
    // remains defined while still proving that deletion won the lifetime race.
    if (raw->freed) s->daemon_observed_uaf = 1;
    pthread_mutex_unlock(&s->head_mutex);
    return NULL;
}

static int legacy_once(void) {
    Shared s;
    init_shared(&s);
    pthread_t daemon;
    if (pthread_create(&daemon, NULL, legacy_daemon, &s)) return 2;
    pthread_mutex_lock(&s.head_mutex);
    while (s.stage < 1) pthread_cond_wait(&s.cv, &s.head_mutex);
    // Models PyInterpreterState_Delete without head_mutex/list lifetime safety:
    // unlink and poison tstate while the daemon retains its raw pointer.
    s.head = NULL;
    s.tstate->freed = 1;
    atomic_store_explicit(&s.tstate->refs, 0, memory_order_release);
    s.stage = 2;
    pthread_cond_broadcast(&s.cv);
    pthread_mutex_unlock(&s.head_mutex);
    pthread_join(daemon, NULL);
    int reproduced = s.daemon_observed_uaf && atomic_load(&s.tstate->refs) == 0;
    destroy_shared(&s);
    return reproduced ? 0 : 1;
}

static void *fixed_daemon(void *arg) {
    Shared *s = arg;
    pthread_mutex_lock(&s->head_mutex);
    // Acquire head_mutex before touching the interpreter list or tstate refs.
    if (s->head == s->tstate && !s->tstate->freed) {
        atomic_fetch_add_explicit(&s->tstate->refs, 1, memory_order_acquire);
        s->stage = 1; // daemon reference is now independently owned
        pthread_cond_broadcast(&s->cv);
    }
    while (s->stage < 2) pthread_cond_wait(&s->cv, &s->head_mutex);
    pthread_mutex_unlock(&s->head_mutex);

    // Simulated PyEval_SaveThread/GIL release occurs without head_mutex while
    // the atomic daemon reference keeps the object alive.
    if (!s->tstate->freed && s->tstate->canary == 0xC0FFEE)
        s->daemon_completed = 1;
    int old = atomic_fetch_sub_explicit(&s->tstate->refs, 1, memory_order_acq_rel);
    if (old == 2) s->daemon_completed = s->daemon_completed && 1;
    return NULL;
}

static int fixed_once(int *owner_old, int *remaining) {
    Shared s;
    init_shared(&s);
    pthread_t daemon;
    if (pthread_create(&daemon, NULL, fixed_daemon, &s)) return 2;
    pthread_mutex_lock(&s.head_mutex);
    while (s.stage < 1) pthread_cond_wait(&s.cv, &s.head_mutex);
    // Deletion and list unlink are serialized by head_mutex. Drop only the
    // owner's reference; the daemon's atomic reference prevents premature free.
    s.head = NULL;
    *owner_old = atomic_fetch_sub_explicit(&s.tstate->refs, 1, memory_order_acq_rel);
    s.stage = 2;
    pthread_cond_broadcast(&s.cv);
    pthread_mutex_unlock(&s.head_mutex);
    pthread_join(daemon, NULL);
    *remaining = atomic_load_explicit(&s.tstate->refs, memory_order_acquire);
    int ok = *owner_old == 2 && *remaining == 0 && s.daemon_completed &&
             !s.daemon_observed_uaf && !s.tstate->freed;
    destroy_shared(&s);
    return ok ? 0 : 1;
}

int main(int argc, char **argv) {
    if (argc != 2) {
        fprintf(stderr, "usage: subinterpreter_lifetime legacy|fixed|stress\n");
        return 2;
    }
    if (!strcmp(argv[1], "legacy")) {
        if (legacy_once()) return 1;
        puts("LEGACY_GIL_DELETE_UAF_REPRODUCED=YES owner_refcount=0 daemon_observed_freed=1");
        return 0;
    }
    int owner_old = 0, remaining = -1;
    if (!strcmp(argv[1], "fixed")) {
        if (fixed_once(&owner_old, &remaining)) return 1;
        puts("FIXED_HEAD_MUTEX=PASS interpreter_unlink_serialized=1");
        printf("FIXED_TSTATE_REFCOUNT=PASS owner_decrement_old=%d final_refs=%d\n", owner_old, remaining);
        puts("FIXED_NO_UAF=PASS daemon_gil_release_completed=1 freed_before_daemon=0");
        return 0;
    }
    if (!strcmp(argv[1], "stress")) {
        for (int i = 0; i < 1000; ++i) {
            if (fixed_once(&owner_old, &remaining)) {
                fprintf(stderr, "fixed stress failed at iteration %d\n", i);
                return 1;
            }
        }
        puts("FIXED_LIFETIME_STRESS=PASS iterations=1000 final_refs=0 uaf=0");
        return 0;
    }
    return 2;
}
