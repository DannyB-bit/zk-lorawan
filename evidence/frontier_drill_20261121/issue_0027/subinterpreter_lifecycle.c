// FRONTIER-GH-0027: deterministic native CPython-lifecycle race model.
// Scope: models the stated PyEval_SaveThread/PyInterpreterState_Delete hazard;
// it is not a claimed patch to CPython or torvalds/linux.
#define _POSIX_C_SOURCE 200809L
#include <pthread.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

typedef struct { _Atomic int refs; uint64_t magic; } TState;
typedef struct Interpreter { TState *tstate; bool deleting; struct Interpreter *next; } Interpreter;

static pthread_mutex_t head_mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_mutex_t gate_mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t gate_cond = PTHREAD_COND_INITIALIZER;
static Interpreter *head;
static int gate_stage;
static int save_mutex_acquisitions;
static int delete_mutex_acquisitions;

static void wait_for_stage(int stage) {
    pthread_mutex_lock(&gate_mutex);
    while (gate_stage < stage) pthread_cond_wait(&gate_cond, &gate_mutex);
    pthread_mutex_unlock(&gate_mutex);
}
static void announce_save(void) {
    pthread_mutex_lock(&gate_mutex);
    gate_stage = 1;
    pthread_cond_broadcast(&gate_cond);
    pthread_mutex_unlock(&gate_mutex);
}
static void finish_delete(void) {
    pthread_mutex_lock(&gate_mutex);
    gate_stage = 2;
    pthread_cond_broadcast(&gate_cond);
    pthread_mutex_unlock(&gate_mutex);
}
static int release_tstate(TState *tstate) {
    int old = atomic_fetch_sub_explicit(&tstate->refs, 1, memory_order_acq_rel);
    // A dedicated mapping makes the buggy post-delete access a deterministic,
    // kernel-enforced UAF fault rather than allocator-dependent behavior.
    if (old == 1 && munmap(tstate, 4096) != 0) abort();
    return old;
}
static bool fixed_mode;
static void *save_thread(void *arg) {
    Interpreter *interp = arg;
    TState *tstate = NULL;
    if (fixed_mode) {
        // Fix: pin the interpreter/tstate while head_mutex protects the list.
        pthread_mutex_lock(&head_mutex);
        save_mutex_acquisitions++;
        if (!interp->deleting) {
            tstate = interp->tstate;
            int old = atomic_fetch_add_explicit(&tstate->refs, 1, memory_order_relaxed);
            if (old < 1) { pthread_mutex_unlock(&head_mutex); abort(); }
        }
        pthread_mutex_unlock(&head_mutex);
        if (!tstate) return NULL;
    } else {
        // Defect: an unpinned tstate pointer survives concurrent deletion.
        tstate = interp->tstate;
    }
    announce_save();
    wait_for_stage(2);
    if (!fixed_mode) {
        // Deliberate real UAF in buggy mode: deletion already unmapped this page.
        if (tstate->magic != UINT64_C(0x545354414745)) abort();
    }
    int old = release_tstate(tstate);
    if (fixed_mode && old != 1) abort();
    return NULL;
}
static void *delete_interpreter(void *arg) {
    Interpreter *interp = arg;
    wait_for_stage(1);
    if (fixed_mode) {
        // Fix: unlink/mark deleting and drop the owner ref under head_mutex.
        pthread_mutex_lock(&head_mutex);
        delete_mutex_acquisitions++;
        interp->deleting = true;
        if (head == interp) head = interp->next;
        int old = release_tstate(interp->tstate);
        if (old != 2) { pthread_mutex_unlock(&head_mutex); abort(); }
        pthread_mutex_unlock(&head_mutex);
    } else {
        // Defect: list mutation and owner release race with SaveThread.
        if (head == interp) head = interp->next;
        release_tstate(interp->tstate);
    }
    finish_delete();
    return NULL;
}
int main(int argc, char **argv) {
    if (argc != 2 || (strcmp(argv[1], "--buggy") && strcmp(argv[1], "--fixed"))) return 64;
    fixed_mode = !strcmp(argv[1], "--fixed");
    Interpreter interp = {0};
    interp.tstate = mmap(NULL, 4096, PROT_READ | PROT_WRITE,
                         MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (interp.tstate == MAP_FAILED) return 70;
    atomic_init(&interp.tstate->refs, 1);
    interp.tstate->magic = UINT64_C(0x545354414745);
    head = &interp;
    pthread_t saver, deleter;
    if (pthread_create(&saver, NULL, save_thread, &interp)) return 71;
    if (pthread_create(&deleter, NULL, delete_interpreter, &interp)) return 72;
    pthread_join(saver, NULL);
    pthread_join(deleter, NULL);
    if (fixed_mode) {
        if (save_mutex_acquisitions != 1 || delete_mutex_acquisitions != 1 || head != NULL) return 73;
        puts("FIXED_OK: head_mutex protected save+delete; temporary ref pinned tstate; atomic decrements 2->1->0");
    } else {
        puts("BUGGY_RETURNED_WITHOUT_FAULT: reproduction did not fault");
        return 2;
    }
    return 0;
}
