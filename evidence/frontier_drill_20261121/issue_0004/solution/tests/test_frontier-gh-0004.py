import pathlib
import subprocess


ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_reproduce_frontier_gh_0004():
    binary = ROOT / ".pytest-frontier-gh-0004"
    subprocess.run([
        "gcc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-pthread",
        str(ROOT / "epoll_server.c"), str(ROOT / "frontier_gh_0004_test.c"),
        "-o", str(binary),
    ], check=True)
    run = subprocess.run([str(binary)], check=True, text=True, capture_output=True)
    assert "EPOLLEXCLUSIVE: wakeups=1 accepted=1 EWOULDBLOCK=0" in run.stdout
    assert "MPSC queue: 80000/80000" in run.stdout
