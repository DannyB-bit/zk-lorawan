import pathlib
import subprocess

EV = pathlib.Path(__file__).resolve().parent
BIN = EV / "epoll_exclusive_test"

def test_reproduce_frontier_gh_0012():
    p = subprocess.run([BIN, "exclusive"], text=True, capture_output=True, timeout=30)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "EPOLL_EXCLUSIVE_PASS=YES" in p.stdout
    assert "ACCEPTS=240" in p.stdout and "EWOULDBLOCK=0" in p.stdout

def test_no_regression_frontier_gh_0012():
    p = subprocess.run([BIN, "legacy"], text=True, capture_output=True, timeout=30)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "LEGACY_HERD_REPRODUCED=YES" in p.stdout
    assert "ACCEPTS=240" in p.stdout and "ERRORS=0" in p.stdout
