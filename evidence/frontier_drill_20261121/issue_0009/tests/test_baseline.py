import pathlib
import subprocess

EV = pathlib.Path(__file__).resolve().parents[1]
BIN = EV / "lockless_queue"


def test_no_regression_frontier_gh_0009():
    p = subprocess.run([BIN, "stress"], text=True, capture_output=True, timeout=60)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "STRESS_EXACTLY_ONCE=128" in p.stdout
    assert "STRESS_PASS=YES" in p.stdout
