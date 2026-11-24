import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent
BIN = ROOT / "frontier_gh_0001_test"


def build_and_run():
    subprocess.run([
        "gcc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
        "-pthread", "lockless_queue.c", "frontier_gh_0001_test.c",
        "-latomic", "-o", str(BIN)
    ], cwd=ROOT, check=True)
    return subprocess.run([str(BIN)], cwd=ROOT, check=True,
                          capture_output=True, text=True).stdout.strip()


def test_reproduce_frontier_gh_0001():
    output = build_and_run()
    assert "legacy ABA reproduced" in output
    assert "CAS rejected stale generation" in output


def test_no_regression_frontier_gh_0001():
    assert "LIFO baseline passed" in build_and_run()


if __name__ == "__main__":
    print(build_and_run())
