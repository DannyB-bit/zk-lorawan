#!/usr/bin/env python3
"""Semantic entry points for FRONTIER-GH-0015 (hyphens normalized for pytest)."""
from pathlib import Path
import subprocess

EV = Path(__file__).resolve().parent
BIN = EV / "subinterp_lifetime_test"


def test_reproduce_frontier_gh_0015():
    legacy = subprocess.run([BIN, "legacy"], text=True, capture_output=True)
    assert legacy.returncode == -11  # SIGSEGV from the unmapped former tstate page
    fixed = subprocess.run([BIN, "fixed"], text=True, capture_output=True, timeout=120)
    assert fixed.returncode == 0, fixed.stderr
    assert "SUBINTERPRETER_LIFETIME_PASS=YES" in fixed.stdout
    assert "atomic_deletes=128" in fixed.stdout


def test_no_regression_frontier_gh_0015():
    fixed = subprocess.run([BIN, "fixed"], text=True, capture_output=True, timeout=120)
    assert fixed.returncode == 0, fixed.stderr
    assert "head_mutex_acquisitions=" in fixed.stdout
    assert "ERROR: AddressSanitizer" not in fixed.stderr
