import pathlib


ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_no_regression_frontier_gh_0007():
    source = (ROOT / "interpreter_lifecycle.c").read_text()
    assert "pthread_mutex_lock(&runtime->head_mutex)" in source
    assert "atomic_fetch_sub_explicit(&tstate->references, 1, memory_order_acq_rel)" in source
    assert "if (old == 1)" in source
    assert "atomic_compare_exchange_weak_explicit" in source
    assert source.index("*link = tstate->next") < source.index("pthread_mutex_unlock(&runtime->head_mutex);", source.index("*link = tstate->next"))
