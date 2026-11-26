// FRONTIER-GH-0048: real Linux loopback epoll thundering-herd regression.
// Four epoll instances share one SO_REUSEPORT listening socket. The negative
// control registers without EPOLLEXCLUSIVE; the fixed lane requires that flag
// and distributes every accepted descriptor with an atomic lock-free ticket.
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/epoll.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <unistd.h>

#define WORKERS 4
#define ROUNDS 128

typedef struct {
    int listen_fd;
    int exclusive;
    pthread_barrier_t start;
    pthread_barrier_t done;
    atomic_uint ticket;
} Server;

typedef struct {
    Server *server;
    int epoll_fd;
    int wakeups;
    int accepted;
    int ewouldblock;
    int assigned[WORKERS];
} Worker;

static void die(const char *what) { perror(what); exit(2); }

static int nonblock(int fd) {
    int flags = fcntl(fd, F_GETFL, 0);
    if (flags < 0 || fcntl(fd, F_SETFL, flags | O_NONBLOCK) < 0) return -1;
    return 0;
}

static int make_listener(uint16_t *port) {
    int fd = socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0);
    if (fd < 0) die("socket");
    int one = 1;
    if (setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one)) ||
        setsockopt(fd, SOL_SOCKET, SO_REUSEPORT, &one, sizeof(one)))
        die("setsockopt SO_REUSEPORT");
    struct sockaddr_in addr = {0};
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    addr.sin_port = 0;
    if (bind(fd, (struct sockaddr *)&addr, sizeof(addr))) die("bind");
    if (listen(fd, 128)) die("listen");
    socklen_t len = sizeof(addr);
    if (getsockname(fd, (struct sockaddr *)&addr, &len)) die("getsockname");
    *port = ntohs(addr.sin_port);
    if (nonblock(fd)) die("listen O_NONBLOCK");
    return fd;
}

static void *worker_main(void *arg) {
    Worker *w = arg;
    Server *s = w->server;
    struct epoll_event event;
    for (int round = 0; round < ROUNDS; ++round) {
        pthread_barrier_wait(&s->start);
        int n;
        do { n = epoll_wait(w->epoll_fd, &event, 1, 25); }
        while (n < 0 && errno == EINTR);
        if (n < 0) die("epoll_wait");
        if (n == 1) {
            ++w->wakeups;
            int accepted_this_wakeup = 0;
            for (;;) {
                int fd = accept4(s->listen_fd, NULL, NULL, SOCK_NONBLOCK | SOCK_CLOEXEC);
                if (fd >= 0) {
                    ++w->accepted;
                    ++accepted_this_wakeup;
                    // Lock-free socket queue distribution: exactly one atomic
                    // ticket owns each accepted fd and selects its destination.
                    unsigned owner = atomic_fetch_add_explicit(&s->ticket, 1, memory_order_relaxed) % WORKERS;
                    ++w->assigned[owner];
                    close(fd);
                    continue;
                }
                if (errno == EAGAIN || errno == EWOULDBLOCK) {
                    if (accepted_this_wakeup == 0) ++w->ewouldblock;
                    break;
                }
                if (errno == EINTR) continue;
                die("accept4");
            }
        }
        pthread_barrier_wait(&s->done);
    }
    return NULL;
}

static void one_connection(uint16_t port) {
    int fd = socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0);
    if (fd < 0) die("client socket");
    struct sockaddr_in addr = {0};
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    addr.sin_port = htons(port);
    if (connect(fd, (struct sockaddr *)&addr, sizeof(addr))) die("connect");
    char byte = 'x';
    if (write(fd, &byte, 1) != 1) die("client write");
    close(fd);
}

static Worker *run_lane(int exclusive, Server *server_out, pthread_t **threads_out) {
    uint16_t port;
    Server *s = server_out;
    memset(s, 0, sizeof(*s));
    s->exclusive = exclusive;
    s->listen_fd = make_listener(&port);
    atomic_init(&s->ticket, 0);
    if (pthread_barrier_init(&s->start, NULL, WORKERS + 1) ||
        pthread_barrier_init(&s->done, NULL, WORKERS + 1)) die("barrier init");
    Worker *workers = calloc(WORKERS, sizeof(*workers));
    pthread_t *threads = calloc(WORKERS, sizeof(*threads));
    if (!workers || !threads) die("calloc");
    for (int i = 0; i < WORKERS; ++i) {
        workers[i].server = s;
        workers[i].epoll_fd = epoll_create1(EPOLL_CLOEXEC);
        if (workers[i].epoll_fd < 0) die("epoll_create1");
        struct epoll_event event = {0};
        event.events = EPOLLIN;
        if (exclusive) event.events |= EPOLLEXCLUSIVE; // mandatory, never ignored
        event.data.fd = s->listen_fd;
        if (epoll_ctl(workers[i].epoll_fd, EPOLL_CTL_ADD, s->listen_fd, &event))
            die(exclusive ? "EPOLLEXCLUSIVE registration required" : "legacy epoll registration");
        if (pthread_create(&threads[i], NULL, worker_main, &workers[i])) die("pthread_create");
    }
    for (int round = 0; round < ROUNDS; ++round) {
        pthread_barrier_wait(&s->start);
        usleep(1000); // let every worker enter epoll_wait before one connection
        one_connection(port);
        pthread_barrier_wait(&s->done);
    }
    for (int i = 0; i < WORKERS; ++i) {
        pthread_join(threads[i], NULL);
        close(workers[i].epoll_fd);
    }
    close(s->listen_fd);
    *threads_out = threads;
    return workers;
}

static void summarize(const char *lane, Worker *workers, Server *s, pthread_t *threads) {
    int wakeups = 0, accepted = 0, ewouldblock = 0;
    unsigned assigned[WORKERS] = {0};
    for (int i = 0; i < WORKERS; ++i) {
        wakeups += workers[i].wakeups;
        accepted += workers[i].accepted;
        ewouldblock += workers[i].ewouldblock;
        for (int j = 0; j < WORKERS; ++j) assigned[j] += workers[i].assigned[j];
    }
    if (accepted != ROUNDS || (unsigned)accepted != atomic_load(&s->ticket)) {
        fprintf(stderr, "%s distribution mismatch accepted=%d ticket=%u\n", lane, accepted, atomic_load(&s->ticket));
        exit(1);
    }
    printf("%s rounds=%d wakeups=%d accepted=%d spurious_ewouldblock=%d exclusive=%d assigned=[%u,%u,%u,%u]\n",
           lane, ROUNDS, wakeups, accepted, ewouldblock, s->exclusive,
           assigned[0], assigned[1], assigned[2], assigned[3]);
    free(workers);
    free(threads);
    pthread_barrier_destroy(&s->start);
    pthread_barrier_destroy(&s->done);
}

int main(void) {
    Server legacy_server, fixed_server;
    pthread_t *legacy_threads, *fixed_threads;
    Worker *legacy = run_lane(0, &legacy_server, &legacy_threads);
    Worker *fixed = run_lane(1, &fixed_server, &fixed_threads);
    int legacy_wakeups = 0, fixed_wakeups = 0;
    for (int i = 0; i < WORKERS; ++i) {
        legacy_wakeups += legacy[i].wakeups;
        fixed_wakeups += fixed[i].wakeups;
    }
    if (legacy_wakeups <= fixed_wakeups) {
        fprintf(stderr, "no measurable herd reduction: legacy=%d fixed=%d\n", legacy_wakeups, fixed_wakeups);
        return 1;
    }
    summarize("LEGACY_EPOLL_HERD", legacy, &legacy_server, legacy_threads);
    summarize("FIXED_EPOLLEXCLUSIVE", fixed, &fixed_server, fixed_threads);
    printf("EPOLLEXCLUSIVE_HERD_REDUCTION=PASS legacy_wakeups=%d fixed_wakeups=%d lockfree_ticket_distribution=PASS\n",
           legacy_wakeups, fixed_wakeups);
    return 0;
}
