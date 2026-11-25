from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
BIN = HERE / "gil_delete_race_model"


def run(mode):
    proc = subprocess.run([BIN, mode], text=True, capture_output=True, timeout=30)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    return proc.stdout


def test_reproduce_frontier_gh_0023():
    out = run("legacy")
    assert "LEGACY_GIL_DELETE_RACE=REPRODUCED" in out
    assert "stale_tstate=1" in out
    assert "unlinked_without_head_mutex=1" in out


def test_fixed_head_mutex_and_atomic_refcount():
    out = run("fixed")
    assert "FIXED_HEAD_MUTEX_REFCOUNT=PASS" in out
    assert "stale_tstate=0" in out
    assert "delete_ref_previous=2 daemon_ref_previous=1 final_refs=0" in out
    assert "free_after_last_ref=YES" in out


def test_fixed_stress():
    out = run("stress")
    assert "FIXED_GIL_DELETE_STRESS=PASS iterations=1000 passed=1000" in out
