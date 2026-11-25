// FRONTIER-GH-0026: native scheduler model, executed on aarch64.
// The legacy lane models an unyielding nested future pushed back at the local
// queue head without charging its cooperative budget. The fixed lane charges
// every local poll and checks the global queue at least once per 64 ticks.
use std::collections::VecDeque;
use std::env;

const COOPERATIVE_BUDGET: u32 = 128;
const GLOBAL_FALLBACK_TICKS: u64 = 64;

#[derive(Clone, Debug)]
enum Future {
    UnyieldingNested { id: u32 },
    GlobalCompletion { id: u32 },
}

struct Worker {
    local: VecDeque<Future>,
    global: VecDeque<Future>,
    ticks: u64,
    budget: u32,
    completed_global: Vec<u32>,
    first_global_tick: Option<u64>,
}

impl Worker {
    fn new(global_tasks: u32) -> Self {
        let local = (0..3).map(|id| Future::UnyieldingNested { id }).collect();
        let global = (0..global_tasks).map(|id| Future::GlobalCompletion { id }).collect();
        Self { local, global, ticks: 0, budget: COOPERATIVE_BUDGET,
               completed_global: Vec::new(), first_global_tick: None }
    }

    // Defect reproduction: no budget decrement and no global fallback.
    fn legacy_tick(&mut self) {
        self.ticks += 1;
        if let Some(Future::UnyieldingNested { id }) = self.local.pop_front() {
            self.local.push_front(Future::UnyieldingNested { id });
        }
    }

    // Fix: cooperative budget is charged for every local poll. A global check
    // occurs when the budget empties OR every 64 scheduler ticks, whichever
    // comes first. Unyielding work may continue only after that global check.
    fn fixed_tick(&mut self) {
        self.ticks += 1;
        if self.ticks % GLOBAL_FALLBACK_TICKS == 0 || self.budget == 0 {
            if let Some(Future::GlobalCompletion { id }) = self.global.pop_front() {
                self.completed_global.push(id);
                if self.first_global_tick.is_none() {
                    self.first_global_tick = Some(self.ticks);
                }
            }
            self.budget = COOPERATIVE_BUDGET;
            return;
        }
        if let Some(Future::UnyieldingNested { id }) = self.local.pop_front() {
            self.budget = self.budget.checked_sub(1).expect("budget underflow");
            self.local.push_front(Future::UnyieldingNested { id });
        }
    }
}

fn legacy() {
    let mut w = Worker::new(1);
    for _ in 0..4096 { w.legacy_tick(); }
    assert_eq!(w.completed_global.len(), 0);
    assert_eq!(w.global.len(), 1);
    println!("LEGACY_UNYIELDING_STARVATION_REPRODUCED=YES ticks={} global_completed=0 local_queue_len={} budget_unchanged={}",
             w.ticks, w.local.len(), w.budget);
}

fn fixed() {
    let mut w = Worker::new(1);
    w.fixed_tick();
    let budget_after_first_poll = w.budget;
    while w.completed_global.is_empty() { w.fixed_tick(); }
    assert_eq!(budget_after_first_poll, 127);
    assert_eq!(w.first_global_tick, Some(64));
    assert_eq!(w.completed_global, vec![0]);
    println!("FIXED_COOPERATIVE_BUDGET=PASS budget_after_first_poll={}", budget_after_first_poll);
    println!("FIXED_GLOBAL_FALLBACK=PASS first_global_tick=64 interval_ticks=64 global_completed=1");
}

fn stress() {
    let mut w = Worker::new(64);
    for _ in 0..4096 { w.fixed_tick(); }
    assert_eq!(w.completed_global.len(), 64);
    assert!(w.global.is_empty());
    assert_eq!(w.local.len(), 3, "unyielding local futures remain pending");
    println!("FIXED_GLOBAL_STRESS=PASS ticks={} global_completed=64 first_global_tick={} local_pending=3",
             w.ticks, w.first_global_tick.unwrap());
}

fn main() {
    match env::args().nth(1).as_deref() {
        Some("legacy") => legacy(),
        Some("fixed") => fixed(),
        Some("stress") => stress(),
        _ => { eprintln!("usage: cooperative_budget_model legacy|fixed|stress"); std::process::exit(2); }
    }
}
