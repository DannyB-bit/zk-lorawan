use std::collections::VecDeque;
use std::env;

#[derive(Clone, Copy)]
enum Task { UnyieldingNested, Global }

fn run(fixed: bool) -> Result<(u64, u64), String> {
    let mut local = VecDeque::from([Task::UnyieldingNested]);
    let mut global = VecDeque::from([Task::Global]);
    let mut ticks = 0u64;
    let mut global_completed = 0u64;
    let mut budget = 128u32;
    while ticks < 256 {
        ticks += 1;
        // Fixed worker: countdown every cooperative poll and force a global
        // fallback every 64 ticks, even while the local queue stays nonempty.
        if fixed { budget = budget.saturating_sub(1); }
        let forced_global = fixed && ticks % 64 == 0;
        let task = if forced_global || local.is_empty() {
            global.pop_front().or_else(|| local.pop_front())
        } else {
            local.pop_front()
        };
        match task {
            Some(Task::Global) => { global_completed += 1; }
            Some(Task::UnyieldingNested) => {
                // Nested future returns Pending without yielding to the runtime.
                local.push_back(Task::UnyieldingNested);
            }
            None => break,
        }
        if fixed && (budget == 0 || forced_global) { budget = 128; }
        if global_completed == 1 { break; }
    }
    if global_completed == 1 && ticks == 64 && local.len() == 1 {
        Ok((ticks, global_completed))
    } else {
        Err(format!("GLOBAL_STARVED ticks={ticks} global_completed={global_completed} local_pending={}", local.len()))
    }
}

fn main() {
    let fixed = env::args().nth(1).as_deref() == Some("--fixed");
    match run(fixed) {
        Ok((ticks, done)) => {
            println!("COOPERATIVE_BUDGET_PASS=YES ticks={ticks} global_completed={done} forced_global_every=64 budget=128");
        }
        Err(e) => {
            println!("LEGACY_STARVATION_REPRODUCED=YES {e}");
            std::process::exit(2);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test] fn legacy_starves() { assert!(run(false).is_err()); }
    #[test] fn fixed_checks_global_at_64() { assert_eq!(run(true).unwrap(), (64, 1)); }
}
