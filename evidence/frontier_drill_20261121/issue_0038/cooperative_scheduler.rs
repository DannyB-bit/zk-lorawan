// FRONTIER-GH-0038: native regression model for Tokio local-queue starvation.
// A nested cooperative future is modeled by a local task that always requeues
// itself Pending. Legacy scheduling never consumes its global queue. The fixed
// scheduler decrements a 64-poll budget and performs a global fallback check.
use std::collections::VecDeque;
use std::env;

#[derive(Clone, Copy)]
struct Report { local_polls: u64, global_polls: u64, global_checks: u64, first_global_tick: u64 }

fn schedule(fixed: bool, ticks: u64) -> Report {
    let mut local = VecDeque::from([1_u32]); // unyielding nested future
    let mut global = VecDeque::from([99_u32]); // externally injected work
    let mut out = Report { local_polls: 0, global_polls: 0, global_checks: 0, first_global_tick: 0 };
    let mut budget = 64_u32;
    for tick in 1..=ticks {
        // The fix checks global work whenever the cooperative budget expires.
        if fixed && (budget == 0 || tick % 64 == 0) {
            out.global_checks += 1;
            if let Some(task) = global.pop_front() {
                assert_eq!(task, 99);
                out.global_polls += 1;
                if out.first_global_tick == 0 { out.first_global_tick = tick; }
            }
            budget = 64;
            continue;
        }
        if let Some(task) = local.pop_front() {
            assert_eq!(task, 1);
            out.local_polls += 1;
            local.push_back(task); // Pending: yields without doing global work
            if fixed { budget = budget.saturating_sub(1); }
        }
    }
    out
}

fn main() {
    let mode = env::args().nth(1).unwrap_or_else(|| "all".into());
    if mode == "legacy" || mode == "all" {
        let r = schedule(false, 128);
        assert_eq!((r.local_polls, r.global_polls, r.global_checks), (128, 0, 0));
        println!("LEGACY_UNYIELDING_LOCAL_STARVATION=REPRODUCED local_polls=128 global_polls=0");
    }
    if mode == "fixed" || mode == "all" {
        let r = schedule(true, 128);
        assert_eq!(r.global_polls, 1);
        assert_eq!(r.first_global_tick, 64);
        assert_eq!(r.global_checks, 2);
        assert_eq!(r.local_polls, 126);
        println!("FIXED_COOPERATIVE_BUDGET=PASS global_first_poll_tick=64 global_polls=1 local_polls=126");
    }
    if mode == "stress" || mode == "all" {
        let r = schedule(true, 64 * 1000);
        assert_eq!(r.global_polls, 1);
        assert_eq!(r.global_checks, 1000);
        assert_eq!(r.local_polls, 63_000);
        println!("GLOBAL_FALLBACK_STRESS=PASS rounds=1000 interval_ticks=64 global_checks=1000");
    }
    if mode == "all" { println!("FRONTIER_GH_0038_PASS=YES budget=64 starvation=FIXED"); }
}
