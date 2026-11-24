import pathlib
import subprocess

EV = pathlib.Path(__file__).resolve().parents[1]
BIN = EV / "aba_epoch_queue_test"


def test_reproduce_frontier_gh_0013():
    legacy = subprocess.run([BIN, "legacy"], text=True, capture_output=True, timeout=30)
    assert legacy.returncode == 0, legacy.stdout + legacy.stderr
    assert "LEGACY_ABA_REPRODUCED=YES" in legacy.stdout
    assert "STALE_CAS_SUCCESS=1" in legacy.stdout
    assert "B_SELF_CYCLE=1" in legacy.stdout
    fixed = subprocess.run([BIN, "tagged"], text=True, capture_output=True, timeout=30)
    assert fixed.returncode == 0, fixed.stdout + fixed.stderr
    assert "ABA_TAGGED_EPOCH_PASS=YES" in fixed.stdout
    assert "STALE_CAS_SUCCESS=0" in fixed.stdout
    assert "RETRY_EPOCH=3" in fixed.stdout and "FINAL_EPOCH=4" in fixed.stdout


def test_no_regression_frontier_gh_0013():
    p = subprocess.run([BIN, "baseline"], text=True, capture_output=True, timeout=30)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "BASELINE_PASS=YES" in p.stdout
    assert "FINAL_EPOCH=2" in p.stdout
