#include "interpreter_lifecycle.h"

#include <assert.h>
#include <stdio.h>

#define STRESS_ITERATIONS 2000

typedef struct Race {
    pthread_barrier_t barrier;
    RuntimeState runtime;
    TestThreadState *tstate;
    int saved;
} Race;

static void *save_worker(void *arg)
{
    Race *race = arg;
    pthread_barrier_wait(&race->barrier);
    TestThreadState *saved = tstate_save_thread(&race->runtime, race->tstate);
    race->saved = saved != NULL;
    if (saved != NULL) {
        assert(saved->id == 0x7000);
        tstate_release(saved);
    }
    return NULL;
}

static void *delete_worker(void *arg)
{
    Race *race = arg;
    pthread_barrier_wait(&race->barrier);
    tstate_delete(&race->runtime, race->tstate);
    return NULL;
}

static void test_delete_then_save_is_rejected(void)
{
    RuntimeState runtime;
    runtime_init(&runtime);
    TestThreadState *tstate = tstate_create(&runtime, 7);
    tstate_delete(&runtime, tstate);
    assert(tstate_save_thread(&runtime, tstate) == NULL);
    assert(runtime.head == NULL);
    runtime_destroy(&runtime);
}

static void test_last_reference_frees_exactly_once(void)
{
    RuntimeState runtime;
    runtime_init(&runtime);
    TestThreadState *tstate = tstate_create(&runtime, 7);
    TestThreadState *saved = tstate_save_thread(&runtime, tstate);
    assert(saved == tstate);
    tstate_delete(&runtime, tstate);
    size_t allocated, freed;
    lifecycle_counts(&allocated, &freed);
    assert(allocated == freed + 1);
    assert(saved->id == 7);
    tstate_release(saved);
    lifecycle_counts(&allocated, &freed);
    assert(allocated == freed);
    runtime_destroy(&runtime);
}

static void test_concurrent_save_and_delete(void)
{
    int saves = 0;
    for (int i = 0; i < STRESS_ITERATIONS; i++) {
        Race race;
        pthread_barrier_init(&race.barrier, NULL, 2);
        runtime_init(&race.runtime);
        race.tstate = tstate_create(&race.runtime, 0x7000);
        race.saved = 0;
        pthread_t saver, deleter;
        assert(pthread_create(&saver, NULL, save_worker, &race) == 0);
        assert(pthread_create(&deleter, NULL, delete_worker, &race) == 0);
        pthread_join(saver, NULL);
        pthread_join(deleter, NULL);
        saves += race.saved;
        assert(race.runtime.head == NULL);
        size_t allocated, freed;
        lifecycle_counts(&allocated, &freed);
        assert(allocated == freed);
        runtime_destroy(&race.runtime);
        pthread_barrier_destroy(&race.barrier);
    }
    printf("concurrent iterations=%d successful_saves=%d rejected_saves=%d\n",
           STRESS_ITERATIONS, saves, STRESS_ITERATIONS - saves);
}

int main(void)
{
    test_delete_then_save_is_rejected();
    puts("delete_then_save_rejected: PASS");
    test_last_reference_frees_exactly_once();
    puts("atomic_last_reference_free_once: PASS");
    test_concurrent_save_and_delete();
    puts("concurrent_save_delete_no_uaf: PASS");
    return 0;
}
