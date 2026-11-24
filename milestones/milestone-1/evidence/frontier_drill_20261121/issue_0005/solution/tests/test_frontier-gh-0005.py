import pathlib
import subprocess


ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_reproduce_frontier_gh_0005():
    binary = ROOT / ".pytest-frontier-gh-0005"
    subprocess.run([
        "gcc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-pthread",
        str(ROOT / "lockless_queue.c"), str(ROOT / "frontier_gh_0005_test.c"),
        "-o", str(binary),
    ], check=True)
    run = subprocess.run([str(binary)], check=True, text=True, capture_output=True)
    assert "legacy ABA: stale_cas_succeeded=1 head_recycled_to_B=YES C_lost=YES" in run.stdout
    assert "tagged ABA: stale_cas_succeeded=0" in run.stdout
    assert "C_preserved=YES" in run.stdout
    assert "consumed=80000 unique=80000 final_epoch=160000" in run.stdout
