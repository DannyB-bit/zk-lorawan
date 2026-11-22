# FRONTIER-GH-0002 — sealed A→B issue, native Tokio scheduler fix, B→A solution fired

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

## Sealed solution and B→A RF fire

Resolved JSON: 3,265 bytes, SHA-256 `082367d0868c4aca9c95c1494ddc5f0a847c5b6f6d0035cae401586f2d13820e`. It was sealed to Alpha's published X25519 key as 19 canonical RAW-mode CHIRP245 frames. The pre-fire staged-SHA gate passed 19/19.

`frontier_solution_ready` posts **B4919/A1527** returned `ok:true` and were read back. Alpha then declared `rx_window_open` **B4932/A1529**, armed 11:25:00Z and closing 12:55:00Z. Bravo fired into that declared window at 903.9 MHz, SF9/BW125, 14 dBm.

The native `b2a_solution_tx.log` records 19/19 `TX_DONE`, `CHIRP_TX_FRAMES=19/19_OK`, `CHIRP_TX_SENDS=19/19_OK`, and `CHIRP_TX_COMPLETE=YES`. Post-fire recovery passed at 11:53:03Z and the continuous RX listener re-armed. `frontier_solution_verdict` posts **B4937/A1531** returned `ok:true` and were read back.

This is a Bravo TX+staging verdict only: Alpha receive-side unique-frame count, `DECRYPT_OK`, and exact payload-SHA confirmation remain required before issue completion or any on-chain settlement claim.
