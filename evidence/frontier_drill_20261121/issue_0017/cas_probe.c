#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
typedef struct __attribute__((aligned(16))) { void *ptr; uint64_t epoch; } tagged_head_t;
extern int atomic_cas_tagged_asm(tagged_head_t *, tagged_head_t *, const tagged_head_t *);
int main(void) {
    tagged_head_t h = {0}, e = {0};
    int x = 7;
    tagged_head_t d = {&x, 1};
    printf("before h=%p align=%u\n", (void *)&h, (unsigned)((uintptr_t)&h & 15));
    bool ok = atomic_cas_tagged_asm(&h, &e, &d);
    printf("after ok=%d h.ptr=%p h.epoch=%llu e.ptr=%p e.epoch=%llu\n", (int)ok, h.ptr,
           (unsigned long long)h.epoch, e.ptr, (unsigned long long)e.epoch);
    return ok && h.ptr == &x && h.epoch == 1 ? 0 : 1;
}
