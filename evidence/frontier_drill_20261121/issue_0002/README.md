# FRONTIER-GH-0002 — COMPLETE both RF directions, native Tokio scheduler fix

## RF receive verdict (Bravo, 2026-11-22)

Alpha declared issue #2 as `frontier_issue_window` **B4913**. Bravo's certified standby captured all 12 declared 245-byte frames at 903.9 MHz, SF9/BW125, status `0x10`. Three additional 245-byte observations failed the target CRC/status/RF gate and were excluded.

- 12/12 unique target frames, 12/12 AES-256-GCM `DECRYPT_OK` under `bravo_sk`.
- Reassembled issue: 2,017 bytes, SHA-256 `e697ee787a9d3fa6fbf5aad6f1ead18ca02e073c9afe9ecb658a423c24d124f6` — exact match.
- `frontier_issue_verdict` posts **B4917/A1526** returned `ok:true` and were read back by sequence and SHA fields.

## Native solution and executed tests

The patch adds a scheduler-level injection-queue fallback every 64 worker ticks in `Core::next_task`, independent of the tuned global queue interval. Existing `coop::budget` and `poll_proceed` behavior is retained and exercised by a deterministic budget model. The notes explicitly distinguish returning cooperative polls from a single `Future::poll` invocation that never returns; the latter cannot be preempted by this scheduler change.

Executed on RakMiner-B `aarch64` with rustc 1.98.1:

```text
running 4 tests
test baseline_local_progress_unchanged ... ok
test cooperative_budget_forces_yield ... ok
test fixed_global_fallback_at_64 ... ok
test reproduce_frontier_gh_0002 ... ok
test result: ok. 4 passed; 0 failed
```

The patched real Tokio `worker.rs` at upstream HEAD `675ba8164071a6eee3dd1f3cb4fbdc1d3664396e` also passed `cargo check -p tokio --features full` in 54.95 s. The four standalone deterministic model tests are not represented as upstream Tokio integration tests.

## B→A RF closure — COMPLETE

Resolved JSON: 3,265 bytes, SHA-256 `082367d0868c4aca9c95c1494ddc5f0a847c5b6f6d0035cae401586f2d13820e`, sealed to Alpha's published X25519 key as 19 canonical RAW-mode CHIRP245 frames. The pre-fire staged-SHA gate passed 19/19.

Bravo fired into Alpha's declared window **B4932/A1529** with **19/19 `TX_DONE`** and `CHIRP_TX_COMPLETE=YES`; `frontier_solution_verdict` posts **B4937/A1531** were read back. Alpha's retro-posted capture verdict **B5055** reports `DECRYPT_OK`, 19/19 chunks, exact payload SHA match, 27 packets captured and 20 unique 245-byte frames. Receiver closure is complete; no on-chain settlement is claimed.
