#define _GNU_SOURCE
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

typedef struct {
    atomic_int refcount;
    int id;
} tstate;

typedef struct {
    tstate *thread;
    int id;
} interpreter_state;

static interpreter_state *global_interpreter;
static pthread_mutex_t head_mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_barrier_t observed;
static pthread_barrier_t deletion_released;
static int fixed_mode;
static atomic_int final_refcount = -1;
static int freed_once;

static void *daemon_save_thread(void *unused) {
    (void)unused;
    interpreter_state *victim;
    tstate *ts;

    if (fixed_mode) {
        /* Fixed PyEval_SaveThread path: head_mutex protects the interpreter
         * list lookup and an atomic reference is acquired before unlock. */
        pthread_mutex_lock(&head_mutex);
        victim = global_interpreter;
        if (!victim) {
            fprintf(stderr, "fixed daemon found no interpreter\n");
            exit(2);
        }
        ts = victim->thread;
        atomic_fetch_add_explicit(&ts->refcount, 1, memory_order_acq_rel);
        pthread_mutex_unlock(&head_mutex);
    } else {
        /* Legacy defect: borrowed tstate pointer escapes with neither the
         * list mutex nor an owning reference. */
        victim = global_interpreter;
        ts = victim->thread;
    }

    pthread_barrier_wait(&observed);
    pthread_barrier_wait(&deletion_released);

    int old = atomic_fetch_sub_explicit(&ts->refcount, 1, memory_order_acq_rel);
    atomic_store_explicit(&final_refcount, old - 1, memory_order_release);
    if (fixed_mode) {
        if (old != 1) {
            fprintf(stderr, "fixed final refcount was %d, expected 1\n", old);
            exit(2);
        }
        if (munmap(ts, 4096) != 0) return NULL;
        free(victim);
        freed_once++;
    }
    return NULL;
}

static int run_once(void) {
    global_interpreter = malloc(sizeof(*global_interpreter));
    if (!global_interpreter) return 2;
    global_interpreter->thread = mmap(NULL, 4096, PROT_READ | PROT_WRITE,
                                      MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (global_interpreter->thread == MAP_FAILED) return 2;
    global_interpreter->id = 43;
    global_interpreter->thread->id = 4301;
    atomic_init(&global_interpreter->thread->refcount, 1);
    atomic_store(&final_refcount, -1);
    freed_once = 0;

    pthread_t daemon;
    if (pthread_create(&daemon, NULL, daemon_save_thread, NULL)) return 2;

    pthread_barrier_wait(&observed);
    if (fixed_mode) {
        /* Fixed PyInterpreterState_Delete: serialized list detach followed
         * by atomic drop of the list's owning reference. */
        pthread_mutex_lock(&head_mutex);
        interpreter_state *victim = global_interpreter;
        global_interpreter = NULL;
        int old = atomic_fetch_sub_explicit(&victim->thread->refcount, 1,
                                            memory_order_acq_rel);
        pthread_mutex_unlock(&head_mutex);
        if (old != 2) {
            fprintf(stderr, "fixed delete refcount was %d, expected 2\n", old);
            return 2;
        }
        /* old==2 means the daemon still owns tstate; do not free here. */
    } else {
        interpreter_state *victim = global_interpreter;
        global_interpreter = NULL;
        /* Unmapping the tstate page makes the legacy daemon's next atomic
         * access a real, deterministic SIGSEGV rather than a simulated error. */
        munmap(victim->thread, 4096);
        free(victim);
    }
    pthread_barrier_wait(&deletion_released);
    pthread_join(daemon, NULL);

    if (fixed_mode) {
        printf("mode=fixed detach=head_mutex initial_refs=2 daemon_lease=1 "
               "final_refcount=%d freed_once=%d invariant=PASS\n",
               atomic_load(&final_refcount), freed_once);
        return atomic_load(&final_refcount) == 0 && freed_once == 1 ? 0 : 1;
    }
    printf("mode=legacy unexpectedly completed without UAF detection\n");
    return 1;
}

int main(int argc, char **argv) {
    if (argc != 2 || (strcmp(argv[1], "legacy") && strcmp(argv[1], "fixed"))) {
        fprintf(stderr, "usage: %s legacy|fixed\n", argv[0]);
        return 2;
    }
    fixed_mode = !strcmp(argv[1], "fixed");
    if (pthread_barrier_init(&observed, NULL, 2) ||
        pthread_barrier_init(&deletion_released, NULL, 2)) return 2;
    int rc = run_once();
    pthread_barrier_destroy(&observed);
    pthread_barrier_destroy(&deletion_released);
    return rc;
}
