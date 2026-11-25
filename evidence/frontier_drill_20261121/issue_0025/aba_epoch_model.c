#define _GNU_SOURCE
#include <pthread.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#if !defined(__aarch64__)
#error "This evidence test requires native aarch64 LDAXP/STLXP pair CAS"
#endif

typedef struct Node { struct Node *next; int id; } Node;
typedef struct __attribute__((aligned(16))) {
    Node *ptr;
    uint64_t epoch;
} TaggedHead;
_Static_assert(sizeof(TaggedHead) == 16, "pair CAS must be exactly 128 bits");
_Static_assert(sizeof(((TaggedHead *)0)->epoch) == 8, "epoch must be 64 bits");

/* Load a 128-bit head with acquire semantics using one exclusive pair load. */
static inline TaggedHead tagged_load_acquire(TaggedHead *addr) {
    uint64_t ptr, epoch;
    __asm__ volatile("ldaxp %0, %1, [%2]"
                     : "=&r"(ptr), "=&r"(epoch)
                     : "r"(addr)
                     : "memory");
    TaggedHead out = {.ptr = (Node *)(uintptr_t)ptr, .epoch = epoch};
    return out;
}

/*
 * Native aarch64 128-bit compare-and-swap.
 * LDAXP provides the acquire half; STLXP provides release and retries while
 * exclusive. A nonmatching pair exits without a store and returns the observed
 * head just like atomic_compare_exchange. No mutex or libatomic fallback.
 */
static inline bool tagged_cas(TaggedHead *addr, TaggedHead *expected,
                              TaggedHead desired) {
    uint64_t seen_ptr, seen_epoch;
    uint64_t expected_ptr = (uint64_t)(uintptr_t)expected->ptr;
    uint64_t expected_epoch = expected->epoch;
    uint64_t desired_ptr = (uint64_t)(uintptr_t)desired.ptr;
    uint64_t desired_epoch = desired.epoch;
    uint32_t status = 1;
    __asm__ volatile(
        "1:\n"
        "ldaxp %0, %1, [%3]\n"
        "cmp %0, %4\n"
        "ccmp %1, %5, #0, eq\n"
        "b.ne 2f\n"
        "stlxp %w2, %6, %7, [%3]\n"
        "cbnz %w2, 1b\n"
        "2:\n"
        : "=&r"(seen_ptr), "=&r"(seen_epoch), "+r"(status)
        : "r"(addr), "r"(expected_ptr), "r"(expected_epoch),
          "r"(desired_ptr), "r"(desired_epoch)
        : "memory", "cc");
    bool matched = seen_ptr == expected_ptr && seen_epoch == expected_epoch;
    expected->ptr = (Node *)(uintptr_t)seen_ptr;
    expected->epoch = seen_epoch;
    return matched && status == 0;
}

/* Pointer-only legacy negative control. */
static _Atomic(Node *) legacy_head;
static _Atomic int legacy_phase;
static Node legacy_a, legacy_b, legacy_c;
static bool legacy_suspended_cas;
static Node *legacy_stale_next;

static void *legacy_suspended_pop(void *unused) {
    (void)unused;
    Node *old = atomic_load_explicit(&legacy_head, memory_order_acquire);
    Node *next = old->next;
    legacy_stale_next = next;
    atomic_store_explicit(&legacy_phase, 1, memory_order_release);
    while (atomic_load_explicit(&legacy_phase, memory_order_acquire) != 2) {}
    /* old is A again, so pointer-only CAS incorrectly accepts stale next=B. */
    legacy_suspended_cas = atomic_compare_exchange_strong_explicit(
        &legacy_head, &old, next, memory_order_acq_rel, memory_order_acquire);
    return NULL;
}

static int run_legacy(void) {
    legacy_a = (Node){.next = &legacy_b, .id = 1};
    legacy_b = (Node){.next = &legacy_c, .id = 2};
    legacy_c = (Node){.next = NULL, .id = 3};
    atomic_store(&legacy_head, &legacy_a);
    atomic_store(&legacy_phase, 0);
    legacy_suspended_cas = false;
    pthread_t thread;
    if (pthread_create(&thread, NULL, legacy_suspended_pop, NULL) != 0) return 2;
    while (atomic_load_explicit(&legacy_phase, memory_order_acquire) != 1) {}
    /* Other consumer: pop A, pop B, then recycle A above C. */
    Node *a = atomic_load(&legacy_head);
    atomic_store(&legacy_head, a->next);
    Node *b = atomic_load(&legacy_head);
    atomic_store(&legacy_head, b->next);
    legacy_a.next = &legacy_c;
    atomic_store(&legacy_head, &legacy_a);
    atomic_store_explicit(&legacy_phase, 2, memory_order_release);
    pthread_join(thread, NULL);
    Node *head = atomic_load(&legacy_head);
    bool reproduced = legacy_suspended_cas && legacy_stale_next == &legacy_b && head == &legacy_b;
    printf("LEGACY_POINTER_ABA_REPRODUCED=%s stale_next=B final_head=%s expected_uncorrupted_head=A\n",
           reproduced ? "YES" : "NO", head == &legacy_b ? "B" : "OTHER");
    return reproduced ? 0 : 3;
}

/* Tagged fixed path with the exact same suspended-pop schedule. */
static TaggedHead fixed_head;
static _Atomic int fixed_phase;
static Node fixed_a, fixed_b, fixed_c;
static bool fixed_suspended_cas;
static TaggedHead fixed_observed_after_cas;
static Node *fixed_stale_next;

static void tagged_pop(Node **out) {
    TaggedHead old = tagged_load_acquire(&fixed_head);
    for (;;) {
        Node *next = old.ptr->next;
        TaggedHead desired = {.ptr = next, .epoch = old.epoch + 1};
        if (tagged_cas(&fixed_head, &old, desired)) { *out = old.ptr; return; }
    }
}

static void tagged_push_a(void) {
    TaggedHead old = tagged_load_acquire(&fixed_head);
    for (;;) {
        fixed_a.next = old.ptr;
        TaggedHead desired = {.ptr = &fixed_a, .epoch = old.epoch + 1};
        if (tagged_cas(&fixed_head, &old, desired)) return;
    }
}

static void *fixed_suspended_pop(void *unused) {
    (void)unused;
    TaggedHead old = tagged_load_acquire(&fixed_head);
    Node *next = old.ptr->next;
    fixed_stale_next = next;
    atomic_store_explicit(&fixed_phase, 1, memory_order_release);
    while (atomic_load_explicit(&fixed_phase, memory_order_acquire) != 2) {}
    TaggedHead desired = {.ptr = next, .epoch = old.epoch + 1};
    fixed_suspended_cas = tagged_cas(&fixed_head, &old, desired);
    fixed_observed_after_cas = old;
    return NULL;
}

static int run_fixed_once(void) {
    fixed_a = (Node){.next = &fixed_b, .id = 1};
    fixed_b = (Node){.next = &fixed_c, .id = 2};
    fixed_c = (Node){.next = NULL, .id = 3};
    fixed_head = (TaggedHead){.ptr = &fixed_a, .epoch = 0};
    atomic_store(&fixed_phase, 0);
    fixed_suspended_cas = true;
    pthread_t thread;
    if (pthread_create(&thread, NULL, fixed_suspended_pop, NULL) != 0) return 2;
    while (atomic_load_explicit(&fixed_phase, memory_order_acquire) != 1) {}
    Node *popped;
    tagged_pop(&popped);             /* epoch 0 -> 1, head B */
    tagged_pop(&popped);             /* epoch 1 -> 2, head C */
    tagged_push_a();                 /* epoch 2 -> 3, recycled A -> C */
    atomic_store_explicit(&fixed_phase, 2, memory_order_release);
    pthread_join(thread, NULL);
    TaggedHead head = tagged_load_acquire(&fixed_head);
    bool rejected = !fixed_suspended_cas && fixed_stale_next == &fixed_b &&
                    fixed_observed_after_cas.ptr == &fixed_a &&
                    fixed_observed_after_cas.epoch == 3 && head.ptr == &fixed_a && head.epoch == 3;
    printf("FIXED_TAGGED_ABA_REJECTED=%s stale_next=B final_head=A suspended_epoch=0 observed_epoch=%llu\n",
           rejected ? "YES" : "NO", (unsigned long long)fixed_observed_after_cas.epoch);
    if (!rejected) return 3;
    /* Retry from the observed current head: A->C is the correct next link. */
    TaggedHead desired = {.ptr = head.ptr->next, .epoch = head.epoch + 1};
    bool retry = tagged_cas(&fixed_head, &head, desired);
    head = tagged_load_acquire(&fixed_head);
    bool retry_ok = retry && head.ptr == &fixed_c && head.epoch == 4;
    printf("FIXED_RETRY_FROM_CURRENT_HEAD=%s final_head=C epoch=%llu\n",
           retry_ok ? "PASS" : "FAIL", (unsigned long long)head.epoch);
    return retry_ok ? 0 : 4;
}

static int run_stress(unsigned iterations) {
    unsigned rejected = 0;
    for (unsigned i = 0; i < iterations; ++i) {
        Node a = {.next = NULL, .id = 1}, b = {.next = NULL, .id = 2}, c = {.next = NULL, .id = 3};
        a.next = &b; b.next = &c;
        TaggedHead head = {.ptr = &a, .epoch = 0};
        TaggedHead suspended = tagged_load_acquire(&head);
        Node *stale_next = suspended.ptr->next;
        /* Execute the other consumer's two pops and A recycle with real CAS. */
        for (int pop = 0; pop < 2; ++pop) {
            TaggedHead old = tagged_load_acquire(&head);
            TaggedHead desired = {.ptr = old.ptr->next, .epoch = old.epoch + 1};
            if (!tagged_cas(&head, &old, desired)) return 5;
        }
        TaggedHead old = tagged_load_acquire(&head);
        a.next = old.ptr;
        TaggedHead recycled = {.ptr = &a, .epoch = old.epoch + 1};
        if (!tagged_cas(&head, &old, recycled)) return 6;
        TaggedHead desired = {.ptr = stale_next, .epoch = suspended.epoch + 1};
        if (!tagged_cas(&head, &suspended, desired) && suspended.epoch == 3 &&
            tagged_load_acquire(&head).ptr == &a) rejected++;
    }
    printf("FIXED_TAGGED_ABA_STRESS=%s iterations=%u rejected=%u epoch_bits=64 cas_width_bits=128\n",
           rejected == iterations ? "PASS" : "FAIL", iterations, rejected);
    return rejected == iterations ? 0 : 7;
}

int main(int argc, char **argv) {
    const char *mode = argc > 1 ? argv[1] : "all";
    puts("NATIVE_AARCH64_PAIR_CAS=LDAXP_STLXP EPOCH_GENERATION_BITS=64");
    if (strcmp(mode, "legacy") == 0) return run_legacy();
    if (strcmp(mode, "fixed") == 0) return run_fixed_once();
    if (strcmp(mode, "stress") == 0) return run_stress(100000);
    if (strcmp(mode, "all") != 0) return 8;
    int legacy = run_legacy();
    int fixed = run_fixed_once();
    int stress = run_stress(100000);
    if (legacy == 0 && fixed == 0 && stress == 0) {
        puts("FRONTIER_GH_0025_PASS=YES legacy_aba=REPRODUCED tagged_aba=REJECTED");
        return 0;
    }
    return 9;
}
