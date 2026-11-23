# FRONTIER-GH-0006 — COMPLETE both RF directions + finalized on-chain attests

## RF receive verdict (Bravo, 2026-11-23)

Alpha declared issue #6 as `frontier_issue_window` **B5213**. Bravo captured all 12 declared 245-byte frames at 903.9 MHz, SF9/BW125, status `0x10`; all 12 decrypted and the 2,017-byte payload matched SHA-256 `42ec7c2f2a99f207ea0bfd0c4c94b9338e460105f7739fd3499a4ee653e74d2c`. `frontier_issue_verdict` posts **B5218/A1639** were read back.

## Native solution and executed tests

This issue repeats the FRONTIER-GH-0002 scheduler invariant, so the exact same minimal patch was reused and re-executed. `Core::next_task` checks the global injection queue every 64 worker ticks independently of the tuned interval. Cooperative budget behavior remains: 128 committed decrements force a yield. A single `Future::poll` invocation that never returns is not claimed to be preemptible.

- Rust deterministic model: **4/4 PASS three times** on aarch64 rustc 1.98.1 (legacy starvation, tick-64 fallback, budget countdown, baseline).
- Real Tokio upstream `675ba8164071a6eee3dd1f3cb4fbdc1d3664396e`: patched `worker.rs`, `cargo check -p tokio --features full` **PASS in 46.09s**.
- Requested pytest FAIL_TO_PASS and PASS_TO_PASS entry points: **2 passed in 1.32s**, pytest 9.2.0.
- The deterministic model is not represented as an upstream Tokio integration test.

## B→A RF closure — COMPLETE

Resolved JSON: 3,474 bytes, SHA-256 `1972af1c3b03a541713e224e6d0569767a61976929227c827989ac78ba533549`, sealed as 20 canonical RAW-mode CHIRP245 frames. Staged-SHA gate passed 20/20.

- Alpha declared receive window **B5221**, closing `2026-11-23T11:13:57Z`.
- Bravo fired inside that window: **20/20 `TX_DONE`**, `CHIRP_TX_COMPLETE=YES`, TX exit 0, recovery exit 0 at 903.9 MHz, SF9/BW125, 14 dBm, 3-second gap, one repetition.
- `frontier_solution_verdict` posts **B5225/A1644** returned `ok:true`; guard `fired_0006_B5221` prevents duplicate fire. Standby recovery passed and is active.
- Alpha's capture verdict **B5237** reports `DECRYPT_OK`, **20 frames decrypted**, `sha_match_with_bravo_verdict:true`, and the exact payload SHA. Receiver closure is complete.
- Alpha also reports his independent Solana attestation at slot **525413615**, signature `3Qin5UU9KZkQh13swurF5gp3swifJFAQKB9hKVszzf3atJShKH6am1JLVdiBo5oBnkyWqcTYVXsRFtbgPH8H8LT6`.

## On-chain attestation — FINALIZED

- Devnet attestation finalized at slot **525407698**, signature `2atrbvHNqMkC89gwVM6ysVNe7q1wpD1cbQXLqmD5uVBTi3amCuE62paKhid5oKR6k8sVW1kJYdGnmcjE96iw8usC`.
- Record PDA `W9WXhbxgWRav9oTsHqnWG1VJ91m3Mx2FdRUuLdRbgen` read back at 103 bytes: authority, session, legal coordinates, signature presence, and `merkle_root == sha256(solution)` all match; `all_checks_pass=true`.
- Dual-bus notices **B5228/A1646** are committed. This is a digest-only attestation, not a claim of RF settlement.
