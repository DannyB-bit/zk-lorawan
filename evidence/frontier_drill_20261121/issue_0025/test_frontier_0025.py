from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
BIN = HERE / "aba_epoch_model"


def test_reproduce_frontier_gh_0025():
    run = subprocess.run([BIN, "legacy"], text=True, capture_output=True, timeout=20)
    assert run.returncode == 0, run.stderr + run.stdout
    assert "LEGACY_POINTER_ABA_REPRODUCED=YES" in run.stdout
    assert "stale_next=B final_head=B" in run.stdout


def test_no_regression_frontier_gh_0025():
    fixed = subprocess.run([BIN, "fixed"], text=True, capture_output=True, timeout=20)
    stress = subprocess.run([BIN, "stress"], text=True, capture_output=True, timeout=45)
    assert fixed.returncode == stress.returncode == 0, fixed.stdout + stress.stdout
    assert "FIXED_TAGGED_ABA_REJECTED=YES" in fixed.stdout
    assert "observed_epoch=3" in fixed.stdout
    assert "FIXED_RETRY_FROM_CURRENT_HEAD=PASS final_head=C epoch=4" in fixed.stdout
    assert "iterations=100000 rejected=100000 epoch_bits=64 cas_width_bits=128" in stress.stdout
