from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
BIN = HERE / "cooperative_budget"


def run(mode):
    return subprocess.run([BIN, mode], text=True, capture_output=True, timeout=10)


def test_reproduce_frontier_gh_0054():
    legacy = run("legacy")
    fixed = run("fixed")
    assert legacy.returncode == 0, legacy.stdout + legacy.stderr
    assert "mode=legacy ticks=256 local_polls=256 global_completed=0 global_starved=1" in legacy.stdout
    assert "max_global_wait_ticks=256" in legacy.stdout
    assert "invariant=STARVATION_REPRODUCED" in legacy.stdout
    assert fixed.returncode == 0, fixed.stdout + fixed.stderr
    assert "mode=fixed ticks=256 local_polls=252 global_completed=4 global_starved=0" in fixed.stdout
    assert "fallback_checks=4 max_global_wait_ticks=64 budget=64 invariant=PASS" in fixed.stdout


def test_no_regression_frontier_gh_0054():
    result = run("fixed")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "global_completed=4" in result.stdout
    assert "fallback_checks=4" in result.stdout
    assert "max_global_wait_ticks=64" in result.stdout
    assert "invariant=PASS" in result.stdout
