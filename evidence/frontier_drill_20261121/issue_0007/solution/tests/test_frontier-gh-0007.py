import pathlib
import subprocess


ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_reproduce_frontier_gh_0007():
    fixed = ROOT / ".pytest-frontier-gh-0007"
    subprocess.run([
        "gcc", "-std=c11", "-O2", "-g", "-Wall", "-Wextra", "-Werror",
        "-pthread", "-fsanitize=undefined", "-fno-sanitize-recover=all",
        str(ROOT / "interpreter_lifecycle.c"), str(ROOT / "frontier_gh_0007_test.c"),
        "-o", str(fixed),
    ], check=True)
    run = subprocess.run([str(fixed)], check=True, text=True, capture_output=True)
    assert "delete_then_save_rejected: PASS" in run.stdout
    assert "atomic_last_reference_free_once: PASS" in run.stdout
    assert "concurrent_save_delete_no_uaf: PASS" in run.stdout
    legacy_binary = ROOT / ".pytest-legacy-gh-0007"
    subprocess.run([
        "gcc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
        str(ROOT / "legacy_uaf_repro.c"), "-o", str(legacy_binary),
    ], check=True)
    legacy = subprocess.run([str(legacy_binary)], text=True, capture_output=True)
    assert legacy.returncode == 2
    assert "LEGACY_USE_AFTER_FREE_ORDERING_DETECTED" in legacy.stdout
