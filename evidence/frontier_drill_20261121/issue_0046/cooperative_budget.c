#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define TICKS 256
#define BUDGET 64
#define GLOBAL_TASKS 4

typedef enum { READY, PENDING } poll_result;

typedef struct {
    int id;
    int completed;
} task;

/* An unyielding cooperative future: every poll returns PENDING and the
 * scheduler immediately requeues it at the local queue's tail. */
static poll_result unyielding_local_poll(task *t) {
    (void)t;
    return PENDING;
}

static poll_result global_poll(task *t) {
    t->completed = 1;
    return READY;
}

typedef struct {
    unsigned local_polls;
    unsigned global_completed;
    unsigned fallback_checks;
    unsigned max_global_wait;
    unsigned final_budget;
} metrics;

static metrics run_scheduler(int fixed) {
    task local = {.id = 1, .completed = 0};
    task global[GLOBAL_TASKS];
    for (int i = 0; i < GLOBAL_TASKS; i++) {
        global[i].id = 100 + i;
        global[i].completed = 0;
    }

    metrics m = {0};
    unsigned global_head = 0;
    unsigned ticks_since_global = 0;
    unsigned budget = BUDGET;

    for (unsigned tick = 1; tick <= TICKS; tick++) {
        if (global_head < GLOBAL_TASKS) ticks_since_global++;
        if (ticks_since_global > m.max_global_wait)
            m.max_global_wait = ticks_since_global;

        /* The repaired worker checks its global queue every 64 local polls,
         * including when the local unyielding future keeps winning polls. */
        int global_fallback_due = fixed && ticks_since_global >= BUDGET;
        if (global_fallback_due && global_head < GLOBAL_TASKS) {
            m.fallback_checks++;
            if (global_poll(&global[global_head]) == READY) {
                global_head++;
                m.global_completed++;
            }
            ticks_since_global = 0;
            budget = BUDGET;
            continue;
        }

        /* Legacy behavior: nonempty local queue always wins and the global
         * queue is never examined. Fixed behavior decrements cooperative
         * budget on every local poll, including PENDING nested yields. */
        if (unyielding_local_poll(&local) == PENDING) {
            m.local_polls++;
            if (fixed) {
                if (budget == 0) {
                    fprintf(stderr, "budget underflow before fallback\n");
                    exit(2);
                }
                budget--;
            }
        }
    }
    m.final_budget = budget;
    return m;
}

int main(int argc, char **argv) {
    if (argc != 2 || (strcmp(argv[1], "legacy") && strcmp(argv[1], "fixed"))) {
        fprintf(stderr, "usage: %s legacy|fixed\n", argv[0]);
        return 2;
    }
    int fixed = !strcmp(argv[1], "fixed");
    metrics m = run_scheduler(fixed);
    printf("mode=%s ticks=%d local_polls=%u global_completed=%u "
           "global_starved=%u fallback_checks=%u max_global_wait_ticks=%u "
           "budget=%u invariant=%s\n",
           fixed ? "fixed" : "legacy", TICKS, m.local_polls,
           m.global_completed, m.global_completed == 0, m.fallback_checks,
           m.max_global_wait, m.final_budget,
           fixed && m.global_completed == GLOBAL_TASKS &&
                   m.max_global_wait == BUDGET && m.fallback_checks == GLOBAL_TASKS
               ? "PASS"
               : (!fixed && m.global_completed == 0 ? "STARVATION_REPRODUCED" : "FAIL"));
    if (!fixed)
        return m.global_completed == 0 && m.local_polls == TICKS ? 0 : 1;
    return m.global_completed == GLOBAL_TASKS && m.local_polls == TICKS - GLOBAL_TASKS &&
                   m.max_global_wait == BUDGET && m.fallback_checks == GLOBAL_TASKS &&
                   m.final_budget == BUDGET
               ? 0
               : 1;
}
