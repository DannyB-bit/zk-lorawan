import pathlib


ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_no_regression_frontier_gh_0005():
    implementation = (ROOT / "lockless_queue.c").read_text()
    assert "ldaxp" in implementation
    assert "stlxp" in implementation
    assert "expected.epoch + 1" in implementation
    assert "sizeof(tagged_head) == 16" in implementation
    assert "__atomic_compare_exchange" not in implementation
