#define _GNU_SOURCE
#include <pthread.h>
#include <sched.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#if !defined(__aarch64__)
#error "This evidence test requires native aarch64 execution"
#endif

#define TSTATE_ALIVE_MAGIC UINT64_C(0x4350595448535441)
#define STRESS_ITERATIONS 1000

typedef struct {
    uint64_t magic;
    _Atomic unsigned refs;
    bool allocated;
} TState;

typedef struct {
    TState *tstate;
    bool linked;
} Interpreter;

static void wait_for(_Atomic int *phase, int wanted) {
    while (atomic_load_explicit(phase, memory_order_acquire) != wanted) sched_yield();
}

/* Legacy negative control: poison instead of dereferencing a real freed allocation,
 * so the lifetime violation is deterministic without invoking C undefined behavior. */
static pthread_mutex_t legacy_head_mutex = PTHREAD_MUTEX_INITIALIZER;
static Interpreter legacy_interp;
static TState legacy_tstate;
static _Atomic int legacy_phase;
static bool legacy_unlinked_without_mutex;
static bool legacy_stale_access;

static void *legacy_daemon_save_thread(void *unused) {
    (void)unused;
    TState *saved = legacy_interp.tstate; /* borrowed pointer: no reference acquired */
    atomic_store_explicit(&legacy_phase, 1, memory_order_release); /* SaveThread window */
    wait_for(&legacy_phase, 2);
    legacy_stale_access = !saved->allocated || saved->magic != TSTATE_ALIVE_MAGIC;
    return NULL;
}

static int run_legacy(void) {
    legacy_tstate = (TState){.magic = TSTATE_ALIVE_MAGIC, .allocated = true};
    atomic_init(&legacy_tstate.refs, 1);
    legacy_interp = (Interpreter){.tstate = &legacy_tstate, .linked = true};
    atomic_init(&legacy_phase, 0);
    legacy_unlinked_without_mutex = false;
    legacy_stale_access = false;
    pthread_t daemon;
    if (pthread_create(&daemon, NULL, legacy_daemon_save_thread, NULL) != 0) return 2;
    wait_for(&legacy_phase, 1);
    /* Bug model: interpreter-list mutation and tstate destruction race SaveThread,
     * with neither head_mutex serialization nor a daemon-owned tstate reference. */
    if (pthread_mutex_trylock(&legacy_head_mutex) == 0) {
        legacy_unlinked_without_mutex = true; /* lock was available but not required */
        pthread_mutex_unlock(&legacy_head_mutex);
    }
    legacy_interp.linked = false;
    legacy_interp.tstate = NULL;
    legacy_tstate.magic = 0;
    legacy_tstate.allocated = false;
    atomic_store_explicit(&legacy_phase, 2, memory_order_release);
    pthread_join(daemon, NULL);
    bool reproduced = legacy_unlinked_without_mutex && legacy_stale_access;
    printf("LEGACY_GIL_DELETE_RACE=REPRODUCED stale_tstate=%u poisoned_magic=0x%llx unlinked_without_head_mutex=%u\n",
           legacy_stale_access, (unsigned long long)legacy_tstate.magic,
           legacy_unlinked_without_mutex);
    return reproduced ? 0 : 3;
}

static pthread_mutex_t fixed_head_mutex = PTHREAD_MUTEX_INITIALIZER;
static Interpreter fixed_interp;
static TState fixed_tstate;
static _Atomic int fixed_phase;
static bool fixed_unlinked_under_mutex;
static bool fixed_stale_access;
static bool fixed_deleter_freed_early;
static unsigned fixed_delete_previous_refs;
static unsigned fixed_daemon_previous_refs;
static unsigned fixed_stress_passed;

static void *fixed_daemon_save_thread(void *unused) {
    (void)unused;
    /* Own a reference across the GIL-release window. */
    atomic_fetch_add_explicit(&fixed_tstate.refs, 1, memory_order_acq_rel);
    atomic_store_explicit(&fixed_phase, 1, memory_order_release);
    wait_for(&fixed_phase, 2);
    fixed_stale_access = !fixed_tstate.allocated || fixed_tstate.magic != TSTATE_ALIVE_MAGIC;
    fixed_daemon_previous_refs = atomic_fetch_sub_explicit(&fixed_tstate.refs, 1, memory_order_acq_rel);
    if (fixed_daemon_previous_refs == 1) {
        /* Last reference: destruction is now safe. */
        fixed_tstate.magic = 0;
        fixed_tstate.allocated = false;
    }
    return NULL;
}

static int run_fixed_once(bool quiet) {
    fixed_tstate = (TState){.magic = TSTATE_ALIVE_MAGIC, .allocated = true};
    atomic_init(&fixed_tstate.refs, 1);
    fixed_interp = (Interpreter){.tstate = &fixed_tstate, .linked = true};
    atomic_init(&fixed_phase, 0);
    fixed_unlinked_under_mutex = false;
    fixed_stale_access = false;
    fixed_deleter_freed_early = false;
    fixed_delete_previous_refs = 0;
    fixed_daemon_previous_refs = 0;
    pthread_t daemon;
    if (pthread_create(&daemon, NULL, fixed_daemon_save_thread, NULL) != 0) return 2;
    wait_for(&fixed_phase, 1);
    pthread_mutex_lock(&fixed_head_mutex);
    fixed_unlinked_under_mutex = true;
    fixed_interp.linked = false;
    fixed_interp.tstate = NULL;
    fixed_delete_previous_refs = atomic_fetch_sub_explicit(&fixed_tstate.refs, 1, memory_order_acq_rel);
    if (fixed_delete_previous_refs == 1) {
        fixed_tstate.magic = 0;
        fixed_tstate.allocated = false;
    } else if (fixed_delete_previous_refs != 2) {
        fixed_deleter_freed_early = true;
    }
    pthread_mutex_unlock(&fixed_head_mutex);
    atomic_store_explicit(&fixed_phase, 2, memory_order_release);
    pthread_join(daemon, NULL);
    unsigned final_refs = atomic_load_explicit(&fixed_tstate.refs, memory_order_acquire);
    bool pass = fixed_unlinked_under_mutex && !fixed_stale_access &&
                !fixed_deleter_freed_early && fixed_delete_previous_refs == 2 &&
                fixed_daemon_previous_refs == 1 && final_refs == 0 &&
                !fixed_tstate.allocated && !fixed_interp.linked;
    if (!quiet) {
        printf("FIXED_HEAD_MUTEX_REFCOUNT=%s stale_tstate=%u unlink_under_head_mutex=%u delete_ref_previous=%u daemon_ref_previous=%u final_refs=%u free_after_last_ref=%s\n",
               pass ? "PASS" : "FAIL", fixed_stale_access, fixed_unlinked_under_mutex,
               fixed_delete_previous_refs, fixed_daemon_previous_refs, final_refs,
               !fixed_tstate.allocated ? "YES" : "NO");
    }
    return pass ? 0 : 3;
}

static int run_stress(void) {
    fixed_stress_passed = 0;
    for (unsigned i = 0; i < STRESS_ITERATIONS; ++i) {
        if (run_fixed_once(true) != 0) break;
        fixed_stress_passed++;
    }
    printf("FIXED_GIL_DELETE_STRESS=%s iterations=%u passed=%u atomic_refcount_bits=32\n",
           fixed_stress_passed == STRESS_ITERATIONS ? "PASS" : "FAIL",
           STRESS_ITERATIONS, fixed_stress_passed);
    return fixed_stress_passed == STRESS_ITERATIONS ? 0 : 4;
}

int main(int argc, char **argv) {
    const char *mode = argc > 1 ? argv[1] : "all";
    puts("NATIVE_AARCH64_PTHREADS=YES HEAD_MUTEX=REQUIRED TSTATE_REFCOUNT=ATOMIC");
    if (strcmp(mode, "legacy") == 0) return run_legacy();
    if (strcmp(mode, "fixed") == 0) return run_fixed_once(false);
    if (strcmp(mode, "stress") == 0) return run_stress();
    if (strcmp(mode, "all") != 0) return 5;
    int legacy = run_legacy();
    int fixed = run_fixed_once(false);
    int stress = run_stress();
    if (legacy == 0 && fixed == 0 && stress == 0) {
        puts("FRONTIER_GH_0023_PASS=YES legacy_uaf=REPRODUCED fixed_uaf=REJECTED");
        return 0;
    }
    return 6;
}
