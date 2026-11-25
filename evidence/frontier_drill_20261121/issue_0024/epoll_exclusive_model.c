#define _GNU_SOURCE
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <pthread.h>
#include <sched.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/epoll.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <unistd.h>

#define CLIENTS 256
#define ACCEPTERS 4
#define CONSUMERS 4
#define QUEUE_CAP 1024

typedef struct { _Atomic size_t seq; int fd; } cell_t;
typedef struct {
    cell_t cells[QUEUE_CAP];
    _Atomic size_t enq;
    _Atomic size_t deq;
} fd_queue_t;

typedef struct {
    int listen_fd;
    bool exclusive;
    fd_queue_t queue;
    _Atomic int stop;
    _Atomic int accepted;
    _Atomic int consumed;
    _Atomic int errors;
    int wakeups[ACCEPTERS];
    int empty_wakeups[ACCEPTERS];
    int accepted_by[ACCEPTERS];
} scenario_t;

typedef struct { scenario_t *s; int index; } accept_arg_t;

static void queue_init(fd_queue_t *q) {
    atomic_init(&q->enq, 0);
    atomic_init(&q->deq, 0);
    for (size_t i = 0; i < QUEUE_CAP; ++i) {
        atomic_init(&q->cells[i].seq, i);
        q->cells[i].fd = -1;
    }
}

/* Vyukov-style bounded MPMC queue: no mutex, no conditional lock fallback. */
static bool queue_push(fd_queue_t *q, int fd) {
    size_t pos = atomic_load_explicit(&q->enq, memory_order_relaxed);
    cell_t *cell;
    for (;;) {
        cell = &q->cells[pos & (QUEUE_CAP - 1)];
        size_t seq = atomic_load_explicit(&cell->seq, memory_order_acquire);
        intptr_t dif = (intptr_t)seq - (intptr_t)pos;
        if (dif == 0) {
            if (atomic_compare_exchange_weak_explicit(&q->enq, &pos, pos + 1,
                    memory_order_relaxed, memory_order_relaxed)) break;
        } else if (dif < 0) {
            return false;
        } else {
            pos = atomic_load_explicit(&q->enq, memory_order_relaxed);
        }
    }
    cell->fd = fd;
    atomic_store_explicit(&cell->seq, pos + 1, memory_order_release);
    return true;
}

static bool queue_pop(fd_queue_t *q, int *fd) {
    size_t pos = atomic_load_explicit(&q->deq, memory_order_relaxed);
    cell_t *cell;
    for (;;) {
        cell = &q->cells[pos & (QUEUE_CAP - 1)];
        size_t seq = atomic_load_explicit(&cell->seq, memory_order_acquire);
        intptr_t dif = (intptr_t)seq - (intptr_t)(pos + 1);
        if (dif == 0) {
            if (atomic_compare_exchange_weak_explicit(&q->deq, &pos, pos + 1,
                    memory_order_relaxed, memory_order_relaxed)) break;
        } else if (dif < 0) {
            return false;
        } else {
            pos = atomic_load_explicit(&q->deq, memory_order_relaxed);
        }
    }
    *fd = cell->fd;
    atomic_store_explicit(&cell->seq, pos + QUEUE_CAP, memory_order_release);
    return true;
}

static void *consumer_main(void *opaque) {
    scenario_t *s = opaque;
    while (!atomic_load_explicit(&s->stop, memory_order_acquire) &&
           atomic_load_explicit(&s->consumed, memory_order_acquire) < CLIENTS) {
        int fd;
        if (!queue_pop(&s->queue, &fd)) { sched_yield(); continue; }
        char byte = 0;
        ssize_t n = read(fd, &byte, 1);
        if (n != 1 || byte != 'Z') atomic_fetch_add(&s->errors, 1);
        if (close(fd) != 0) atomic_fetch_add(&s->errors, 1);
        atomic_fetch_add_explicit(&s->consumed, 1, memory_order_release);
    }
    return NULL;
}

static void *accept_main(void *opaque) {
    accept_arg_t *arg = opaque;
    scenario_t *s = arg->s;
    int ep = epoll_create1(EPOLL_CLOEXEC);
    if (ep < 0) { atomic_fetch_add(&s->errors, 1); return NULL; }
    struct epoll_event reg = {.events = EPOLLIN | (s->exclusive ? EPOLLEXCLUSIVE : 0),
                              .data.u32 = (uint32_t)arg->index};
    if (epoll_ctl(ep, EPOLL_CTL_ADD, s->listen_fd, &reg) != 0) {
        atomic_fetch_add(&s->errors, 1); close(ep); return NULL;
    }
    while (!atomic_load_explicit(&s->stop, memory_order_acquire)) {
        struct epoll_event events[4];
        int n = epoll_wait(ep, events, 4, 10);
        if (n < 0) {
            if (errno == EINTR) continue;
            atomic_fetch_add(&s->errors, 1); break;
        }
        for (int i = 0; i < n; ++i) {
            s->wakeups[arg->index]++;
            bool accepted_this_wakeup = false;
            for (;;) {
                int fd = accept4(s->listen_fd, NULL, NULL, SOCK_CLOEXEC);
                if (fd >= 0) {
                    accepted_this_wakeup = true;
                    s->accepted_by[arg->index]++;
                    atomic_fetch_add_explicit(&s->accepted, 1, memory_order_release);
                    struct timeval tv = {.tv_sec = 2, .tv_usec = 0};
                    if (setsockopt(fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv)) != 0)
                        atomic_fetch_add(&s->errors, 1);
                    if (!queue_push(&s->queue, fd)) {
                        atomic_fetch_add(&s->errors, 1); close(fd);
                    }
                    continue;
                }
                if (errno == EAGAIN || errno == EWOULDBLOCK) {
                    if (!accepted_this_wakeup) s->empty_wakeups[arg->index]++;
                    break;
                }
                if (errno == EINTR) continue;
                if (errno != EBADF && errno != EINVAL) atomic_fetch_add(&s->errors, 1);
                break;
            }
        }
    }
    close(ep);
    return NULL;
}

static int probe_reallocation_contract(void) {
    int fd = socket(AF_INET, SOCK_STREAM | SOCK_NONBLOCK | SOCK_CLOEXEC, 0);
    int ep = epoll_create1(EPOLL_CLOEXEC);
    if (fd < 0 || ep < 0) return 1;
    struct epoll_event ev = {.events = EPOLLIN, .data.u64 = 1};
    if (epoll_ctl(ep, EPOLL_CTL_ADD, fd, &ev) != 0) return 2;
    ev.events = EPOLLIN | EPOLLEXCLUSIVE;
    errno = 0;
    int mod_rc = epoll_ctl(ep, EPOLL_CTL_MOD, fd, &ev);
    int mod_errno = errno;
    if (mod_rc != -1 || mod_errno != EINVAL) {
        fprintf(stderr, "EPOLLEXCLUSIVE MOD unexpectedly rc=%d errno=%d\n", mod_rc, mod_errno);
        return 3;
    }
    if (epoll_ctl(ep, EPOLL_CTL_DEL, fd, NULL) != 0) return 4;
    if (epoll_ctl(ep, EPOLL_CTL_ADD, fd, &ev) != 0) return 5;
    close(ep); close(fd);
    puts("REALLOC_MOD_EXCLUSIVE_REJECTED=YES errno=EINVAL DELETE_READD_EXCLUSIVE=PASS");
    return 0;
}

static int connect_and_send(uint16_t port_net) {
    int fd = socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0);
    if (fd < 0) return 1;
    struct sockaddr_in addr = {.sin_family = AF_INET, .sin_port = port_net};
    addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    if (connect(fd, (struct sockaddr *)&addr, sizeof(addr)) != 0) { close(fd); return 2; }
    char byte = 'Z';
    if (write(fd, &byte, 1) != 1) { close(fd); return 3; }
    if (close(fd) != 0) return 4;
    return 0;
}

static int run_scenario(bool exclusive) {
    scenario_t s;
    memset(&s, 0, sizeof(s));
    s.exclusive = exclusive;
    atomic_init(&s.stop, 0); atomic_init(&s.accepted, 0);
    atomic_init(&s.consumed, 0); atomic_init(&s.errors, 0);
    queue_init(&s.queue);
    s.listen_fd = socket(AF_INET, SOCK_STREAM | SOCK_NONBLOCK | SOCK_CLOEXEC, 0);
    if (s.listen_fd < 0) return 1;
    int one = 1;
    if (setsockopt(s.listen_fd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one)) != 0 ||
        setsockopt(s.listen_fd, SOL_SOCKET, SO_REUSEPORT, &one, sizeof(one)) != 0) return 2;
    struct sockaddr_in addr = {.sin_family = AF_INET, .sin_port = 0};
    addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    if (bind(s.listen_fd, (struct sockaddr *)&addr, sizeof(addr)) != 0 ||
        listen(s.listen_fd, CLIENTS) != 0) return 3;
    socklen_t alen = sizeof(addr);
    if (getsockname(s.listen_fd, (struct sockaddr *)&addr, &alen) != 0) return 4;

    pthread_t consumers[CONSUMERS], accepters[ACCEPTERS];
    accept_arg_t args[ACCEPTERS];
    for (int i = 0; i < CONSUMERS; ++i)
        if (pthread_create(&consumers[i], NULL, consumer_main, &s) != 0) return 5;
    for (int i = 0; i < ACCEPTERS; ++i) {
        args[i] = (accept_arg_t){.s = &s, .index = i};
        if (pthread_create(&accepters[i], NULL, accept_main, &args[i]) != 0) return 6;
    }
    for (int i = 0; i < CLIENTS; ++i) {
        int rc = connect_and_send(addr.sin_port);
        if (rc != 0) { fprintf(stderr, "client %d rc=%d\n", i, rc); atomic_fetch_add(&s.errors, 1); }
    }
    int timed_out = 1;
    for (int i = 0; i < 20000; ++i) {
        if (atomic_load_explicit(&s.consumed, memory_order_acquire) == CLIENTS) { timed_out = 0; break; }
        struct timespec ts = {.tv_sec = 0, .tv_nsec = 1000000};
        nanosleep(&ts, NULL);
    }
    if (timed_out) atomic_fetch_add(&s.errors, 1);
    atomic_store_explicit(&s.stop, 1, memory_order_release);
    for (int i = 0; i < ACCEPTERS; ++i) pthread_join(accepters[i], NULL);
    for (int i = 0; i < CONSUMERS; ++i) pthread_join(consumers[i], NULL);
    close(s.listen_fd);

    int wakeups = 0, empty = 0, per_accept = 0;
    for (int i = 0; i < ACCEPTERS; ++i) {
        wakeups += s.wakeups[i]; empty += s.empty_wakeups[i]; per_accept += s.accepted_by[i];
    }
    int accepted = atomic_load(&s.accepted), consumed = atomic_load(&s.consumed);
    int errors = atomic_load(&s.errors);
    bool pass = !timed_out && errors == 0 && accepted == CLIENTS && consumed == CLIENTS && per_accept == CLIENTS;
    printf("%s flags=%#x clients=%d wakeups=%d empty_wakeups=%d accepted=%d consumed=%d errors=%d timeout=%d RESULT=%s\n",
           exclusive ? "FIXED_EPOLLEXCLUSIVE" : "LEGACY_NO_EXCLUSIVE",
           exclusive ? (unsigned)EPOLLEXCLUSIVE : 0U, CLIENTS, wakeups, empty,
           accepted, consumed, errors, timed_out, pass ? "PASS" : "FAIL");
    return pass ? 0 : 7;
}

int main(int argc, char **argv) {
    const char *mode = argc > 1 ? argv[1] : "all";
    if (!atomic_is_lock_free(&(fd_queue_t){0}.enq) || !atomic_is_lock_free(&(fd_queue_t){0}.deq)) {
        puts("LOCKFREE_SIZE_T=NO"); return 10;
    }
    puts("LOCKFREE_SIZE_T=YES queue=bounded_MPMC_mutex_free");
    if (strcmp(mode, "legacy") == 0) return run_scenario(false);
    if (probe_reallocation_contract() != 0) return 11;
    if (strcmp(mode, "fixed") == 0) return run_scenario(true);
    if (strcmp(mode, "all") != 0) return 12;
    int legacy = run_scenario(false);
    int fixed = run_scenario(true);
    if (legacy == 0 && fixed == 0) {
        printf("FRONTIER_GH_0024_PASS=YES clients_per_mode=%d note=legacy_empty_wakeups_are_measured_not_assumed\n", CLIENTS);
        return 0;
    }
    return 13;
}
