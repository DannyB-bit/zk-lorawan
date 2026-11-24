import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent
BIN = ROOT / "solution" / "frontier_gh_0011_test"


def test_reproduce_frontier_gh_0011():
    out = subprocess.check_output([BIN], text=True)
    assert "PASS: legacy ordering reproduced free while SaveThread pin was live" in out
    assert "PASS: patched ordering frees only after atomic pin drains" in out


def test_no_regression_frontier_gh_0011():
    out = subprocess.check_output([BIN], text=True)
    assert "PASS: no-pin baseline and head_mutex detach boundary" in out
    assert "test result: ok. 2 passed; 0 failed" in out
