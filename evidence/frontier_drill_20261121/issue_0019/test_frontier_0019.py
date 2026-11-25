from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
BIN = HERE / "pylifecycle_model"

def test_reproduce_frontier_gh_0019():
    run = subprocess.run([BIN, "legacy"], text=True, capture_output=True, timeout=20)
    assert run.returncode == 0, run.stderr
    assert "LEGACY_TSTATE_RACE_REPRODUCED=YES" in run.stdout
    assert "old_refs=0" in run.stdout

def test_no_regression_frontier_gh_0019():
    fixed = subprocess.run([BIN, "fixed"], text=True, capture_output=True, timeout=20)
    stress = subprocess.run([BIN, "stress"], text=True, capture_output=True, timeout=60)
    assert fixed.returncode == stress.returncode == 0
    assert "FIXED_TSTATE_LIFETIME_PASS=YES iterations=1" in fixed.stdout
    assert "iterations=2000" in stress.stdout
    assert "freed=2000" in stress.stdout
    assert stress.stdout.count("acquired=") == 1
