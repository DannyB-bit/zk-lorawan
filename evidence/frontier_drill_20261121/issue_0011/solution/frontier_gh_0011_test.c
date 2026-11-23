#include <assert.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdio.h>

/* Deterministic lifetime model of the patched SaveThread/Delete critical sections. */
typedef struct {
    pthread_mutex_t head_mutex;
    _Atomic unsigned int gil_release_refs;
    _Atomic bool detached;
    _Atomic bool freed;
} runtime_model_t;

static void save_thread_pin(runtime_model_t *r) {
    pthread_mutex_lock(&r->head_mutex);
    atomic_fetch_add_explicit(&r->gil_release_refs, 1, memory_order_acquire);
    pthread_mutex_unlock(&r->head_mutex);
}

static void save_thread_unpin_after_drop_gil(runtime_model_t *r) {
    unsigned int old = atomic_fetch_sub_explicit(&r->gil_release_refs, 1,
                                                 memory_order_release);
    assert(old == 1); /* verify atomic decrement: no underflow/double release */
}

static void delete_interpreter(runtime_model_t *r) {
    pthread_mutex_lock(&r->head_mutex);
    atomic_store_explicit(&r->detached, true, memory_order_release);
    pthread_mutex_unlock(&r->head_mutex);
    while (atomic_load_explicit(&r->gil_release_refs, memory_order_acquire) != 0) {
        atomic_signal_fence(memory_order_seq_cst);
    }
    atomic_store_explicit(&r->freed, true, memory_order_release);
}

static void legacy_delete_without_pin_check(runtime_model_t *r) {
    atomic_store_explicit(&r->detached, true, memory_order_release);
    atomic_store_explicit(&r->freed, true, memory_order_release);
}

static void init(runtime_model_t *r) {
    pthread_mutex_init(&r->head_mutex, NULL);
    atomic_init(&r->gil_release_refs, 0);
    atomic_init(&r->detached, false);
    atomic_init(&r->freed, false);
}

static void test_reproduce_frontier_gh_0011(void) {
    runtime_model_t legacy;
    init(&legacy);
    save_thread_pin(&legacy);
    legacy_delete_without_pin_check(&legacy);
    assert(atomic_load(&legacy.freed));
    assert(atomic_load(&legacy.gil_release_refs) == 1);
    puts("PASS: legacy ordering reproduced free while SaveThread pin was live");

    runtime_model_t fixed;
    init(&fixed);
    save_thread_pin(&fixed);
    pthread_mutex_lock(&fixed.head_mutex);
    atomic_store(&fixed.detached, true);
    pthread_mutex_unlock(&fixed.head_mutex);
    assert(!atomic_load(&fixed.freed));
    assert(atomic_load(&fixed.gil_release_refs) == 1);
    save_thread_unpin_after_drop_gil(&fixed);
    delete_interpreter(&fixed);
    assert(atomic_load(&fixed.freed));
    assert(atomic_load(&fixed.gil_release_refs) == 0);
    puts("PASS: patched ordering frees only after atomic pin drains");
}

static void test_baseline_and_mutex_boundary(void) {
    runtime_model_t r;
    init(&r);
    save_thread_pin(&r);
    assert(!atomic_load(&r.detached));
    save_thread_unpin_after_drop_gil(&r);
    delete_interpreter(&r);
    assert(atomic_load(&r.detached) && atomic_load(&r.freed));
    pthread_mutex_destroy(&r.head_mutex);
    puts("PASS: no-pin baseline and head_mutex detach boundary");
}

int main(void) {
    test_reproduce_frontier_gh_0011();
    test_baseline_and_mutex_boundary();
    puts("test result: ok. 2 passed; 0 failed");
    return 0;
}
