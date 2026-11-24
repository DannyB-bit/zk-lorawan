#ifndef LOCKLESS_QUEUE_H
#define LOCKLESS_QUEUE_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdatomic.h>

typedef struct lq_node {
    struct lq_node *next;
    int value;
} lq_node_t;

typedef struct {
    lq_node_t *ptr;
    uint64_t epoch;
} lq_tagged_t;

typedef struct {
    _Atomic(lq_tagged_t) head;
} lq_queue_t;

void lq_init(lq_queue_t *q, lq_node_t *initial);
void lq_push(lq_queue_t *q, lq_node_t *node);
bool lq_pop(lq_queue_t *q, lq_node_t **out);

#endif
