#define _GNU_SOURCE
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* Deterministic two-thread ABA regression over real C atomic CAS operations.
 * Nodes are statically owned: this isolates pointer/epoch ABA semantics and
 * deliberately makes no claim to solve safe memory reclamation. */
typedef struct node { struct node *next; int id; } node;
typedef struct { node *ptr; uint64_t epoch; } tagged_head;

static node A, B, C;
static _Atomic(node *) legacy_head;
static tagged_head fixed_head;
static uint64_t epoch_counter;
static pthread_barrier_t staged, release;
static int legacy_stale_cas_ok;
static int fixed_stale_cas_rejected;
static int fixed_retry_ok;

static uint64_t next_epoch(void) { return __atomic_add_fetch(&epoch_counter, 1, __ATOMIC_ACQ_REL); }

static void *legacy_popper(void *unused) {
    (void)unused;
    node *observed = atomic_load_explicit(&legacy_head, memory_order_acquire);
    node *next = observed->next;
    pthread_barrier_wait(&staged);
    pthread_barrier_wait(&release);
    node *expected = observed;
    legacy_stale_cas_ok = atomic_compare_exchange_strong_explicit(
        &legacy_head, &expected, next, memory_order_acq_rel, memory_order_acquire);
    return NULL;
}

static void *fixed_popper(void *unused) {
    (void)unused;
    tagged_head observed;
    __atomic_load(&fixed_head, &observed, __ATOMIC_ACQUIRE);
    node *next = observed.ptr->next;
    pthread_barrier_wait(&staged);
    pthread_barrier_wait(&release);
    tagged_head expected = observed;
    tagged_head desired = { next, next_epoch() };
    if (__atomic_compare_exchange(&fixed_head, &expected, &desired, 0,
                                  __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) {
        fprintf(stderr, "fixed stale CAS unexpectedly succeeded\n"); exit(1);
    }
    fixed_stale_cas_rejected = 1;
    /* Correct CAS-loop retry: reload both pointer and generation after ABA. */
    for (;;) {
        tagged_head current;
        __atomic_load(&fixed_head, &current, __ATOMIC_ACQUIRE);
        tagged_head replacement = { current.ptr->next, next_epoch() };
        if (__atomic_compare_exchange(&fixed_head, &current, &replacement, 0,
                                      __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) {
            fixed_retry_ok = 1; break;
        }
    }
    return NULL;
}

static void recycle_A_to_C(void) {
    /* Other consumer: pop A, pop B, then push recycled A before the stalled
     * consumer resumes. The address sequence is A -> C -> A (classic ABA). */
    atomic_store_explicit(&legacy_head, &B, memory_order_release);
    atomic_store_explicit(&legacy_head, &C, memory_order_release);
    A.next = &C;
    atomic_store_explicit(&legacy_head, &A, memory_order_release);
    fixed_head.ptr = &B; fixed_head.epoch = next_epoch();
    fixed_head.ptr = &C; fixed_head.epoch = next_epoch();
    A.next = &C;
    fixed_head.ptr = &A; fixed_head.epoch = next_epoch();
}

int main(int argc, char **argv) {
    if (argc != 2) { fprintf(stderr, "usage: %s legacy|fixed\n", argv[0]); return 2; }
    A.next = &B; B.next = &C; C.next = NULL; A.id = 1; B.id = 2; C.id = 3;
    atomic_init(&legacy_head, &A); fixed_head = (tagged_head){ &A, 0 }; epoch_counter = 0;
    if (pthread_barrier_init(&staged, NULL, 2) || pthread_barrier_init(&release, NULL, 2)) return 2;
    pthread_t thread;
    if (argv[1][0] == 'l') {
        if (pthread_create(&thread, NULL, legacy_popper, NULL)) return 2;
        pthread_barrier_wait(&staged); recycle_A_to_C(); pthread_barrier_wait(&release);
        pthread_join(thread, NULL);
        node *final = atomic_load_explicit(&legacy_head, memory_order_acquire);
        printf("mode=legacy ABA=A->C->A stale_cas_ok=%d final_node=%d expected_node=3 corruption=%s\n",
               legacy_stale_cas_ok, final->id, final == &B ? "REPRODUCED" : "NO");
        if (!legacy_stale_cas_ok || final != &B) return 1;
    } else if (argv[1][0] == 'f') {
        if (pthread_create(&thread, NULL, fixed_popper, NULL)) return 2;
        pthread_barrier_wait(&staged); recycle_A_to_C(); pthread_barrier_wait(&release);
        pthread_join(thread, NULL);
        tagged_head final; __atomic_load(&fixed_head, &final, __ATOMIC_ACQUIRE);
        int lock_free = __atomic_is_lock_free(sizeof(tagged_head), 0);
        printf("mode=fixed ABA=A->C->A stale_cas_rejected=%d retry_ok=%d final_node=%d final_epoch=%llu epoch_bits=64 tagged_cas_lock_free=%d\n",
               fixed_stale_cas_rejected, fixed_retry_ok, final.ptr->id,
               (unsigned long long)final.epoch, lock_free);
        if (!fixed_stale_cas_rejected || !fixed_retry_ok || final.ptr != &C || final.epoch != 5) return 1;
    } else { fprintf(stderr, "unknown mode\n"); return 2; }
    pthread_barrier_destroy(&staged); pthread_barrier_destroy(&release);
    return 0;
}
