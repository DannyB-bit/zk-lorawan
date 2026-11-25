import pathlib
import platform
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent
BIN = ROOT / "tagged_queue_aba_native"

def build_and_run(mode: str) -> subprocess.CompletedProcess:
    if not BIN.exists():
        subprocess.run(["gcc", "-std=c11", "-O2", "-g", "-pthread", str(ROOT / "tagged_queue_aba.c"), "-o", str(BIN)], check=True)
    return subprocess.run([str(BIN), mode], text=True, capture_output=True, timeout=20)

def test_reproduce_frontier_gh_0029():
    assert platform.machine() == "aarch64"
    legacy = build_and_run("--legacy")
    assert legacy.returncode == 0, legacy.stdout + legacy.stderr
    assert "LEGACY_ABA_ACCEPTED=YES head_id=2" in legacy.stdout
    fixed = build_and_run("--fixed")
    assert fixed.returncode == 0, fixed.stdout + fixed.stderr
    assert "FIXED_ABA_REJECTED=YES" in fixed.stdout
    assert "current_epoch=3 head_id=1" in fixed.stdout

def test_no_regression_frontier_gh_0029():
    for _ in range(20):
        fixed = build_and_run("--fixed")
        assert fixed.returncode == 0, fixed.stdout + fixed.stderr
        assert "FIXED_ABA_REJECTED=YES" in fixed.stdout
