const FALLBACK: u32 = 64;

#[derive(Clone, Copy)]
struct Worker {
    tick: u32,
    tuned_interval: u32,
    budget: u8,
    forced_fallback: bool,
}

impl Worker {
    fn buggy_next(&mut self, local_ready: bool, global_ready: bool) -> Option<&'static str> {
        self.tick = self.tick.wrapping_add(1);
        if self.tick % self.tuned_interval == 0 {
            if global_ready { return Some("global"); }
        }
        if local_ready { return Some("local"); }
        if global_ready { Some("global") } else { None }
    }

    fn fixed_next(&mut self, local_ready: bool, global_ready: bool) -> Option<&'static str> {
        self.tick = self.tick.wrapping_add(1);
        self.forced_fallback = self.tick % FALLBACK == 0;
        if self.forced_fallback || self.tick % self.tuned_interval == 0 {
            if global_ready { return Some("global"); }
            if local_ready { return Some("local"); }
            return None;
        }
        if local_ready { return Some("local"); }
        if global_ready { Some("global") } else { None }
    }

    // Model of coop::poll_proceed after made_progress commits the decrement.
    fn poll_nested_ready_future(&mut self) -> Result<(), &'static str> {
        if self.budget == 0 { return Err("forced yield"); }
        self.budget -= 1;
        Ok(())
    }
}

fn worker() -> Worker {
    // A large valid tuned interval makes the missing hard fallback observable.
    Worker { tick: 0, tuned_interval: 10_000, budget: 128, forced_fallback: false }
}

#[test]
fn reproduce_frontier_gh_0006() {
    let mut w = worker();
    for _ in 0..130 { assert_eq!(w.buggy_next(true, true), Some("local")); }
    assert_eq!(w.tick, 130, "global task was starved by continuous local work");
}

#[test]
fn fixed_global_fallback_at_64() {
    let mut w = worker();
    for expected_tick in 1..64 {
        assert_eq!(w.fixed_next(true, true), Some("local"));
        assert_eq!(w.tick, expected_tick);
    }
    assert_eq!(w.fixed_next(true, true), Some("global"));
    assert!(w.forced_fallback);
    assert_eq!(w.tick, 64);
}

#[test]
fn cooperative_budget_forces_yield() {
    let mut w = worker();
    for remaining in (0..128).rev() {
        assert_eq!(w.poll_nested_ready_future(), Ok(()));
        assert_eq!(w.budget, remaining);
    }
    assert_eq!(w.poll_nested_ready_future(), Err("forced yield"));
}

#[test]
fn baseline_local_progress_unchanged() {
    let mut w = worker();
    assert_eq!(w.fixed_next(true, false), Some("local"));
    assert_eq!(w.fixed_next(false, true), Some("global"));
    let mut empty = worker();
    assert_eq!(empty.fixed_next(false, false), None);
}
