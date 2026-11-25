#include <pthread.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define WORKERS 4
#define GLOBAL_TASKS 256
#define TICKS_PER_WORKER 4096
#define COOP_BUDGET_INITIAL 128
#define GLOBAL_FALLBACK_TICKS 64

typedef enum { PENDING, READY } Poll;
typedef struct {
    unsigned depth;
    unsigned long polls;
} NestedFuture;

/* An unyielding nested future: every poll returns Pending and requeues locally. */
static Poll poll_nested_future(NestedFuture *f) {
    unsigned long polls = 0;
    for (unsigned level = 0; level < f->depth; ++level) {
        /* Child Pending propagates through every nested poll level. */
        polls++;
    }
    f->polls += polls;
    return PENDING;
}

typedef struct {
    _Atomic unsigned next;
    _Atomic unsigned completed;
    _Atomic unsigned long checksum;
} GlobalQueue;

typedef struct {
    GlobalQueue *global;
    bool cooperative;
    unsigned id;
    NestedFuture local;
    unsigned budget;
    unsigned long scheduler_ticks;
    unsigned long global_checks;
    unsigned global_completed;
    unsigned final_budget;
} Worker;

static void execute_global_task(Worker *w, unsigned task) {
    /* Real queued work: verify a deterministic task payload and account once. */
    unsigned long value = (unsigned long)(task + 1) * 1099511628211UL;
    atomic_fetch_add_explicit(&w->global->checksum, value, memory_order_relaxed);
    w->global_completed++;
    atomic_fetch_add_explicit(&w->global->completed, 1, memory_order_release);
}

static void global_fallback(Worker *w) {
    w->global_checks++;
    unsigned task = atomic_fetch_add_explicit(&w->global->next, 1, memory_order_acq_rel);
    if (task < GLOBAL_TASKS) execute_global_task(w, task);
}

static void *worker_main(void *opaque) {
    Worker *w = opaque;
    w->budget = COOP_BUDGET_INITIAL;
    for (unsigned tick = 1; tick <= TICKS_PER_WORKER; ++tick) {
        /* Local queue always wins in legacy mode: no budget, no global check. */
        if (poll_nested_future(&w->local) != PENDING) atomic_fetch_add(&w->global->completed, 1000000);
        w->scheduler_ticks++;
        if (w->cooperative) {
            if (w->budget > 0) w->budget--;
            bool tick_fallback = tick % GLOBAL_FALLBACK_TICKS == 0;
            bool budget_fallback = w->budget == 0;
            if (tick_fallback || budget_fallback) {
                global_fallback(w);
                if (budget_fallback) w->budget = COOP_BUDGET_INITIAL;
            }
        }
    }
    w->final_budget = w->budget;
    return NULL;
}

static int run_scheduler(bool cooperative) {
    GlobalQueue global;
    atomic_init(&global.next, 0);
    atomic_init(&global.completed, 0);
    atomic_init(&global.checksum, 0);
    Worker workers[WORKERS];
    pthread_t threads[WORKERS];
    memset(workers, 0, sizeof(workers));
    for (unsigned i = 0; i < WORKERS; ++i) {
        workers[i] = (Worker){.global = &global, .cooperative = cooperative,
                              .id = i, .local = {.depth = 4, .polls = 0}};
        if (pthread_create(&threads[i], NULL, worker_main, &workers[i]) != 0) return 2;
    }
    unsigned long checks = 0, ticks = 0, local_polls = 0;
    unsigned final_budget_sum = 0;
    for (unsigned i = 0; i < WORKERS; ++i) {
        pthread_join(threads[i], NULL);
        checks += workers[i].global_checks;
        ticks += workers[i].scheduler_ticks;
        local_polls += workers[i].local.polls;
        final_budget_sum += workers[i].final_budget;
    }
    unsigned completed = atomic_load_explicit(&global.completed, memory_order_acquire);
    unsigned long expected_checksum = 0;
    for (unsigned i = 0; i < GLOBAL_TASKS; ++i) expected_checksum += (unsigned long)(i + 1) * 1099511628211UL;
    bool counts_ok = ticks == WORKERS * TICKS_PER_WORKER &&
                     local_polls == WORKERS * TICKS_PER_WORKER * 4;
    if (!cooperative) {
        bool starved = counts_ok && completed == 0 && checks == 0 &&
                       final_budget_sum == WORKERS * COOP_BUDGET_INITIAL;
        printf("LEGACY_UNYIELDING_STARVATION=%s local_ticks=%lu nested_polls=%lu global_completed=%u global_checks=%lu budget=UNDECREMENTED\n",
               starved ? "REPRODUCED" : "FAIL", ticks, local_polls, completed, checks);
        return starved ? 0 : 3;
    }
    bool fixed = counts_ok && completed == GLOBAL_TASKS &&
                 atomic_load(&global.checksum) == expected_checksum &&
                 checks >= WORKERS * (TICKS_PER_WORKER / GLOBAL_FALLBACK_TICKS);
    printf("FIXED_COOPERATIVE_SCHEDULER=%s local_ticks=%lu nested_polls=%lu global_completed=%u global_checks=%lu checksum=%s budget_bits=32 fallback_ticks=64\n",
           fixed ? "PASS" : "FAIL", ticks, local_polls, completed, checks,
           atomic_load(&global.checksum) == expected_checksum ? "MATCH" : "MISMATCH");
    return fixed ? 0 : 4;
}

int main(int argc, char **argv) {
    const char *mode = argc > 1 ? argv[1] : "all";
    printf("NATIVE_PTHREAD_WORKERS=%d NESTED_FUTURE_DEPTH=4 COOP_BUDGET_INITIAL=%d GLOBAL_FALLBACK_TICKS=%d\n",
           WORKERS, COOP_BUDGET_INITIAL, GLOBAL_FALLBACK_TICKS);
    if (strcmp(mode, "legacy") == 0) return run_scheduler(false);
    if (strcmp(mode, "fixed") == 0) return run_scheduler(true);
    if (strcmp(mode, "all") != 0) return 5;
    int legacy = run_scheduler(false);
    int fixed = run_scheduler(true);
    if (legacy == 0 && fixed == 0) {
        puts("FRONTIER_GH_0022_PASS=YES legacy_global_starved=YES fixed_global_drained=YES");
        return 0;
    }
    return 6;
}
