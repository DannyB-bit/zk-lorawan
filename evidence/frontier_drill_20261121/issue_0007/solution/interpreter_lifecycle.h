#ifndef FRONTIER_INTERPRETER_LIFECYCLE_H
#define FRONTIER_INTERPRETER_LIFECYCLE_H

#define _POSIX_C_SOURCE 200809L
#include <pthread.h>
#include <stdatomic.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

typedef struct TestThreadState {
    uintptr_t id;
    _Atomic size_t references;
    _Atomic int deleting;
    struct TestThreadState *next;
} TestThreadState;

typedef struct RuntimeState {
    pthread_mutex_t head_mutex;
    TestThreadState *head;
} RuntimeState;

void runtime_init(RuntimeState *runtime);
void runtime_destroy(RuntimeState *runtime);
TestThreadState *tstate_create(RuntimeState *runtime, uintptr_t id);
TestThreadState *tstate_save_thread(RuntimeState *runtime, TestThreadState *candidate);
void tstate_delete(RuntimeState *runtime, TestThreadState *tstate);
void tstate_release(TestThreadState *tstate);
void lifecycle_counts(size_t *allocated, size_t *freed);

#endif
