import pathlib
import subprocess

EV = pathlib.Path(__file__).resolve().parents[1]
BIN = EV / "solution/target/debug/frontier-gh-0014"


def run(mode):
    return subprocess.run([BIN, mode], text=True, capture_output=True, timeout=20)


def test_reproduce_frontier_gh_0014():
    legacy = run("legacy")
    assert legacy.returncode == 0, legacy.stdout + legacy.stderr
    assert "LEGACY_STARVATION_REPRODUCED=YES" in legacy.stdout
    assert "GLOBAL_POLLS=0" in legacy.stdout
    fixed = run("fixed")
    assert fixed.returncode == 0, fixed.stdout + fixed.stderr
    assert "COOPERATIVE_BUDGET_PASS=YES" in fixed.stdout
    assert "GLOBAL_FALLBACK_CHECKS=4" in fixed.stdout
    assert "GLOBAL_POLLS=1" in fixed.stdout
    assert "TOKIO_WATCHDOG_POLLS=" in fixed.stdout


def test_no_regression_frontier_gh_0014():
    result = run("baseline")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "BASELINE_PASS=YES" in result.stdout
    assert "LOCAL_POLLS=8" in result.stdout
    assert "GLOBAL_POLLS=8" in result.stdout
