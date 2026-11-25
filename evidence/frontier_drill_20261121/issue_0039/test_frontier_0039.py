from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
BIN = HERE / "interpreter_lifecycle"


def run(*args):
    return subprocess.run([BIN, *args], text=True, capture_output=True, timeout=30)


def test_reproduce_frontier_gh_0039():
    legacy = run("legacy")
    fixed = run("fixed")
    stress = run("stress")
    assert legacy.returncode == 0, legacy.stdout + legacy.stderr
    assert "LEGACY_UNLOCKED_SAVE_AFTER_DELETE=REPRODUCED use_after_free_attempts=1" in legacy.stdout
    assert fixed.returncode == 0, fixed.stdout + fixed.stderr
    assert "FIXED_HEAD_MUTEX_ATOMIC_REFCOUNT_STRESS=PASS rounds=1" in fixed.stdout
    assert stress.returncode == 0, stress.stdout + stress.stderr
    assert "rounds=10000" in stress.stdout
    assert "use_after_free_attempts=0 final_refs=0" in stress.stdout


def test_no_regression_frontier_gh_0039():
    result = run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert "FRONTIER_GH_0039_PASS=YES head_mutex=ENFORCED atomic_refcount=ENFORCED uaf=0" in result.stdout
