# FRONTIER-GH-0012 — RF + native tests + on-chain attest complete; Alpha capture pending

## RF receive verdict (Bravo, 2026-11-23)

Alpha declared issue #12 in **B5427**. Bravo captured all 12 declared 245-byte frames at 903.9 MHz, SF9/BW125, status `0x10`; all 12 decrypted and the 2,006-byte payload matched SHA-256 `0f4fa240bf7738fd5ce75e5cffb1dd6f44c6a0b38c11751a2872eef6f8fcc02a`. Two additional 245-byte observations failed the target status/RF gate and were excluded. `frontier_issue_verdict` posts **B5432/A1767** were read back.

## Native solution and executed tests

Issue 0012 repeats the issue-0008 EPOLLEXCLUSIVE herd scenario. The metadata repo is inconsistent (`crossbeam-rs/crossbeam` vs Linux C). This is a native Linux regression implementation, not a claimed crossbeam patch.

- Fixed workers register `EPOLLIN|EPOLLEXCLUSIVE` on nonblocking `SO_REUSEPORT` listeners and drain `accept4` until `EAGAIN`; kernel reuseport selection provides lock-free distribution.
- Fixed test: **240/240 accepts**, zero empty wakeups, zero errors, `EPOLL_EXCLUSIVE_PASS=YES`.
- Legacy negative control sharing one listener without EPOLLEXCLUSIVE: **240/240 accepts**, **302 empty wakeups**, zero errors, `LEGACY_HERD_REPRODUCED=YES`.
- Requested pytest FAIL_TO_PASS and PASS_TO_PASS entry points: **2 passed in 0.18s** on physical aarch64.
- An initial shell chaining typo attempted to execute the numeric `PIPESTATUS` value rather than the legacy binary. It was corrected; the standalone legacy run and both pytest entry points then executed successfully. No result is inferred from the discarded shell error.

## B→A RF fire — COMPLETE; Alpha capture verdict pending

Resolved JSON: 6,130 bytes, SHA-256 `fdc47bda9f14964bb214bd271a4a647cf81dbdc438c0087448857102b142bf76`, sealed as 35 canonical RAW-mode CHIRP245 frames. Staged-SHA gate passed 35/35.

- Bravo fired inside Alpha window **B5435**: **35/35 `TX_DONE`**, `CHIRP_TX_COMPLETE=YES`, TX exit 0, recovery exit 0 at 903.9 MHz, SF9/BW125, 14 dBm, 3-second gap, one repetition. Verdict posts **B5441/A1773** returned `ok:true`; guard `fired_0012_B5435` prevents duplicate fire. Standby recovery passed and is active.
- Alpha's `DECRYPT_OK` + exact-SHA capture verdict is still required before this issue is complete both sides.

## On-chain attestation — FINALIZED

- Devnet attestation finalized at slot **525538520**, signature `5nR2oct8243NokcLd2QhSKyo…` (full signature in `onchain_attest_readback.json`).
- Record PDA `7MMqjLfMf6esS5H187sQLMSoNYFZoaTLuKTy8vSfYdzJ` read back at 103 bytes: authority, session, legal coordinates, signature presence, and `merkle_root == sha256(solution)` all match; `all_checks_pass=true`.
- Dual-bus notices **B5442/A1774**. This is a digest-only attestation, not a claim of RF settlement.
