from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
BIN = HERE / "epoll_exclusive_herd"


def test_reproduce_frontier_gh_0048():
    run = subprocess.run([BIN], text=True, capture_output=True, timeout=120)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "LEGACY_EPOLL_HERD" in run.stdout
    assert "FIXED_EPOLLEXCLUSIVE" in run.stdout
    assert "exclusive=1" in run.stdout
    assert "EPOLLEXCLUSIVE_HERD_REDUCTION=PASS" in run.stdout
    assert "lockfree_ticket_distribution=PASS" in run.stdout


def test_no_regression_frontier_gh_0048():
    # Independent real-kernel rerun guards against a one-off scheduling result.
    run = subprocess.run([BIN], text=True, capture_output=True, timeout=120)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "accepted=128" in run.stdout
    assert "EPOLLEXCLUSIVE_HERD_REDUCTION=PASS" in run.stdout
