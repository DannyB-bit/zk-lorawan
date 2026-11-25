// FRONTIER-GH-0033: deterministic two-thread ABA regression on physical aarch64.
// The legacy lane recycles A->B->C back to A->C while a consumer holds A/B.
// The fixed lane couples the pointer to a uint64_t epoch in one 16-byte atomic CAS.
#define _GNU_SOURCE
#include <pthread.h>
#include <sched.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

typedef struct Node Node;
struct Node { int id; _Atomic(Node *) next; };
typedef struct { Node *ptr; uint64_t epoch; } Tagged;
typedef struct {
    int fixed, rounds;
    Node a, b, c;
    _Atomic(Node *) plain_head;
    Tagged tagged_head;
    _Atomic int stage;
    long aba, rejected, chain_ok;
} Harness;

static void stage_store(Harness *h, int s) { atomic_store_explicit(&h->stage, s, memory_order_release); }
static void stage_wait(Harness *h, int s) { while (atomic_load_explicit(&h->stage, memory_order_acquire) != s) sched_yield(); }

static int tagged_cas(Tagged *head, Tagged *expected, Node *desired) {
    Tagged want = { desired, expected->epoch + 1 }; // 64-bit generation changes on every successful update.
    return __atomic_compare_exchange(head, expected, &want, 0, __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE);
}
static Node *tagged_pop(Tagged *head) {
    Tagged old = ({ Tagged old; __atomic_load(head, &old, __ATOMIC_ACQUIRE); old; });
    for (;;) {
        if (!old.ptr) return NULL;
        Node *next = atomic_load_explicit(&old.ptr->next, memory_order_acquire);
        Tagged expected = old;
        if (tagged_cas(head, &expected, next)) return old.ptr;
        old = expected;
    }
}
static void tagged_push(Tagged *head, Node *n) {
    Tagged old = ({ Tagged old; __atomic_load(head, &old, __ATOMIC_ACQUIRE); old; });
    for (;;) {
        atomic_store_explicit(&n->next, old.ptr, memory_order_relaxed);
        Tagged expected = old;
        if (tagged_cas(head, &expected, n)) return;
        old = expected;
    }
}
static Node *plain_pop(_Atomic(Node *) *head) {
    Node *old = atomic_load_explicit(head, memory_order_acquire);
    while (old) {
        Node *next = atomic_load_explicit(&old->next, memory_order_acquire);
        if (atomic_compare_exchange_weak_explicit(head, &old, next, memory_order_acq_rel, memory_order_acquire)) return old;
    }
    return NULL;
}
static void plain_push(_Atomic(Node *) *head, Node *n) {
    Node *old = atomic_load_explicit(head, memory_order_acquire);
    for (;;) {
        atomic_store_explicit(&n->next, old, memory_order_relaxed);
        if (atomic_compare_exchange_weak_explicit(head, &old, n, memory_order_acq_rel, memory_order_acquire)) return;
    }
}
static void init_round(Harness *h, int r) {
    atomic_store(&h->a.next, &h->b); atomic_store(&h->b.next, &h->c); atomic_store(&h->c.next, NULL);
    if (h->fixed) { Tagged t = { &h->a, ((uint64_t)r + 1) << 32 }; __atomic_store(&h->tagged_head, &t, __ATOMIC_RELEASE); }
    else atomic_store_explicit(&h->plain_head, &h->a, memory_order_release);
}
static void *victim(void *arg) {
    Harness *h = arg;
    for (int r = 0; r < h->rounds; r++) {
        stage_wait(h, 1);
        if (h->fixed) {
            Tagged old = ({ Tagged old; __atomic_load(&h->tagged_head, &old, __ATOMIC_ACQUIRE); old; });
            Node *next = atomic_load_explicit(&old.ptr->next, memory_order_acquire);
            stage_store(h, 2); stage_wait(h, 3);
            Tagged expected = old;
            if (!tagged_cas(&h->tagged_head, &expected, next)) h->rejected++; else h->aba++;
        } else {
            Node *old = atomic_load_explicit(&h->plain_head, memory_order_acquire);
            Node *next = atomic_load_explicit(&old->next, memory_order_acquire);
            stage_store(h, 2); stage_wait(h, 3);
            Node *expected = old;
            if (atomic_compare_exchange_strong_explicit(&h->plain_head, &expected, next, memory_order_acq_rel, memory_order_acquire)) h->aba++;
        }
        stage_store(h, 4);
    }
    return NULL;
}
static void *recycler(void *arg) {
    Harness *h = arg;
    for (int r = 0; r < h->rounds; r++) {
        init_round(h, r); stage_store(h, 1); stage_wait(h, 2);
        if (h->fixed) {
            Node *a = tagged_pop(&h->tagged_head), *b = tagged_pop(&h->tagged_head);
            if (a != &h->a || b != &h->b) abort();
            tagged_push(&h->tagged_head, a); // Recycle identical address A with a different epoch.
        } else {
            Node *a = plain_pop(&h->plain_head), *b = plain_pop(&h->plain_head);
            if (a != &h->a || b != &h->b) abort();
            plain_push(&h->plain_head, a);
        }
        stage_store(h, 3); stage_wait(h, 4);
        if (h->fixed) {
            Tagged t = ({ Tagged old; __atomic_load(&h->tagged_head, &old, __ATOMIC_ACQUIRE); old; });
            if (t.ptr == &h->a && atomic_load(&h->a.next) == &h->c && atomic_load(&h->c.next) == NULL) h->chain_ok++;
        }
    }
    stage_store(h, 5); return NULL;
}
static Harness run_lane(int fixed, int rounds) {
    Harness h; memset(&h, 0, sizeof(h)); h.fixed = fixed; h.rounds = rounds;
    h.a.id = 1; h.b.id = 2; h.c.id = 3;
    pthread_t v, r;
    if (pthread_create(&v, NULL, victim, &h) || pthread_create(&r, NULL, recycler, &h)) abort();
    pthread_join(v, NULL); pthread_join(r, NULL); return h;
}
static int ordered_regression(void) {
    Tagged head = {0}; Node n[3];
    for (int i = 0; i < 3; i++) { n[i].id = i; atomic_init(&n[i].next, NULL); tagged_push(&head, &n[i]); }
    for (int i = 2; i >= 0; i--) if (tagged_pop(&head) != &n[i]) return 0;
    return head.ptr == NULL && head.epoch == 6;
}
int main(void) {
    const int rounds = 2000;
    Harness legacy = run_lane(0, rounds), fixed = run_lane(1, rounds);
    int ordered = ordered_regression();
    printf("LEGACY_POINTER_CAS rounds=%d ABA_success=%ld corrupted_head_B=%ld\n", rounds, legacy.aba, legacy.aba);
    printf("FIXED_TAGGED_CAS rounds=%d ABA_success=%ld stale_CAS_rejected=%ld intact_A_to_C=%ld epoch_bits=64\n", rounds, fixed.aba, fixed.rejected, fixed.chain_ok);
    printf("ORDERED_PUSH_POP=%s tagged_16B_always_lockfree=%d\n", ordered ? "PASS" : "FAIL", __atomic_always_lock_free(sizeof(Tagged), 0));
    if (legacy.aba != rounds || fixed.aba != 0 || fixed.rejected != rounds || fixed.chain_ok != rounds || !ordered) return 1;
    puts("ABA_EPOCH_INVARIANT=PASS"); return 0;
}
