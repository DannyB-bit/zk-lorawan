// FRONTIER-GH-0015 native regression model for CPython interpreter/tstate teardown.
// This is not upstream CPython source: it isolates the required lifetime protocol
// so ASan and real pthread execution can test the exact lock/refcount invariant.
#define _GNU_SOURCE
#include <assert.h>
#include <pthread.h>
#include <sched.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

typedef struct {
    int refcount; // legacy deliberately uses non-atomic lifetime accounting
    atomic_int atomic_refcount; // fixed path
    unsigned char tls_area[256];
} TState;

typedef struct {
    TState *tstate;
    atomic_bool listed;
} Interpreter;

static pthread_mutex_t head_mutex = PTHREAD_MUTEX_INITIALIZER;
static atomic_ulong lock_acquisitions;
static atomic_ulong successful_saves;
static atomic_ulong completed_deletes;

static void fixed_release(TState *ts) {
    int old = atomic_fetch_sub_explicit(&ts->atomic_refcount, 1, memory_order_acq_rel);
    assert(old > 0);
    if (old == 1) {
        // No thread can retain a reference after the final atomic decrement.
        memset(ts->tls_area, 0, sizeof(ts->tls_area));
        free(ts);
    }
}

typedef struct {
    Interpreter *interp;
    atomic_bool *stop;
} SaveArgs;

// Models a daemon thread calling PyEval_SaveThread while teardown is concurrent.
static void *fixed_save_thread(void *opaque) {
    SaveArgs *args = opaque;
    while (!atomic_load_explicit(args->stop, memory_order_relaxed)) {
        pthread_mutex_lock(&head_mutex);
        atomic_fetch_add(&lock_acquisitions, 1);
        TState *ts = NULL;
        if (atomic_load_explicit(&args->interp->listed, memory_order_acquire)) {
            ts = args->interp->tstate;
            int old = atomic_fetch_add_explicit(&ts->atomic_refcount, 1, memory_order_relaxed);
            assert(old > 0);
        }
        pthread_mutex_unlock(&head_mutex);
        if (ts) {
            atomic_fetch_add(&successful_saves, 1);
            // GIL-release critical section: temporary ref keeps tstate alive.
            ((volatile unsigned char *)ts->tls_area)[0]++;
            sched_yield();
            fixed_release(ts);
        }
    }
    return NULL;
}

static void fixed_delete_interpreter(Interpreter *interp) {
    pthread_mutex_lock(&head_mutex);
    atomic_fetch_add(&lock_acquisitions, 1);
    atomic_store_explicit(&interp->listed, false, memory_order_release);
    // Drop the interpreter list's owning ref. New acquisitions are impossible
    // after unlink; prior daemon refs drain independently and atomically.
    fixed_release(interp->tstate);
    pthread_mutex_unlock(&head_mutex);
    atomic_fetch_add(&completed_deletes, 1);
}

static int fixed_stress(void) {
    enum { ROUNDS = 128, SAVERS = 8 };
    for (int round = 0; round < ROUNDS; round++) {
        TState *ts = calloc(1, sizeof(*ts));
        assert(ts);
        atomic_init(&ts->atomic_refcount, 1);
        Interpreter interp = {.tstate = ts};
        atomic_init(&interp.listed, true);
        atomic_bool stop;
        atomic_init(&stop, false);
        pthread_t threads[SAVERS];
        SaveArgs args = {.interp = &interp, .stop = &stop};
        for (int i = 0; i < SAVERS; i++) assert(!pthread_create(&threads[i], NULL, fixed_save_thread, &args));
        // Vary teardown timing to exercise both acquisition-before-unlink and
        // acquisition-after-unlink paths without controlling the outcome.
        if (round & 1) sched_yield(); else usleep(50);
        fixed_delete_interpreter(&interp);
        atomic_store(&stop, true);
        for (int i = 0; i < SAVERS; i++) assert(!pthread_join(threads[i], NULL));
        assert(!atomic_load(&interp.listed));
    }
    unsigned long saves = atomic_load(&successful_saves);
    unsigned long locks = atomic_load(&lock_acquisitions);
    unsigned long deletes = atomic_load(&completed_deletes);
    assert(saves > 0 && locks >= ROUNDS && deletes == ROUNDS);
    printf("SUBINTERPRETER_LIFETIME_PASS=YES rounds=%d savers=%d successful_saves=%lu head_mutex_acquisitions=%lu atomic_deletes=%lu\n",
           ROUNDS, SAVERS, saves, locks, deletes);
    return 0;
}

static int legacy_negative_control(void) {
    // Legacy ordering: PyInterpreterState_Delete unlinks/frees the tstate while
    // a daemon can still enter PyEval_SaveThread without head_mutex or a ref.
    long page = sysconf(_SC_PAGESIZE);
    assert(page > 0 && (size_t)page >= sizeof(TState));
    TState *ts = mmap(NULL, (size_t)page, PROT_READ | PROT_WRITE,
                      MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    assert(ts != MAP_FAILED);
    ts->refcount = 1;
    Interpreter interp = {.tstate = ts};
    atomic_init(&interp.listed, true);
    atomic_store(&interp.listed, false);
    ts->refcount--; // non-atomic decrement in the legacy model
    assert(munmap(ts, (size_t)page) == 0); // deterministic guard-page UAF
    // The unmapped former tstate page must trap this exact daemon read with
    // SIGSEGV. This does not depend on ASan's runtime address-space layout.
    volatile unsigned char daemon_read = ((volatile unsigned char *)interp.tstate->tls_area)[0];
    fprintf(stderr, "ERROR: legacy UAF not detected, read=%u\n", daemon_read);
    return 2;
}

int main(int argc, char **argv) {
    if (argc == 2 && !strcmp(argv[1], "fixed")) return fixed_stress();
    if (argc == 2 && !strcmp(argv[1], "legacy")) return legacy_negative_control();
    fprintf(stderr, "usage: %s fixed|legacy\n", argv[0]);
    return 64;
}
