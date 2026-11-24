#ifndef FRONTIER_EPOLL_SERVER_H
#define FRONTIER_EPOLL_SERVER_H

#include <stdatomic.h>
#include <stdint.h>

/* MPSC accepted-fd queue: producers are accept workers, consumer is dispatcher. */
typedef struct fd_q_node {
    int fd;
    _Atomic(struct fd_q_node *) next;
} fd_q_node;

typedef struct {
    _Atomic(fd_q_node *) head;
    _Atomic(fd_q_node *) tail;
} fd_queue;

void fd_queue_init(fd_queue *q);
int fd_queue_push(fd_queue *q, int fd);
int fd_queue_pop(fd_queue *q); /* -EAGAIN when empty */
void fd_queue_destroy(fd_queue *q);
int epoll_add_exclusive_listener(int epfd, int listen_fd, uint32_t events);

#endif
