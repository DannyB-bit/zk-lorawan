# FRONTIER-GH-0014 — RF + real Tokio execution + on-chain attest complete; Alpha capture pending

## RF receive verdict (Bravo, 2026-11-23)

Alpha declared issue #14 in **B5476**. Bravo captured all 12 declared 245-byte frames at 903.9 MHz, SF9/BW125, status `0x10`; all 12 decrypted and the 2,018-byte payload matched SHA-256 `e348477f81df6fd22a49dae02124a46245ca0f7b9be4e90e69c579b8ab6419c0`. One additional 245-byte observation failed the target status/RF gate and was excluded. `frontier_issue_verdict` posts **B5486/A1799** were read back.

## Native solution and executed tests

This is a native Rust regression harness plus a **real Tokio 1.52.3 multi-thread runtime execution** on physical aarch64, not a claimed upstream Tokio patch.

- Legacy negative control: 256 ready local polls monopolize the worker; `GLOBAL_POLLS=0`, `LEGACY_STARVATION_REPRODUCED=YES`.
- Fixed scheduler model: cooperative budget accounting plus global fallback every 64 ticks yields `GLOBAL_FALLBACK_CHECKS=4` and `GLOBAL_POLLS=1` over 256 local ticks.
- Real Tokio integration: eight `CooperativeJob` futures execute on a two-worker Tokio runtime. Every poll passes through `tokio::task::coop::poll_proceed`, calls `made_progress` only after progress, wakes itself while incomplete, and forces a global-fallback Pending transition every 64 local ticks. A separate global-queue watchdog completed **16/16** yields within the 10-second fail-closed timeout: `COOPERATIVE_BUDGET_PASS=YES`.
- Offline Cargo build succeeded on Linux aarch64. Requested FAIL_TO_PASS/PASS_TO_PASS semantic entry points (hyphens normalized to valid Python identifiers): **2 passed in 0.05s**.
- An initial fixed-mode test exposed an off-by-one at tick 256 (257 polls); the terminal-tick branch was corrected, rebuilt, and all three native modes plus pytest rerun green. No passing result is inferred from that discarded run.

## B→A RF fire — COMPLETE; Alpha capture verdict pending

Resolved JSON: 7,621 bytes, SHA-256 `78990613ad9efc18871edc7d3530f944cd7ac707f4fdfd1475709d3fd09f72ac`, sealed as 43 canonical RAW-mode CHIRP245 frames. Staged-SHA gate passed 43/43.

Bravo fired inside Alpha window **B5491**, closing `2026-11-23T22:23:57Z`: **43/43 `TX_DONE`**, `CHIRP_TX_COMPLETE=YES`, TX exit 0, recovery exit 0 at 903.9 MHz, SF9/BW125, 14 dBm, 3-second gap, one repetition. Verdict posts **B5497/A1806** returned `ok:true`; guard `fired_0014_B5491` prevents duplicate fire. Standby recovery passed and is active. Receiver closure remains pending Alpha's exact-SHA DECRYPT_OK verdict.

## On-chain attestation — FINALIZED

- Devnet attestation finalized at slot **525573802**, signature `5SnDRDdiwcG57mh7prNYzB1Z…` (full signature in `onchain_attest_readback.json`).
- Record PDA `2aABGWNYMctZi7CKQfh9z3m4cc61RrXNBd6LTvB1BuSa` read back at 103 bytes: authority, session, legal coordinates, signature presence, and `merkle_root == sha256(solution)` all match; `all_checks_pass=true`.
- Dual-bus notices **B5498/A1807**. This is a digest-only attestation, not a claim of RF settlement.
