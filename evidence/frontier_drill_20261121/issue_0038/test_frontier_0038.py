from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
BIN = HERE / "cooperative_scheduler"

def run(*args):
    return subprocess.run([BIN, *args], text=True, capture_output=True, timeout=30)

def test_reproduce_frontier_gh_0038():
    legacy = run("legacy")
    fixed = run("fixed")
    stress = run("stress")
    assert legacy.returncode == 0, legacy.stdout + legacy.stderr
    assert "LEGACY_UNYIELDING_LOCAL_STARVATION=REPRODUCED local_polls=128 global_polls=0" in legacy.stdout
    assert fixed.returncode == 0, fixed.stdout + fixed.stderr
    assert "FIXED_COOPERATIVE_BUDGET=PASS global_first_poll_tick=64" in fixed.stdout
    assert stress.returncode == 0, stress.stdout + stress.stderr
    assert "GLOBAL_FALLBACK_STRESS=PASS rounds=1000 interval_ticks=64 global_checks=1000" in stress.stdout

def test_no_regression_frontier_gh_0038():
    result = run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert "FRONTIER_GH_0038_PASS=YES budget=64 starvation=FIXED" in result.stdout
