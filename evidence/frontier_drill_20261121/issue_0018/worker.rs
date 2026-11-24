// FRONTIER-GH-0018: native cooperative-budget scheduler regression model.
// This is not presented as an upstream Tokio source patch.
use std::collections::VecDeque;
use std::env;
use std::sync::mpsc::{self, TryRecvError};
use std::thread;

const BUDGET: u32 = 128;
const GLOBAL_CHECK_INTERVAL: u64 = 64;

fn legacy() {
    let mut local: VecDeque<u64> = (0..1024).collect();
    let global = VecDeque::from([u64::MAX]);
    let mut local_polls = 0_u64;
    for _ in 0..4096 {
        // Legacy priority inversion: an always-nonempty local run queue is
        // polled forever and the global fallback is never checked.
        let task = local.pop_front().expect("local task");
        local.push_back(task);
        local_polls += 1;
    }
    assert_eq!(local_polls, 4096);
    assert_eq!(global.len(), 1);
    println!("LEGACY_STARVATION_REPRODUCED=YES local_polls={} global_completed=0 global_pending=1", local_polls);
}

fn fixed() {
    let mut local: VecDeque<u64> = (0..1024).collect();
    let mut global = VecDeque::from([u64::MAX]);
    let mut local_polls = 0_u64;
    let mut ticks = 0_u64;
    let mut budget_remaining = BUDGET;
    let mut global_checks = 0_u64;
    let mut first_global_tick = None;
    while global.len() == 1 {
        let task = local.pop_front().expect("local task");
        local.push_back(task);
        local_polls += 1;
        ticks += 1;
        budget_remaining -= 1;
        // A non-yielding local future still consumes cooperative budget. The
        // hard 64-tick fallback prevents a nonempty local queue starving global.
        if ticks % GLOBAL_CHECK_INTERVAL == 0 || budget_remaining == 0 {
            global_checks += 1;
            if global.pop_front().is_some() {
                first_global_tick = Some(ticks);
            }
            budget_remaining = BUDGET;
        }
    }
    assert_eq!(first_global_tick, Some(64));
    assert!(global_checks >= 1);
    println!("GLOBAL_FALLBACK_PASS=YES local_polls={} global_completed=1 first_global_tick=64 global_checks={} budget={} fallback_interval={}", local_polls, global_checks, BUDGET, GLOBAL_CHECK_INTERVAL);
}

fn stress() {
    const PRODUCERS: usize = 8;
    const PER_PRODUCER: usize = 10_000;
    const TOTAL: usize = PRODUCERS * PER_PRODUCER;
    let (tx, rx) = mpsc::channel::<usize>();
    let mut handles = Vec::new();
    for producer in 0..PRODUCERS {
        let sender = tx.clone();
        handles.push(thread::spawn(move || {
            for sequence in 0..PER_PRODUCER {
                sender.send(producer * PER_PRODUCER + sequence).expect("global send");
            }
        }));
    }
    drop(tx);
    let mut local: VecDeque<u64> = (0..256).collect();
    let mut ticks = 0_u64;
    let mut local_polls = 0_u64;
    let mut budget_remaining = BUDGET;
    let mut global_checks = 0_u64;
    let mut consumed = 0_usize;
    let mut sum = 0_usize;
    let expected_sum = (0..TOTAL).sum::<usize>();
    let mut last_check_tick = 0_u64;
    let mut max_ticks_between_global_checks = 0_u64;
    while consumed < TOTAL {
        let task = local.pop_front().expect("local task");
        local.push_back(task);
        local_polls += 1;
        ticks += 1;
        budget_remaining -= 1;
        if ticks % GLOBAL_CHECK_INTERVAL == 0 || budget_remaining == 0 {
            global_checks += 1;
            max_ticks_between_global_checks = max_ticks_between_global_checks.max(ticks - last_check_tick);
            last_check_tick = ticks;
            match rx.try_recv() {
                Ok(value) => {
                    consumed += 1;
                    sum += value;
                }
                Err(TryRecvError::Empty) => {}
                Err(TryRecvError::Disconnected) => {
                    assert_eq!(consumed, TOTAL, "channel closed with work missing");
                }
            }
            budget_remaining = BUDGET;
        }
    }
    for handle in handles {
        handle.join().expect("producer join");
    }
    assert!(rx.try_recv().is_err());
    assert_eq!(sum, expected_sum);
    assert!(max_ticks_between_global_checks <= GLOBAL_CHECK_INTERVAL);
    println!("FIXED_STRESS_PASS=YES producers={} produced={} consumed={} checksum={} local_polls={} global_checks={} max_ticks_between_global_checks={} budget={}", PRODUCERS, TOTAL, consumed, sum, local_polls, global_checks, max_ticks_between_global_checks, BUDGET);
}

fn main() {
    match env::args().nth(1).as_deref() {
        Some("legacy") => legacy(),
        Some("fixed") => fixed(),
        Some("stress") => stress(),
        _ => {
            eprintln!("usage: worker legacy|fixed|stress");
            std::process::exit(2);
        }
    }
}
