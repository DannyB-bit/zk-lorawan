import pathlib
import subprocess

BIN = pathlib.Path(__file__).with_name("lockless_queue")


def test_reproduce_frontier_gh_0017():
    legacy = subprocess.run([BIN, "legacy"], text=True, capture_output=True, timeout=20)
    assert legacy.returncode == 0, legacy.stdout + legacy.stderr
    assert "LEGACY_ABA_REPRODUCED=YES" in legacy.stdout
    fixed = subprocess.run([BIN, "fixed"], text=True, capture_output=True, timeout=30)
    assert fixed.returncode == 0, fixed.stdout + fixed.stderr
    assert "TAGGED_EPOCH_ABA_REJECTED=YES" in fixed.stdout
    assert "TAGGED_STRESS_PASS=YES" in fixed.stdout


def test_no_regression_frontier_gh_0017():
    fixed = subprocess.run([BIN, "fixed"], text=True, capture_output=True, timeout=30)
    assert fixed.returncode == 0, fixed.stdout + fixed.stderr
    assert "stress_consumed=40000" in fixed.stdout
    assert "duplicates=0" in fixed.stdout
