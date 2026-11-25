#define _GNU_SOURCE
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/epoll.h>
#include <sys/socket.h>
#include <unistd.h>

#define WORKERS 4
#define ROUNDS 100

typedef struct {
    int fd;
    _Atomic int wakeups;
    _Atomic int accepted;
    _Atomic int eagain;
    _Atomic int release_accept;
    _Atomic int done;
} round_state;

typedef struct {
    int epfd;
    round_state *volatile round;
} worker_arg;

static _Atomic int stop_workers;
static worker_arg args[WORKERS];

static void die(const char *what) { perror(what); exit(2); }

static void *worker(void *opaque) {
    worker_arg *a = opaque;
    while (!atomic_load_explicit(&stop_workers, memory_order_relaxed)) {
        struct epoll_event events[8];
        int n = epoll_wait(a->epfd, events, 8, 10);
        if (n < 0) { if (errno == EINTR) continue; die("epoll_wait"); }
        for (int i = 0; i < n; i++) {
            round_state *r = events[i].data.ptr;
            if (r == NULL || r != a->round) continue;
            atomic_fetch_add_explicit(&r->wakeups, 1, memory_order_release);
            while (!atomic_load_explicit(&r->release_accept, memory_order_acquire))
                ; /* Intentional test barrier: expose every spurious wakeup. */
            int c;
            do { c = accept4(r->fd, NULL, NULL, SOCK_NONBLOCK | SOCK_CLOEXEC); }
            while (c < 0 && errno == EINTR);
            if (c >= 0) {
                atomic_fetch_add_explicit(&r->accepted, 1, memory_order_release);
                close(c);
            } else if (errno == EAGAIN || errno == EWOULDBLOCK) {
                atomic_fetch_add_explicit(&r->eagain, 1, memory_order_release);
            } else { die("accept4"); }
            atomic_fetch_add_explicit(&r->done, 1, memory_order_release);
        }
    }
    return NULL;
}

static int make_listener(uint16_t *port) {
    int fd = socket(AF_INET, SOCK_STREAM | SOCK_NONBLOCK | SOCK_CLOEXEC, 0);
    if (fd < 0) die("socket");
    int one = 1;
    if (setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one)) < 0) die("SO_REUSEADDR");
    if (setsockopt(fd, SOL_SOCKET, SO_REUSEPORT, &one, sizeof(one)) < 0) die("SO_REUSEPORT");
    int got = 0; socklen_t gotlen = sizeof(got);
    if (getsockopt(fd, SOL_SOCKET, SO_REUSEPORT, &got, &gotlen) < 0 || got != 1) {
        fprintf(stderr, "SO_REUSEPORT readback failed\n"); exit(2);
    }
    struct sockaddr_in addr = { .sin_family = AF_INET, .sin_addr.s_addr = htonl(INADDR_LOOPBACK), .sin_port = 0 };
    if (bind(fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) die("bind");
    if (listen(fd, 128) < 0) die("listen");
    socklen_t alen = sizeof(addr);
    if (getsockname(fd, (struct sockaddr *)&addr, &alen) < 0) die("getsockname");
    *port = ntohs(addr.sin_port);
    return fd;
}

static void connect_one(uint16_t port) {
    int fd = socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0);
    if (fd < 0) die("client socket");
    struct sockaddr_in addr = { .sin_family = AF_INET, .sin_addr.s_addr = htonl(INADDR_LOOPBACK), .sin_port = htons(port) };
    if (connect(fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) die("connect");
    close(fd);
}

int main(int argc, char **argv) {
    if (argc != 2 || (strcmp(argv[1], "legacy") && strcmp(argv[1], "fixed"))) {
        fprintf(stderr, "usage: %s legacy|fixed\n", argv[0]); return 2;
    }
    int fixed = !strcmp(argv[1], "fixed");
    pthread_t threads[WORKERS];
    for (int i = 0; i < WORKERS; i++) {
        args[i].epfd = epoll_create1(EPOLL_CLOEXEC);
        if (args[i].epfd < 0) die("epoll_create1");
        if (pthread_create(&threads[i], NULL, worker, &args[i])) die("pthread_create");
    }
    unsigned long total_wake = 0, total_accept = 0, total_eagain = 0;
    for (int iteration = 0; iteration < ROUNDS; iteration++) {
        uint16_t port;
        round_state r = { .fd = make_listener(&port) };
        uint32_t flags = EPOLLIN | (fixed ? EPOLLEXCLUSIVE : 0);
        for (int i = 0; i < WORKERS; i++) {
            args[i].round = &r;
            struct epoll_event event = { .events = flags, .data.ptr = &r };
            if (epoll_ctl(args[i].epfd, EPOLL_CTL_ADD, r.fd, &event) < 0) die("epoll_ctl ADD");
        }
        connect_one(port);
        while (atomic_load_explicit(&r.wakeups, memory_order_acquire) < 1) ;
        usleep(20000); /* Allow the legacy thundering herd to arrive before release. */
        atomic_store_explicit(&r.release_accept, 1, memory_order_release);
        while (atomic_load_explicit(&r.accepted, memory_order_acquire) < 1) ;
        while (atomic_load_explicit(&r.done, memory_order_acquire) < atomic_load_explicit(&r.wakeups, memory_order_acquire)) ;
        for (int i = 0; i < WORKERS; i++)
            if (epoll_ctl(args[i].epfd, EPOLL_CTL_DEL, r.fd, NULL) < 0) die("epoll_ctl DEL");
        close(r.fd);
        total_wake += r.wakeups; total_accept += r.accepted; total_eagain += r.eagain;
    }
    atomic_store(&stop_workers, 1);
    for (int i = 0; i < WORKERS; i++) { pthread_join(threads[i], NULL); close(args[i].epfd); }
    printf("mode=%s rounds=%d wakeups=%lu accepted=%lu eagain=%lu spurious=%lu EPOLLEXCLUSIVE=%s SO_REUSEPORT=verified\n",
           fixed ? "fixed" : "legacy", ROUNDS, total_wake, total_accept, total_eagain,
           total_wake - total_accept, fixed ? "enabled" : "disabled");
    if (!fixed && total_eagain == 0) { fprintf(stderr, "legacy defect did not reproduce\n"); return 1; }
    if (fixed && (total_eagain != 0 || total_wake != total_accept || total_accept != ROUNDS)) {
        fprintf(stderr, "fixed invariant failed\n"); return 1;
    }
    return 0;
}
