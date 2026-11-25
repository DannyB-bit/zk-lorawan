from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
BIN = HERE / "lockless_queue"


def run(*args):
    return subprocess.run([BIN, *args], text=True, capture_output=True, timeout=120)


def test_reproduce_frontier_gh_0037():
    legacy = run("legacy")
    fixed = run("fixed")
    stress = run("stress")
    assert legacy.returncode == 0, legacy.stdout + legacy.stderr
    assert "LEGACY_POINTER_ABA_REPRODUCED=YES" in legacy.stdout
    assert fixed.returncode == 0, fixed.stdout + fixed.stderr
    assert "FIXED_TAGGED_ABA_REJECTED=YES" in fixed.stdout
    assert "FIXED_RETRY_FROM_CURRENT_HEAD=PASS" in fixed.stdout
    assert stress.returncode == 0, stress.stdout + stress.stderr
    assert "FIXED_TAGGED_ABA_STRESS=PASS iterations=100000 rejected=100000 epoch_bits=64 cas_width_bits=128" in stress.stdout


def test_no_regression_frontier_gh_0037():
    result = run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert "NATIVE_AARCH64_PAIR_CAS=LDAXP_STLXP EPOCH_GENERATION_BITS=64" in result.stdout
    assert "FRONTIER_GH_0037_PASS=YES legacy_aba=REPRODUCED tagged_aba=REJECTED" in result.stdout
