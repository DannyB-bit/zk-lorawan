import pathlib


ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_no_regression_frontier_gh_0004():
    implementation = (ROOT / "epoll_server.c").read_text()
    assert "EPOLLIN | EPOLLEXCLUSIVE" in implementation
    assert "memory_order_release" in implementation
    assert "memory_order_acquire" in implementation
    assert "pthread_mutex" not in implementation
