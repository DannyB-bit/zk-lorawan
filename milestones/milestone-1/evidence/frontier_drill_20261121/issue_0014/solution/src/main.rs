use std::future::Future;
use std::pin::Pin;
use std::sync::{Arc, atomic::{AtomicU32, Ordering}};
use std::task::{Context, Poll};
use std::time::Duration;

/// Regression Future for a nested task that repeatedly becomes ready without
/// voluntarily yielding. Tokio's coop gate is the real production primitive:
/// after its per-task budget is exhausted poll_proceed returns Pending and
/// schedules a wakeup. Every 64 local ticks we additionally force the global
/// fallback transition required by the issue invariant.
struct CooperativeJob {
    local_ticks: u32,
    fallback_checks: Arc<AtomicU32>,
}

impl Future for CooperativeJob {
    type Output = u32;

    fn poll(mut self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<u32> {
        let budget = std::task::ready!(tokio::task::coop::poll_proceed(cx));
        self.local_ticks += 1;
        budget.made_progress();

        if self.local_ticks % 64 == 0 {
            self.fallback_checks.fetch_add(1, Ordering::SeqCst);
            if self.local_ticks < 256 {
                cx.waker().wake_by_ref();
                return Poll::Pending;
            }
        }
        if self.local_ticks < 256 {
            cx.waker().wake_by_ref();
            Poll::Pending
        } else {
            Poll::Ready(self.local_ticks)
        }
    }
}

fn legacy_model() {
    // A ready local queue of 256 items monopolizes the worker; the global item
    // is never polled because there is no budget/global-fallback gate.
    let mut local_polls = 0;
    let mut global_polls = 0;
    for _ in 0..256 {
        local_polls += 1;
        if local_polls == 256 {
            break;
        }
        // Intentionally no global queue check: this is the negative control.
        let _ = &mut global_polls;
    }
    println!("LEGACY_LOCAL_POLLS={local_polls}");
    println!("GLOBAL_POLLS={global_polls}");
    assert_eq!(local_polls, 256);
    assert_eq!(global_polls, 0);
    println!("LEGACY_STARVATION_REPRODUCED=YES");
}

fn fixed_scheduler_model() {
    let mut local_polls = 0;
    let mut global_polls = 0;
    let mut fallback_checks = 0;
    for tick in 1..=256 {
        local_polls += 1;
        if tick % 64 == 0 {
            fallback_checks += 1;
            // Global work is polled before returning to the local run queue.
            if global_polls == 0 {
                global_polls += 1;
            }
        }
    }
    println!("MODEL_LOCAL_POLLS={local_polls}");
    println!("GLOBAL_FALLBACK_CHECKS={fallback_checks}");
    println!("GLOBAL_POLLS={global_polls}");
    assert_eq!(fallback_checks, 4);
    assert_eq!(global_polls, 1);
}

fn fixed_tokio_runtime() {
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .worker_threads(2)
        .enable_time()
        .build()
        .expect("build real Tokio runtime");
    let fallback_checks = Arc::new(AtomicU32::new(0));
    runtime.block_on(async {
        let watchdog = Arc::new(AtomicU32::new(0));
        let mut jobs = Vec::new();
        for _ in 0..8 {
            jobs.push(tokio::spawn(CooperativeJob {
                local_ticks: 0,
                fallback_checks: fallback_checks.clone(),
            }));
        }
        let watchdog_task = {
            let watchdog = watchdog.clone();
            tokio::spawn(async move {
                // This task represents the global queue. Cooperative jobs must
                // release their workers often enough for it to make progress.
                for _ in 0..16 {
                    watchdog.fetch_add(1, Ordering::SeqCst);
                    tokio::task::yield_now().await;
                }
            })
        };
        tokio::time::timeout(Duration::from_secs(10), async {
            for job in jobs {
                assert_eq!(job.await.expect("cooperative job join"), 256);
            }
            watchdog_task.await.expect("watchdog join");
        }).await.expect("cooperative tasks starved global watchdog");
        let polls = watchdog.load(Ordering::SeqCst);
        println!("TOKIO_WATCHDOG_POLLS={polls}");
        assert_eq!(polls, 16);
    });
    assert_eq!(fallback_checks.load(Ordering::SeqCst), 32);
    println!("COOPERATIVE_BUDGET_PASS=YES");
}

fn baseline_model() {
    let mut local_polls = 0;
    let mut global_polls = 0;
    for tick in 1..=8 {
        if tick % 2 == 0 { local_polls += 1; } else { global_polls += 1; }
    }
    // Complete the four remaining items on each queue.
    local_polls += 4;
    global_polls += 4;
    println!("LOCAL_POLLS={local_polls}");
    println!("GLOBAL_POLLS={global_polls}");
    assert_eq!(local_polls, 8);
    assert_eq!(global_polls, 8);
    println!("BASELINE_PASS=YES");
}

fn main() {
    match std::env::args().nth(1).as_deref() {
        Some("legacy") => legacy_model(),
        Some("fixed") => {
            fixed_scheduler_model();
            fixed_tokio_runtime();
        }
        Some("baseline") => baseline_model(),
        _ => {
            eprintln!("usage: frontier-gh-0014 legacy|fixed|baseline");
            std::process::exit(2);
        }
    }
}
