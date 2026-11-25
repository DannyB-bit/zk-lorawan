from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
BIN = HERE / "coop_scheduler_model"


def test_reproduce_frontier_gh_0022():
    run = subprocess.run([BIN, "legacy"], text=True, capture_output=True, timeout=20)
    assert run.returncode == 0, run.stderr + run.stdout
    assert "LEGACY_UNYIELDING_STARVATION=REPRODUCED" in run.stdout
    assert "global_completed=0 global_checks=0 budget=UNDECREMENTED" in run.stdout


def test_no_regression_frontier_gh_0022():
    run = subprocess.run([BIN, "fixed"], text=True, capture_output=True, timeout=20)
    assert run.returncode == 0, run.stderr + run.stdout
    assert "FIXED_COOPERATIVE_SCHEDULER=PASS" in run.stdout
    assert "local_ticks=16384 nested_polls=65536 global_completed=256" in run.stdout
    assert "checksum=MATCH budget_bits=32 fallback_ticks=64" in run.stdout
