#define _GNU_SOURCE
#include "epoll_server.h"

#include <errno.h>
#include <stdlib.h>
#include <sys/epoll.h>

int epoll_add_exclusive_listener(int epfd, int listen_fd, uint32_t events)
{
    struct epoll_event ev = {
        .events = events | EPOLLIN | EPOLLEXCLUSIVE,
        .data.fd = listen_fd,
    };

    /* Let the running kernel enforce the full EPOLLEXCLUSIVE event mask. */
    if (events & EPOLLONESHOT) {
        errno = EINVAL;
        return -1;
    }
    return epoll_ctl(epfd, EPOLL_CTL_ADD, listen_fd, &ev);
}

void fd_queue_init(fd_queue *q)
{
    fd_q_node *stub = calloc(1, sizeof(*stub));
    if (!stub)
        abort();
    stub->fd = -1;
    atomic_init(&stub->next, NULL);
    atomic_init(&q->head, stub);
    atomic_init(&q->tail, stub);
}

int fd_queue_push(fd_queue *q, int fd)
{
    fd_q_node *node = calloc(1, sizeof(*node));
    fd_q_node *previous;

    if (!node)
        return -ENOMEM;
    node->fd = fd;
    atomic_init(&node->next, NULL);
    previous = atomic_exchange_explicit(&q->tail, node, memory_order_acq_rel);
    /* Publish the link only after the new node is fully initialized. */
    atomic_store_explicit(&previous->next, node, memory_order_release);
    return 0;
}

int fd_queue_pop(fd_queue *q)
{
    fd_q_node *first = atomic_load_explicit(&q->head, memory_order_acquire);
    fd_q_node *next = atomic_load_explicit(&first->next, memory_order_acquire);
    int fd;

    if (!next)
        return -EAGAIN;
    fd = next->fd;
    atomic_store_explicit(&q->head, next, memory_order_release);
    free(first);
    return fd;
}

void fd_queue_destroy(fd_queue *q)
{
    while (fd_queue_pop(q) != -EAGAIN)
        ;
    free(atomic_load_explicit(&q->head, memory_order_relaxed));
}
