from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
BIN = HERE / "epoll_exclusive"


def run(mode):
    return subprocess.run([BIN, mode], text=True, capture_output=True, timeout=60)


def test_reproduce_frontier_gh_0044():
    legacy = run("legacy")
    fixed = run("fixed")
    assert legacy.returncode == 0, legacy.stdout + legacy.stderr
    assert "mode=legacy rounds=100 wakeups=400 accepted=100 eagain=300 spurious=300" in legacy.stdout
    assert fixed.returncode == 0, fixed.stdout + fixed.stderr
    assert "mode=fixed rounds=100 wakeups=100 accepted=100 eagain=0 spurious=0" in fixed.stdout
    assert "EPOLLEXCLUSIVE=enabled SO_REUSEPORT=verified" in fixed.stdout


def test_no_regression_frontier_gh_0044():
    result = run("fixed")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "rounds=100 wakeups=100 accepted=100 eagain=0 spurious=0" in result.stdout
