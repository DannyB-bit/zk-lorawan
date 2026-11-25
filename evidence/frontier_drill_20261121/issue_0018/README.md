# FRONTIER-GH-0018 — COMPLETE BOTH SIDES: RF + native execution + devnet attested

## RF receive verdict
Alpha declared issue #18 in **B5686/B5687**. Bravo captured all 12 declared 245-byte frames at 903.9 MHz, SF9/BW125, status `0x10`; all 12 decrypted and the 2,019-byte payload matched SHA-256 `01df968ada3567e1e8e91b9d4cb986f847ad0ec9fceca91c6127774661e73e37`. Verdict posts **B5693/A1916** returned `ok:true`. One ambient 245-byte status `0x11` frame on 904.5 MHz was excluded and disclosed in `capture_inventory.json`.

## Native solution and executed tests
This is a native Rust cooperative-budget scheduler regression model on physical aarch64, not a claimed upstream Tokio patch. The legacy negative control reproduced local-queue starvation (`LEGACY_STARVATION_REPRODUCED=YES`, 4,096 local polls and zero global completions). The fixed model passed at tick 64 (`GLOBAL_FALLBACK_PASS=YES`) and completed the 8-producer stress run with 80,000/80,000 consumed, checksum 3,199,960,000, and a maximum 64-tick global-check interval. Both requested pytest entry points passed: **2 passed in 0.10s**. Raw execution output is in `native_execution.log`; source is `worker.rs` and `test_frontier_0018.py`.

## B→A RF fire — COMPLETE BOTH SIDES
Resolved JSON: 6,953 bytes, SHA-256 `ae6d13c963cf0421a514c362fdd6ab6eb3004fc7aa2770e5e726e89d596cb40d`, sealed as 39 canonical RAW-mode CHIRP245 frames. Staged-SHA gate passed 39/39. Bravo fired inside Alpha's open window **B5707**, closing `2026-11-24T07:18:57Z`: **39/39 `TX_DONE`**, `CHIRP_TX_COMPLETE=YES`, TX exit 0, recovery exit 0 at 903.9 MHz, SF9/BW125, 14 dBm, 3-second gap, one repetition. Verdict posts **B5713/A1928** returned `ok:true`; guard `fired_0018_B5707` prevents duplicate fire. Standby recovery passed and is active. Alpha's receiver verdict **B5723** confirms **39/39 frames DECRYPT_OK** and exact SHA equality with Bravo's solution verdict. **Issue 0018 is therefore closed both sides.** Later open windows did not trigger a redundant re-fire.

## On-chain attestation — FINALIZED
- Devnet attestation finalized at slot **525707251**, signature `5QAxvMXUov5vNtbnxCRsGdwjD8yAHd2tZoXkrJ7KW2kR6bk2qodCSFTXTUwdfLefWz3Pu79AeZARNSNxU5a2ThEw`.
- Record PDA `Hyx9DUTjignQJzuWpEhwCoyi9zVxHZFpdtJ42fygB4ck` read back at 103 bytes: authority, session, legal coordinates, signature presence, and `merkle_root == sha256(solution)` all match; `all_checks_pass=true`.
- Dual-bus notices **B5714/A1929** returned `ok:true`. This is a digest-only attestation, not a claim of RF settlement.

## Pushed-artifact verification
A fresh sparse clone of pushed commit `f27e42135f3813c58cbc8c6bfcfc60c8d1bc24af` rebuilt the Rust worker, reproduced legacy starvation, passed fixed and 80,000-task stress execution, passed both pytest entry points (**2 passed in 0.36s**), verified all 39 staged frame SHAs and the solution digest, and checked the committed on-chain readback gates. Raw output: `fresh_clone_verification_f27e421.log`.
