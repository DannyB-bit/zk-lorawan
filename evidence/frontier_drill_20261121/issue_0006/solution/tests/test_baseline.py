import pathlib


ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_no_regression_frontier_gh_0006():
    patch = (ROOT / "worker.rs.patch").read_text()
    assert "GLOBAL_QUEUE_FALLBACK_INTERVAL: u32 = 64" in patch
    assert "self.tick % GLOBAL_QUEUE_FALLBACK_INTERVAL == 0" in patch
    assert "self.tick % self.global_queue_interval == 0" in patch
    source = (ROOT / "frontier_gh_0006_test.rs").read_text()
    assert "self.budget -= 1" in source
    assert "baseline_local_progress_unchanged" in source
