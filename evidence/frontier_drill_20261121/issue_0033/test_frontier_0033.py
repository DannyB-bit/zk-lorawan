from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
BIN = HERE / "aba_tagged_queue"


def test_reproduce_frontier_gh_0033():
    run = subprocess.run([BIN], text=True, capture_output=True, timeout=120)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "LEGACY_POINTER_CAS rounds=2000 ABA_success=2000" in run.stdout
    assert "FIXED_TAGGED_CAS rounds=2000 ABA_success=0 stale_CAS_rejected=2000 intact_A_to_C=2000 epoch_bits=64" in run.stdout
    assert "ABA_EPOCH_INVARIANT=PASS" in run.stdout


def test_no_regression_frontier_gh_0033():
    run = subprocess.run([BIN], text=True, capture_output=True, timeout=120)
    assert run.returncode == 0, run.stdout + run.stderr
    assert "ORDERED_PUSH_POP=PASS" in run.stdout
