#define _GNU_SOURCE
#include "epoll_server.h"

#include <arpa/inet.h>
#include <errno.h>
#include <pthread.h>
#include <sched.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/epoll.h>
#include <sys/eventfd.h>
#include <sys/socket.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>

#define WORKERS 4
#define PRODUCERS 4
#define PER_PRODUCER 20000

static void die(const char *what)
{
    perror(what);
    exit(1);
}

static void sleep_ms(long ms)
{
    struct timespec ts = { .tv_sec = ms / 1000, .tv_nsec = (ms % 1000) * 1000000L };
    while (nanosleep(&ts, &ts) && errno == EINTR)
        ;
}

static int make_listener(uint16_t *port)
{
    struct sockaddr_in addr = { .sin_family = AF_INET, .sin_addr.s_addr = htonl(INADDR_LOOPBACK) };
    socklen_t len = sizeof(addr);
    int fd = socket(AF_INET, SOCK_STREAM | SOCK_NONBLOCK | SOCK_CLOEXEC, 0);
    int one = 1;

    if (fd < 0)
        die("socket listener");
    if (setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one)) ||
        bind(fd, (struct sockaddr *)&addr, sizeof(addr)) ||
        listen(fd, 128) || getsockname(fd, (struct sockaddr *)&addr, &len))
        die("bind/listen");
    *port = ntohs(addr.sin_port);
    return fd;
}

static int connect_client(uint16_t port)
{
    struct sockaddr_in addr = {
        .sin_family = AF_INET,
        .sin_port = htons(port),
        .sin_addr.s_addr = htonl(INADDR_LOOPBACK),
    };
    int fd = socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0);

    if (fd < 0 || connect(fd, (struct sockaddr *)&addr, sizeof(addr)))
        die("connect client");
    return fd;
}

typedef struct {
    int epfd;
    int listen_fd;
    int stop_fd;
    fd_queue *queue;
    _Atomic int *ready;
    _Atomic int *go;
    _Atomic int *tid;
    _Atomic int *wakeups;
    _Atomic int *accepted;
    _Atomic int *wouldblock;
} worker_arg;

static void *accept_worker(void *opaque)
{
    worker_arg *a = opaque;
    struct epoll_event events[4];

    atomic_store_explicit(a->tid, (int)syscall(SYS_gettid), memory_order_release);
    atomic_fetch_add_explicit(a->ready, 1, memory_order_release);
    while (!atomic_load_explicit(a->go, memory_order_acquire))
        sched_yield();

    for (;;) {
        int n = epoll_wait(a->epfd, events, 4, 10000);
        if (n < 0 && errno == EINTR)
            continue;
        if (n <= 0) {
            fprintf(stderr, "epoll_wait failed/timed out\n");
            exit(2);
        }
        for (int i = 0; i < n; i++) {
            if (events[i].data.fd == a->stop_fd) {
                uint64_t value;
                (void)read(a->stop_fd, &value, sizeof(value));
                return NULL;
            }
            if (events[i].data.fd == a->listen_fd) {
                atomic_fetch_add_explicit(a->wakeups, 1, memory_order_relaxed);
                for (;;) {
                    int fd = accept4(a->listen_fd, NULL, NULL, SOCK_NONBLOCK | SOCK_CLOEXEC);
                    if (fd >= 0) {
                        atomic_fetch_add_explicit(a->accepted, 1, memory_order_relaxed);
                        if (fd_queue_push(a->queue, fd))
                            die("fd_queue_push");
                        return NULL;
                    }
                    if (errno == EAGAIN || errno == EWOULDBLOCK) {
                        atomic_fetch_add_explicit(a->wouldblock, 1, memory_order_relaxed);
                        break;
                    }
                    if (errno == EINTR)
                        continue;
                    die("accept4");
                }
            }
        }
    }
}

static void wait_until_in_epoll(_Atomic int *tid_ref)
{
    for (;;) {
        int tid = atomic_load_explicit(tid_ref, memory_order_acquire);
        if (tid > 0) {
            char path[128];
            long syscall_nr = -1;
            snprintf(path, sizeof(path), "/proc/self/task/%d/syscall", tid);
            FILE *f = fopen(path, "r");
            if (f) {
                (void)fscanf(f, "%ld", &syscall_nr);
                fclose(f);
            }
            if (syscall_nr == SYS_epoll_pwait)
                return;
#ifdef SYS_epoll_pwait2
            if (syscall_nr == SYS_epoll_pwait2)
                return;
#endif
        }
        sched_yield();
    }
}

static int run_epoll_case(int exclusive, int *observed_wouldblock)
{
    uint16_t port;
    int listener = make_listener(&port);
    int client = -1;
    int epfd[WORKERS], stopfd[WORKERS];
    pthread_t threads[WORKERS];
    worker_arg args[WORKERS];
    fd_queue queue;
    _Atomic int ready = 0, go = 0, wakeups = 0, accepted = 0, wouldblock = 0;
    _Atomic int tids[WORKERS] = {0};

    fd_queue_init(&queue);
    for (int i = 0; i < WORKERS; i++) {
        struct epoll_event stop_ev;
        epfd[i] = epoll_create1(EPOLL_CLOEXEC);
        stopfd[i] = eventfd(0, EFD_CLOEXEC | EFD_NONBLOCK);
        if (epfd[i] < 0 || stopfd[i] < 0)
            die("epoll_create1/eventfd");
        stop_ev = (struct epoll_event){ .events = EPOLLIN, .data.fd = stopfd[i] };
        if (epoll_ctl(epfd[i], EPOLL_CTL_ADD, stopfd[i], &stop_ev))
            die("epoll_ctl stopfd");
        if (exclusive) {
            if (epoll_add_exclusive_listener(epfd[i], listener, 0))
                die("EPOLLEXCLUSIVE registration");
        } else {
            struct epoll_event ev = { .events = EPOLLIN, .data.fd = listener };
            if (epoll_ctl(epfd[i], EPOLL_CTL_ADD, listener, &ev))
                die("baseline registration");
        }
        args[i] = (worker_arg){
            .epfd = epfd[i], .listen_fd = listener, .stop_fd = stopfd[i],
            .queue = &queue, .ready = &ready, .go = &go, .wakeups = &wakeups,
            .accepted = &accepted, .wouldblock = &wouldblock, .tid = &tids[i],
        };
        if (pthread_create(&threads[i], NULL, accept_worker, &args[i]))
            die("pthread_create");
    }
    while (atomic_load_explicit(&ready, memory_order_acquire) != WORKERS)
        sched_yield();
    atomic_store_explicit(&go, 1, memory_order_release);
    for (int i = 0; i < WORKERS; i++)
        wait_until_in_epoll(&tids[i]);
    client = connect_client(port);
    struct timespec wait_start, wait_now;
    clock_gettime(CLOCK_MONOTONIC, &wait_start);
    for (;;) {
        if (atomic_load(&accepted) == 1)
            break;
        clock_gettime(CLOCK_MONOTONIC, &wait_now);
        double elapsed = (wait_now.tv_sec - wait_start.tv_sec) +
                         (wait_now.tv_nsec - wait_start.tv_nsec) / 1000000000.0;
        if (elapsed >= 3.0) {
            fprintf(stderr, "worker completion timeout in %s case\n",
                    exclusive ? "exclusive" : "baseline");
            break;
        }
        sched_yield();
    }
    /* Allow any inadmissible extra wakeup to become visible before release. */
    sleep_ms(250);

    int wakes = atomic_load(&wakeups);
    int accepts = atomic_load(&accepted);
    int blocks = atomic_load(&wouldblock);
    for (int i = 0; i < WORKERS; i++) {
        uint64_t one = 1;
        if (write(stopfd[i], &one, sizeof(one)) != sizeof(one))
            die("eventfd release");
    }
    for (int i = 0; i < WORKERS; i++) {
        pthread_join(threads[i], NULL);
        close(stopfd[i]);
        close(epfd[i]);
    }
    close(client);
    close(listener);

    if (accepts != 1) {
        fprintf(stderr, "accepted=%d, expected exactly one\n", accepts);
        return 1;
    }
    int queued = fd_queue_pop(&queue);
    if (queued < 0) {
        fprintf(stderr, "accepted fd did not reach lock-free queue\n");
        return 1;
    }
    close(queued);
    if (fd_queue_pop(&queue) != -EAGAIN) {
        fprintf(stderr, "duplicate accepted fd in queue\n");
        return 1;
    }
    fd_queue_destroy(&queue);

    printf("%s: wakeups=%d accepted=%d EWOULDBLOCK=%d\n",
           exclusive ? "EPOLLEXCLUSIVE" : "baseline", wakes, accepts, blocks);
    *observed_wouldblock = blocks;
    if (exclusive)
        return wakes == 1 && blocks == 0 ? 0 : 1;
    return wakes >= 2 && blocks == wakes - 1 ? 0 : 1;
}

typedef struct {
    fd_queue *queue;
    int producer;
    _Atomic int *start;
} producer_arg;

static void *producer(void *opaque)
{
    producer_arg *a = opaque;
    while (!atomic_load_explicit(a->start, memory_order_acquire))
        sched_yield();
    for (int i = 0; i < PER_PRODUCER; i++) {
        int id = a->producer * PER_PRODUCER + i + 1;
        if (fd_queue_push(a->queue, id))
            die("stress push");
    }
    return NULL;
}

static int test_lockfree_queue(void)
{
    fd_queue queue;
    pthread_t threads[PRODUCERS];
    producer_arg args[PRODUCERS];
    _Atomic int start = 0;
    int expected[PRODUCERS] = {0};

    fd_queue_init(&queue);
    for (int p = 0; p < PRODUCERS; p++) {
        args[p] = (producer_arg){ .queue = &queue, .producer = p, .start = &start };
        if (pthread_create(&threads[p], NULL, producer, &args[p]))
            die("stress pthread_create");
    }
    atomic_store_explicit(&start, 1, memory_order_release);
    for (int received = 0; received < PRODUCERS * PER_PRODUCER;) {
        int id = fd_queue_pop(&queue);
        if (id == -EAGAIN) {
            sched_yield();
            continue;
        }
        int p = (id - 1) / PER_PRODUCER;
        int sequence = (id - 1) % PER_PRODUCER;
        if (p < 0 || p >= PRODUCERS || sequence != expected[p]++) {
            fprintf(stderr, "queue ordering corruption id=%d\n", id);
            return 1;
        }
        received++;
    }
    for (int p = 0; p < PRODUCERS; p++)
        pthread_join(threads[p], NULL);
    if (fd_queue_pop(&queue) != -EAGAIN)
        return 1;
    fd_queue_destroy(&queue);
    printf("MPSC queue: %d/%d unique ordered transfers, no mutexes\n",
           PRODUCERS * PER_PRODUCER, PRODUCERS * PER_PRODUCER);
    return 0;
}

static int test_registration_validation(void)
{
    uint16_t port;
    int listener = make_listener(&port);
    int epfd = epoll_create1(EPOLL_CLOEXEC);
    int failed = 0;

    errno = 0;
    if (epoll_add_exclusive_listener(epfd, listener, EPOLLONESHOT) != -1 || errno != EINVAL)
        failed = 1;
    errno = 0;
    if (epoll_add_exclusive_listener(epfd, listener, EPOLLPRI) != -1 || errno != EINVAL)
        failed = 1;
    close(epfd);
    close(listener);
    printf("registration validation: ONESHOT and unsupported EPOLLPRI rejected EINVAL\n");
    return failed;
}

int main(void)
{
    int rc = 0, blocks = 0;

    printf("native epoll regression on aarch64, kernel EPOLLEXCLUSIVE bit=%u\n", EPOLLEXCLUSIVE);
    rc |= test_registration_validation();
    rc |= run_epoll_case(0, &blocks);
    rc |= run_epoll_case(1, &blocks);
    rc |= test_lockfree_queue();
    if (rc) {
        fprintf(stderr, "FRONTIER-GH-0004: FAIL\n");
        return 1;
    }
    printf("FRONTIER-GH-0004: PASS baseline reproduced; exclusive single-wakeup + lock-free distribution verified\n");
    return 0;
}
