// FRONTIER-GH-0029: deterministic two-thread ABA reproduction on aarch64.
// The fixed queue uses a pointer+64-bit epoch pair with real ARMv8 LDAXP/STLXP
// double-width CAS (acquire/release), not an emulated mutex or mock atomic.
#define _POSIX_C_SOURCE 200809L
#include <pthread.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct Node { struct Node *next; int id; } Node;
typedef struct Head { Node *ptr; uint64_t epoch; } Head;
static _Atomic(Node *) legacy_head;
static Head tagged_head;
static Node a, b;
static bool fixed_mode;
static pthread_mutex_t gate_mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t gate_cond = PTHREAD_COND_INITIALIZER;
static int stage;

static void set_stage(int value) {
    pthread_mutex_lock(&gate_mutex); stage = value;
    pthread_cond_broadcast(&gate_cond); pthread_mutex_unlock(&gate_mutex);
}
static void wait_stage(int value) {
    pthread_mutex_lock(&gate_mutex);
    while (stage < value) pthread_cond_wait(&gate_cond, &gate_mutex);
    pthread_mutex_unlock(&gate_mutex);
}
__attribute__((noinline)) static bool tagged_cas(Head *expected, Head desired) {
    uint64_t old_ptr, old_epoch, status;
    do {
        // 128-bit exclusivity granule: pointer and epoch change atomically.
        __asm__ volatile("ldaxp %0,%1,[%2]"
                         : "=&r"(old_ptr), "=&r"(old_epoch)
                         : "r"(&tagged_head) : "memory");
        if (old_ptr != (uint64_t)expected->ptr || old_epoch != expected->epoch) {
            __asm__ volatile("clrex" ::: "memory");
            expected->ptr = (Node *)old_ptr; expected->epoch = old_epoch;
            return false;
        }
        __asm__ volatile("stlxp %w0,%1,%2,[%3]"
                         : "=&r"(status)
                         : "r"((uint64_t)desired.ptr), "r"(desired.epoch), "r"(&tagged_head)
                         : "memory");
    } while (status != 0);
    return true;
}
static void tagged_push(Node *node) {
    Head observed = tagged_head, desired;
    do { node->next = observed.ptr; desired = (Head){node, observed.epoch + 1}; }
    while (!tagged_cas(&observed, desired));
}
static Node *tagged_pop(void) {
    Head observed = tagged_head, desired;
    do { if (!observed.ptr) return NULL; desired = (Head){observed.ptr->next, observed.epoch + 1}; }
    while (!tagged_cas(&observed, desired));
    return observed.ptr;
}
static Node *legacy_pop(void) {
    Node *observed = atomic_load_explicit(&legacy_head, memory_order_acquire);
    while (observed && !atomic_compare_exchange_weak_explicit(&legacy_head, &observed,
            observed->next, memory_order_acq_rel, memory_order_acquire)) {}
    return observed;
}
static void *preempted_pop(void *unused) {
    (void)unused;
    if (fixed_mode) {
        Head expected = tagged_head;
        Node *next = expected.ptr->next;
        set_stage(1); wait_stage(2);
        Head desired = {next, expected.epoch + 1};
        bool accepted = tagged_cas(&expected, desired);
        printf("FIXED_ABA_REJECTED=%s observed_epoch=%llu current_epoch=%llu head_id=%d\n",
               accepted ? "NO" : "YES", (unsigned long long)expected.epoch,
               (unsigned long long)tagged_head.epoch,
               tagged_head.ptr ? tagged_head.ptr->id : -1);
        if (accepted) abort();
    } else {
        Node *expected = atomic_load_explicit(&legacy_head, memory_order_acquire);
        Node *next = expected->next;
        set_stage(1); wait_stage(2);
        bool accepted = atomic_compare_exchange_strong_explicit(&legacy_head, &expected,
                        next, memory_order_acq_rel, memory_order_acquire);
        Node *head = atomic_load_explicit(&legacy_head, memory_order_acquire);
        printf("LEGACY_ABA_ACCEPTED=%s head_id=%d expected_recycled_id=1\n",
               accepted ? "YES" : "NO", head ? head->id : -1);
        if (!accepted || head != &b) abort();
    }
    return NULL;
}
int main(int argc, char **argv) {
    if (argc != 2 || (strcmp(argv[1], "--legacy") && strcmp(argv[1], "--fixed"))) return 64;
    fixed_mode = !strcmp(argv[1], "--fixed");
    a = (Node){&b, 1}; b = (Node){NULL, 2};
    atomic_init(&legacy_head, &a); tagged_head = (Head){&a, 0};
    pthread_t thread;
    if (pthread_create(&thread, NULL, preempted_pop, NULL)) return 70;
    wait_stage(1);
    if (fixed_mode) {
        // A -> B -> empty -> A: address A recycles, but epoch becomes 3.
        if (tagged_pop() != &a || tagged_pop() != &b) abort();
        tagged_push(&a);
    } else {
        // Same ABA sequence with an untagged pointer CAS.
        if (legacy_pop() != &a || legacy_pop() != &b) abort();
        a.next = NULL;
        atomic_store_explicit(&legacy_head, &a, memory_order_release);
    }
    set_stage(2);
    pthread_join(thread, NULL);
    if (fixed_mode && (tagged_head.ptr != &a || tagged_head.epoch != 3)) abort();
    return 0;
}
