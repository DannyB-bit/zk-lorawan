import pathlib
import platform
import signal
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent
BIN = ROOT / "subinterpreter_lifecycle_native"

def build_and_run(mode: str) -> subprocess.CompletedProcess:
    if not BIN.exists():
        subprocess.run([
            "gcc", "-std=c11", "-O1", "-g", "-pthread",
            str(ROOT / "subinterpreter_lifecycle.c"), "-o", str(BIN),
        ], check=True)
    return subprocess.run([str(BIN), mode], text=True, capture_output=True, timeout=20)

def test_reproduce_frontier_gh_0027():
    assert platform.machine() == "aarch64"
    buggy = build_and_run("--buggy")
    # The deleter munmaps the tstate page; SaveThread then dereferences it.
    # The kernel's SIGSEGV is a real UAF proof without sanitizer dependence.
    assert buggy.returncode == -signal.SIGSEGV, buggy.stdout + buggy.stderr
    fixed = build_and_run("--fixed")
    assert fixed.returncode == 0, fixed.stdout + fixed.stderr
    assert "FIXED_OK" in fixed.stdout

def test_no_regression_frontier_gh_0027():
    for _ in range(20):
        fixed = build_and_run("--fixed")
        assert fixed.returncode == 0, fixed.stdout + fixed.stderr
        assert "head_mutex protected save+delete" in fixed.stdout
