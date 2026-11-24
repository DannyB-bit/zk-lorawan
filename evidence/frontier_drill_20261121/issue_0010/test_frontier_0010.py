import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent
BIN = ROOT / "scheduler"


def test_reproduce_frontier_gh_0010():
    legacy = subprocess.run([BIN], text=True, capture_output=True)
    assert legacy.returncode == 2
    assert "LEGACY_STARVATION_REPRODUCED=YES" in legacy.stdout
    fixed = subprocess.run([BIN, "--fixed"], text=True, capture_output=True)
    assert fixed.returncode == 0, fixed.stdout + fixed.stderr
    assert "COOPERATIVE_BUDGET_PASS=YES ticks=64 global_completed=1" in fixed.stdout


def test_no_regression_frontier_gh_0010():
    out = subprocess.check_output([BIN, "--fixed"], text=True)
    assert "forced_global_every=64 budget=128" in out
