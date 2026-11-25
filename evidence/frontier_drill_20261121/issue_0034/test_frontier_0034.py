from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
BIN = HERE / "cooperative_budget_model"


def run(mode):
    return subprocess.run([BIN, mode], text=True, capture_output=True, timeout=20)


def test_reproduce_frontier_gh_0034():
    legacy = run("legacy")
    fixed = run("fixed")
    assert legacy.returncode == fixed.returncode == 0, legacy.stdout + fixed.stdout + legacy.stderr + fixed.stderr
    assert "LEGACY_UNYIELDING_STARVATION_REPRODUCED=YES" in legacy.stdout
    assert "global_completed=0" in legacy.stdout
    assert "budget_unchanged=128" in legacy.stdout
    assert "FIXED_COOPERATIVE_BUDGET=PASS budget_after_first_poll=127" in fixed.stdout
    assert "FIXED_GLOBAL_FALLBACK=PASS first_global_tick=64" in fixed.stdout


def test_no_regression_frontier_gh_0034():
    stress = run("stress")
    assert stress.returncode == 0, stress.stdout + stress.stderr
    assert "FIXED_GLOBAL_STRESS=PASS ticks=4096 global_completed=64 first_global_tick=64" in stress.stdout
