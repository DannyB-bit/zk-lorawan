import pathlib
import subprocess


ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_reproduce_frontier_gh_0006():
    binary = ROOT / ".pytest-frontier-gh-0006"
    subprocess.run([
        "rustc", "--edition=2024", "--test",
        str(ROOT / "frontier_gh_0006_test.rs"), "-o", str(binary),
    ], check=True)
    run = subprocess.run([str(binary), "--nocapture"], check=True, text=True, capture_output=True)
    assert "test reproduce_frontier_gh_0006 ... ok" in run.stdout
    assert "test fixed_global_fallback_at_64 ... ok" in run.stdout
    assert "test result: ok. 4 passed; 0 failed" in run.stdout
