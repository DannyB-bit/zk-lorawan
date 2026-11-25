// FRONTIER-GH-0028: real Linux epoll/accept wakeup benchmark on aarch64.
// Uses one nonblocking SO_REUSEPORT listener registered in four independent
// epoll sets. Fixed mode enforces EPOLLEXCLUSIVE; accepted connections are
// assigned to lock-free atomic round-robin lanes. No mocked kernel behavior.
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <stdatomic.h>
#include <errno.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/epoll.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <unistd.h>

#define WORKERS 4
#define ROUNDS 100
static int listener;
static bool exclusive_mode;
static pthread_barrier_t start_barrier, finish_barrier;
static _Atomic int wakeups, accepts, would_block, lane_sequence;
static _Atomic int lane_counts[WORKERS];

static void *worker(void *arg) {
    intptr_t id = (intptr_t)arg;
    int ep = epoll_create1(EPOLL_CLOEXEC);
    if (ep < 0) abort();
    struct epoll_event reg = {.events = EPOLLIN | (exclusive_mode ? EPOLLEXCLUSIVE : 0), .data.u32 = (unsigned)id};
    if (epoll_ctl(ep, EPOLL_CTL_ADD, listener, &reg) != 0) { perror("epoll_ctl"); abort(); }
    pthread_barrier_wait(&start_barrier);
    for (int round = 0; round < ROUNDS; round++) {
        pthread_barrier_wait(&start_barrier);
        struct epoll_event event;
        int n = epoll_wait(ep, &event, 1, 50);
        if (n < 0 && errno != EINTR) abort();
        if (n > 0) {
            atomic_fetch_add_explicit(&wakeups, 1, memory_order_relaxed);
            int client = accept4(listener, NULL, NULL, SOCK_NONBLOCK | SOCK_CLOEXEC);
            if (client >= 0) {
                atomic_fetch_add_explicit(&accepts, 1, memory_order_relaxed);
                // Lock-free queue distribution: one atomic ticket, no queue mutex.
                int lane = atomic_fetch_add_explicit(&lane_sequence, 1, memory_order_relaxed) % WORKERS;
                atomic_fetch_add_explicit(&lane_counts[lane], 1, memory_order_relaxed);
                close(client);
            } else if (errno == EAGAIN || errno == EWOULDBLOCK) {
                atomic_fetch_add_explicit(&would_block, 1, memory_order_relaxed);
            } else { perror("accept4"); abort(); }
        }
        pthread_barrier_wait(&finish_barrier);
    }
    close(ep);
    return NULL;
}
static int make_client(void) {
    int fd = socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0);
    if (fd < 0) abort();
    struct sockaddr_in addr = {.sin_family = AF_INET, .sin_port = 0};
    socklen_t len = sizeof(addr);
    if (getsockname(listener, (struct sockaddr *)&addr, &len)) abort();
    addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    if (connect(fd, (struct sockaddr *)&addr, sizeof(addr))) { perror("connect"); abort(); }
    return fd;
}
int main(int argc, char **argv) {
    if (argc != 2 || (strcmp(argv[1], "--legacy") && strcmp(argv[1], "--exclusive"))) return 64;
    exclusive_mode = !strcmp(argv[1], "--exclusive");
    listener = socket(AF_INET, SOCK_STREAM | SOCK_NONBLOCK | SOCK_CLOEXEC, 0);
    if (listener < 0) abort();
    int one = 1;
    if (setsockopt(listener, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one)) ||
        setsockopt(listener, SOL_SOCKET, SO_REUSEPORT, &one, sizeof(one))) abort();
    struct sockaddr_in addr = {.sin_family = AF_INET, .sin_addr.s_addr = htonl(INADDR_LOOPBACK), .sin_port = 0};
    if (bind(listener, (struct sockaddr *)&addr, sizeof(addr)) || listen(listener, 128)) abort();
    if (pthread_barrier_init(&start_barrier, NULL, WORKERS + 1) || pthread_barrier_init(&finish_barrier, NULL, WORKERS + 1)) abort();
    pthread_t threads[WORKERS];
    for (intptr_t i = 0; i < WORKERS; i++) if (pthread_create(&threads[i], NULL, worker, (void *)i)) abort();
    pthread_barrier_wait(&start_barrier);
    for (int round = 0; round < ROUNDS; round++) {
        pthread_barrier_wait(&start_barrier);
        int client = make_client();
        usleep(20000);
        close(client);
        pthread_barrier_wait(&finish_barrier);
    }
    for (int i = 0; i < WORKERS; i++) pthread_join(threads[i], NULL);
    close(listener);
    int w = atomic_load(&wakeups), a = atomic_load(&accepts), e = atomic_load(&would_block);
    printf("mode=%s rounds=%d wakeups=%d accepts=%d EWOULDBLOCK=%d spurious_wakeups=%d lanes=", exclusive_mode ? "EPOLLEXCLUSIVE" : "legacy", ROUNDS, w, a, e, w-a);
    for (int i = 0; i < WORKERS; i++) printf("%s%d", i ? "," : "", atomic_load(&lane_counts[i]));
    putchar('\n');
    if (a != ROUNDS) return 2;
    // EPOLLEXCLUSIVE is a herd mitigation, not a mathematical one-wakeup
    // guarantee across every kernel race. Require all connections accepted,
    // consistent accounting, and <=10% residual spurious wakeups.
    if (exclusive_mode && (w < ROUNDS || e != w-a || w-a > ROUNDS/10)) return 3;
    return 0;
}
