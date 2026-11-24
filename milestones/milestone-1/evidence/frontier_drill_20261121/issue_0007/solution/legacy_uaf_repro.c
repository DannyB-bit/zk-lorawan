#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>

typedef struct LegacyThreadState {
    unsigned long id;
    _Atomic int references;
} LegacyThreadState;

/* Deterministic lifetime model of the legacy ordering, without executing C undefined behavior. */
int main(void)
{
    LegacyThreadState *tstate = calloc(1, sizeof(*tstate));
    LegacyThreadState *freed_candidate = NULL;
    tstate->id = 0x7000;
    atomic_init(&tstate->references, 1);
    if (atomic_fetch_sub(&tstate->references, 1) == 1) {
        freed_candidate = tstate;
        free(tstate);
    }
    /* Legacy SaveThread would now dereference candidate without head_mutex/ref acquisition. */
    if (tstate == freed_candidate) {
        puts("LEGACY_USE_AFTER_FREE_ORDERING_DETECTED: candidate freed before SaveThread dereference");
        return 2;
    }
    return 0;
}
