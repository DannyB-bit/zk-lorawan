#include "interpreter_lifecycle.h"

#include <assert.h>
#include <stdlib.h>

static _Atomic size_t allocated;
static _Atomic size_t freed;

static void *
tracked_alloc(size_t size)
{
    void *p = calloc(1, size);
    assert(p != NULL);
    atomic_fetch_add_explicit(&allocated, 1, memory_order_relaxed);
    return p;
}

static void
tracked_free(void *p)
{
    atomic_fetch_add_explicit(&freed, 1, memory_order_relaxed);
    free(p);
}

void
runtime_init(RuntimeState *runtime)
{
    memset(runtime, 0, sizeof(*runtime));
    pthread_mutex_init(&runtime->head_mutex, NULL);
}

void
runtime_destroy(RuntimeState *runtime)
{
    assert(runtime->head == NULL);
    pthread_mutex_destroy(&runtime->head_mutex);
}

TestThreadState *
tstate_create(RuntimeState *runtime, uintptr_t id)
{
    TestThreadState *tstate = tracked_alloc(sizeof(*tstate));
    tstate->id = id;
    atomic_init(&tstate->references, 1);
    atomic_init(&tstate->deleting, 0);
    pthread_mutex_lock(&runtime->head_mutex);
    tstate->next = runtime->head;
    runtime->head = tstate;
    pthread_mutex_unlock(&runtime->head_mutex);
    return tstate;
}

/* Returns an owned reference, or NULL if deletion won the head_mutex race. */
TestThreadState *
tstate_save_thread(RuntimeState *runtime, TestThreadState *candidate)
{
    TestThreadState *result = NULL;
    pthread_mutex_lock(&runtime->head_mutex);
    for (TestThreadState *p = runtime->head; p != NULL; p = p->next) {
        if (p != candidate) {
            continue;
        }
        size_t refs = atomic_load_explicit(&p->references, memory_order_relaxed);
        while (refs != 0 && !atomic_load_explicit(&p->deleting, memory_order_relaxed)) {
            if (atomic_compare_exchange_weak_explicit(&p->references, &refs, refs + 1,
                    memory_order_acquire, memory_order_relaxed)) {
                result = p;
                break;
            }
        }
        break;
    }
    pthread_mutex_unlock(&runtime->head_mutex);
    return result;
}

/* Unlink and mark deleting under head_mutex, then drop the list's reference. */
void
tstate_delete(RuntimeState *runtime, TestThreadState *tstate)
{
    pthread_mutex_lock(&runtime->head_mutex);
    TestThreadState **link = &runtime->head;
    while (*link != NULL && *link != tstate) {
        link = &(*link)->next;
    }
    assert(*link == tstate);
    *link = tstate->next;
    atomic_store_explicit(&tstate->deleting, 1, memory_order_release);
    pthread_mutex_unlock(&runtime->head_mutex);
    tstate_release(tstate);
}

void
tstate_release(TestThreadState *tstate)
{
    size_t old = atomic_fetch_sub_explicit(&tstate->references, 1, memory_order_acq_rel);
    assert(old > 0);
    if (old == 1) {
        tracked_free(tstate);
    }
}

void
lifecycle_counts(size_t *live_allocated, size_t *live_freed)
{
    *live_allocated = atomic_load_explicit(&allocated, memory_order_relaxed);
    *live_freed = atomic_load_explicit(&freed, memory_order_relaxed);
}
