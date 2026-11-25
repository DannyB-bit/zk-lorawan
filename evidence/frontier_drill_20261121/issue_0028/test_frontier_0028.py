import pathlib
import platform
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent
BIN = ROOT / "epoll_exclusive_native"

def build_and_run(mode: str) -> subprocess.CompletedProcess:
    if not BIN.exists():
        subprocess.run(["gcc", "-std=c11", "-O2", "-g", "-pthread", str(ROOT / "epoll_exclusive_native.c"), "-o", str(BIN)], check=True)
    return subprocess.run([str(BIN), mode], text=True, capture_output=True, timeout=30)

def metrics(output: str) -> dict:
    return {k: int(v) for k, v in re.findall(r"(rounds|wakeups|accepts|EWOULDBLOCK|spurious_wakeups)=(\d+)", output)}

def test_reproduce_frontier_gh_0028():
    assert platform.machine() == "aarch64"
    legacy = build_and_run("--legacy")
    assert legacy.returncode == 0, legacy.stdout + legacy.stderr
    lm = metrics(legacy.stdout)
    # Real-kernel negative control: without EPOLLEXCLUSIVE the same listener
    # wakes multiple epoll sets and losers observe EWOULDBLOCK.
    assert lm["spurious_wakeups"] > 0, legacy.stdout
    assert lm["EWOULDBLOCK"] > 0, legacy.stdout
    fixed = build_and_run("--exclusive")
    assert fixed.returncode == 0, fixed.stdout + fixed.stderr
    fm = metrics(fixed.stdout)
    assert fm["accepts"] == fm["rounds"]
    assert fm["EWOULDBLOCK"] == fm["spurious_wakeups"]
    # EPOLLEXCLUSIVE mitigates rather than guarantees zero wakeups on every
    # kernel race; require a measured reduction and no lost connections.
    assert 0 <= fm["spurious_wakeups"] < lm["spurious_wakeups"]

def test_no_regression_frontier_gh_0028():
    fixed = build_and_run("--exclusive")
    assert fixed.returncode == 0, fixed.stdout + fixed.stderr
    m = metrics(fixed.stdout)
    assert m["accepts"] == 100
    assert m["wakeups"] >= 100
    assert m["EWOULDBLOCK"] == m["spurious_wakeups"]
    assert m["spurious_wakeups"] <= 10
    lanes = [int(x) for x in re.search(r"lanes=([0-9,]+)", fixed.stdout).group(1).split(",")]
    assert sum(lanes) == 100
