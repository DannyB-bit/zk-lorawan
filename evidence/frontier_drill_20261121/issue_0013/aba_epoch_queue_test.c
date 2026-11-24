#define _GNU_SOURCE
#include <inttypes.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct Node { int value; struct Node *next; } Node;
typedef union TaggedHead {
    __int128 raw;
    struct { Node *ptr; uint64_t epoch; } s;
} TaggedHead;

static pthread_mutex_t gate = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t cv = PTHREAD_COND_INITIALIZER;
static int loaded, resume_worker;

static void signal_flag(volatile int *flag) {
    pthread_mutex_lock(&gate); *flag = 1;
    pthread_cond_broadcast(&cv); pthread_mutex_unlock(&gate);
}
static void wait_flag(volatile int *flag) {
    pthread_mutex_lock(&gate);
    while (!*flag) pthread_cond_wait(&cv, &gate);
    pthread_mutex_unlock(&gate);
}
static TaggedHead tagged_load(TaggedHead *h) {
    TaggedHead v; v.raw = __atomic_load_n(&h->raw, __ATOMIC_ACQUIRE); return v;
}
static int tagged_cas(TaggedHead *h, TaggedHead *expected, TaggedHead desired) {
    return __atomic_compare_exchange_n(&h->raw, &expected->raw, desired.raw, 0,
                                       __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE);
}

typedef struct {
    Node *head, *observed_next; TaggedHead tagged_head, tagged_expected;
    int fixed, stale_cas_success, retry_pop_success; uint64_t retry_epoch;
} Worker;

static void *preempted_pop(void *arg) {
    Worker *w = arg;
    if (w->fixed) {
        w->tagged_expected = tagged_load(&w->tagged_head);
        w->observed_next = w->tagged_expected.s.ptr->next;
    } else {
        w->head = __atomic_load_n(&w->head, __ATOMIC_ACQUIRE);
        w->observed_next = w->head->next;
    }
    signal_flag(&loaded); wait_flag(&resume_worker);
    if (w->fixed) {
        TaggedHead desired = {.s={.ptr=w->observed_next,
                                  .epoch=w->tagged_expected.s.epoch + 1}};
        w->stale_cas_success = tagged_cas(&w->tagged_head,
                                          &w->tagged_expected, desired);
        if (!w->stale_cas_success) {
            /* CAS returned the current head in expected; retry from a consistent snapshot. */
            w->retry_epoch = w->tagged_expected.s.epoch;
            TaggedHead next = {.s={.ptr=w->tagged_expected.s.ptr->next,
                                   .epoch=w->tagged_expected.s.epoch + 1}};
            w->retry_pop_success = tagged_cas(&w->tagged_head,
                                              &w->tagged_expected, next);
        }
    } else {
        Node *expected = w->head;
        w->stale_cas_success = __atomic_compare_exchange_n(&w->head, &expected,
            w->observed_next, 0, __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE);
    }
    return NULL;
}

static int run_aba(int fixed) {
    Node a={.value=10}, b={.value=20}, c={.value=30};
    a.next=&b; b.next=&c; c.next=NULL;
    Worker w; memset(&w,0,sizeof(w)); w.fixed=fixed; w.head=&a;
    if (fixed) { TaggedHead initial={.s={.ptr=&a,.epoch=0}}; w.tagged_head=initial; }
    loaded=resume_worker=0;
    pthread_t thread;
    if (pthread_create(&thread,NULL,preempted_pop,&w)) return 90;
    wait_flag(&loaded);

    /* Other consumer pops A then B, then recycles A at the head. */
    if (fixed) {
        TaggedHead *h=&w.tagged_head, exp, des;
        exp=tagged_load(h); des=(TaggedHead){.s={.ptr=&b,.epoch=exp.s.epoch+1}};
        if (!tagged_cas(h,&exp,des)) return 91;
        exp=des;
        des=(TaggedHead){.s={.ptr=&c,.epoch=exp.s.epoch+1}};
        if (!tagged_cas(h,&exp,des)) return 92;
        exp=des;
        a.next=&c;
        des=(TaggedHead){.s={.ptr=&a,.epoch=exp.s.epoch+1}};
        if (!tagged_cas(h,&exp,des)) return 93;
    } else {
        if (!__atomic_compare_exchange_n(&w.head,&(Node *){&a},&b,0,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE)) return 91;
        if (!__atomic_compare_exchange_n(&w.head,&(Node *){&b},&c,0,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE)) return 92;
        a.next=&c;
        if (!__atomic_compare_exchange_n(&w.head,&(Node *){&c},&a,0,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE)) return 93;
    }
    b.next=&b; /* recycled node's poisoned link exposes resurrection as a cycle */
    signal_flag(&resume_worker); pthread_join(thread,NULL);

    Node *final_ptr = fixed ? tagged_load(&w.tagged_head).s.ptr : w.head;
    uint64_t final_epoch = fixed ? tagged_load(&w.tagged_head).s.epoch : 0;
    printf("MODE=%s STALE_CAS_SUCCESS=%d RETRY_POP_SUCCESS=%d RETRY_EPOCH=%" PRIu64
           " FINAL_VALUE=%d FINAL_EPOCH=%" PRIu64 " B_SELF_CYCLE=%d\n",
           fixed?"tagged":"legacy",w.stale_cas_success,w.retry_pop_success,
           w.retry_epoch,final_ptr?final_ptr->value:-1,final_epoch,b.next==&b);
    if (fixed) {
        int ok=!w.stale_cas_success && w.retry_pop_success && w.retry_epoch==3 &&
               final_ptr==&c && final_epoch==4;
        printf("ABA_TAGGED_EPOCH_PASS=%s\n",ok?"YES":"NO"); return ok?0:1;
    }
    int ok=w.stale_cas_success && final_ptr==&b && b.next==&b;
    printf("LEGACY_ABA_REPRODUCED=%s\n",ok?"YES":"NO"); return ok?0:1;
}

static int run_baseline(void) {
    Node a={.value=1}, b={.value=2}; a.next=&b; b.next=NULL;
    TaggedHead h={.s={.ptr=&a,.epoch=0}};
    TaggedHead exp=tagged_load(&h), des={.s={.ptr=&b,.epoch=exp.s.epoch+1}};
    if (!tagged_cas(&h,&exp,des)) return 1;
    exp=tagged_load(&h); des=(TaggedHead){.s={.ptr=&a,.epoch=exp.s.epoch+1}};
    a.next=NULL;
    if (!tagged_cas(&h,&exp,des)) return 1;
    TaggedHead final=tagged_load(&h);
    int ok=final.s.ptr==&a && final.s.epoch==2 && a.next==NULL;
    printf("BASELINE_PASS=%s FINAL_EPOCH=%" PRIu64 "\n",ok?"YES":"NO",final.s.epoch);
    return ok?0:1;
}

int main(int argc,char **argv) {
    if (argc!=2) return 64;
    if (!strcmp(argv[1],"legacy")) return run_aba(0);
    if (!strcmp(argv[1],"tagged")) return run_aba(1);
    if (!strcmp(argv[1],"baseline")) return run_baseline();
    return 64;
}
