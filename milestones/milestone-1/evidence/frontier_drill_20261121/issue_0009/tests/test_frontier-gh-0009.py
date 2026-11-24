import pathlib
import subprocess

EV = pathlib.Path(__file__).resolve().parents[1]
BIN = EV / "lockless_queue"


def test_reproduce_frontier_gh_0009():
    legacy = subprocess.run([BIN, "legacy"], text=True, capture_output=True, timeout=30)
    assert legacy.returncode == 2, legacy.stdout + legacy.stderr
    assert "LEGACY_ABA_REPRODUCED=YES" in legacy.stdout
    fixed = subprocess.run([BIN, "fixed"], text=True, capture_output=True, timeout=30)
    assert fixed.returncode == 0, fixed.stdout + fixed.stderr
    assert "TAG_WIDTH_BITS=64" in fixed.stdout
    assert "TAGGED_LOCK_FREE=1" in fixed.stdout
    assert "TAGGED_PTR_ABA_PASS=YES" in fixed.stdout
