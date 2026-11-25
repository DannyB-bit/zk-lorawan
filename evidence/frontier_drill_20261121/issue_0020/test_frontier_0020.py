from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
BIN = HERE / "epoll_exclusive_model"


def test_reproduce_frontier_gh_0020():
    run = subprocess.run([BIN, "all"], text=True, capture_output=True, timeout=45)
    assert run.returncode == 0, run.stderr + run.stdout
    assert "LEGACY_NO_EXCLUSIVE flags=0" in run.stdout
    assert "FIXED_EPOLLEXCLUSIVE flags=0x10000000" in run.stdout
    assert "FRONTIER_GH_0020_PASS=YES" in run.stdout


def test_no_regression_frontier_gh_0020():
    run = subprocess.run([BIN, "fixed"], text=True, capture_output=True, timeout=30)
    assert run.returncode == 0, run.stderr + run.stdout
    assert "LOCKFREE_SIZE_T=YES queue=bounded_MPMC_mutex_free" in run.stdout
    assert "REALLOC_MOD_EXCLUSIVE_REJECTED=YES errno=EINVAL DELETE_READD_EXCLUSIVE=PASS" in run.stdout
    assert "accepted=256 consumed=256 errors=0 timeout=0 RESULT=PASS" in run.stdout
