from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
BIN = HERE / "subinterpreter_lifetime"


def run(mode):
    return subprocess.run([BIN, mode], text=True, capture_output=True, timeout=30)


def test_reproduce_frontier_gh_0031():
    legacy = run("legacy")
    fixed = run("fixed")
    assert legacy.returncode == fixed.returncode == 0, legacy.stdout + fixed.stdout + legacy.stderr + fixed.stderr
    assert "LEGACY_GIL_DELETE_UAF_REPRODUCED=YES" in legacy.stdout
    assert "daemon_observed_freed=1" in legacy.stdout
    assert "FIXED_HEAD_MUTEX=PASS" in fixed.stdout
    assert "FIXED_TSTATE_REFCOUNT=PASS owner_decrement_old=2 final_refs=0" in fixed.stdout
    assert "FIXED_NO_UAF=PASS" in fixed.stdout


def test_no_regression_frontier_gh_0031():
    stress = run("stress")
    assert stress.returncode == 0, stress.stdout + stress.stderr
    assert "FIXED_LIFETIME_STRESS=PASS iterations=1000 final_refs=0 uaf=0" in stress.stdout
