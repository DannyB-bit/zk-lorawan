from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
BIN = HERE / "aba_epoch_queue"


def run(mode):
    return subprocess.run([BIN, mode], text=True, capture_output=True, timeout=20)


def test_reproduce_frontier_gh_0053():
    legacy = run("legacy")
    fixed = run("fixed")
    assert legacy.returncode == 0, legacy.stdout + legacy.stderr
    assert "stale_cas_ok=1 final_node=2 expected_node=3 corruption=REPRODUCED" in legacy.stdout
    assert fixed.returncode == 0, fixed.stdout + fixed.stderr
    assert "stale_cas_rejected=1 retry_ok=1 final_node=3 final_epoch=5 epoch_bits=64" in fixed.stdout


def test_no_regression_frontier_gh_0053():
    result = run("fixed")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "stale_cas_rejected=1 retry_ok=1 final_node=3" in result.stdout
    # Truthful capability report: A72 uses libatomic rather than lock-free 16B CAS.
    assert "tagged_cas_lock_free=0" in result.stdout
