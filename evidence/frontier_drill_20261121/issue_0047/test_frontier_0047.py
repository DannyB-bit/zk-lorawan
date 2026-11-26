from pathlib import Path
import os
import signal
import subprocess

HERE = Path(__file__).resolve().parent
BIN = HERE / "interpreter_lifecycle"
ENV = dict(os.environ)


def run(mode):
    return subprocess.run([BIN, mode], text=True, capture_output=True,
                          timeout=10, env=ENV)


def test_reproduce_frontier_gh_0047():
    legacy = run("legacy")
    assert legacy.returncode == -signal.SIGSEGV, legacy.stdout + legacy.stderr
    fixed = run("fixed")
    assert fixed.returncode == 0, fixed.stdout + fixed.stderr
    assert "mode=fixed detach=head_mutex initial_refs=2 daemon_lease=1" in fixed.stdout
    assert "final_refcount=0 freed_once=1 invariant=PASS" in fixed.stdout


def test_no_regression_frontier_gh_0047():
    for _ in range(8):
        result = run("fixed")
        assert result.returncode == 0, result.stdout + result.stderr
        assert "final_refcount=0 freed_once=1 invariant=PASS" in result.stdout
