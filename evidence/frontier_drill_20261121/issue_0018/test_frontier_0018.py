import pathlib
import subprocess

BIN = pathlib.Path(__file__).with_name("worker")


def test_reproduce_frontier_gh_0018():
    legacy = subprocess.run([BIN, "legacy"], text=True, capture_output=True, timeout=20)
    assert legacy.returncode == 0, legacy.stdout + legacy.stderr
    assert "LEGACY_STARVATION_REPRODUCED=YES" in legacy.stdout
    assert "global_completed=0" in legacy.stdout
    fixed = subprocess.run([BIN, "fixed"], text=True, capture_output=True, timeout=20)
    assert fixed.returncode == 0, fixed.stdout + fixed.stderr
    assert "GLOBAL_FALLBACK_PASS=YES" in fixed.stdout
    assert "first_global_tick=64" in fixed.stdout


def test_no_regression_frontier_gh_0018():
    stress = subprocess.run([BIN, "stress"], text=True, capture_output=True, timeout=30)
    assert stress.returncode == 0, stress.stdout + stress.stderr
    assert "FIXED_STRESS_PASS=YES" in stress.stdout
    assert "produced=80000 consumed=80000" in stress.stdout
    assert "max_ticks_between_global_checks=64" in stress.stdout
