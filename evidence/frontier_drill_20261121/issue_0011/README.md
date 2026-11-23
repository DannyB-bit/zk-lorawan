# FRONTIER-GH-0011 — RF + native tests + on-chain attest complete; Alpha capture pending

## RF receive verdict (Bravo, 2026-11-23)

Alpha declared issue #11 in **B5391**. Bravo captured all 12 declared 245-byte frames at 903.9 MHz, SF9/BW125, status `0x10`; all 12 decrypted and the 2,032-byte payload matched SHA-256 `315658bb513cc1f88af2d25a6ce6c6e7e16130d3e0950c5f13838dd7a3060622`. `frontier_issue_verdict` posts **B5402/A1748** were read back.

## Native solution and executed tests

Issue 0011 repeats the CPython SaveThread/Delete lifetime defect class proven in issue 0003. The issue metadata says `torvalds/linux`, but `Python/pylifecycle.c` belongs to CPython. The actual patch is against real `python/cpython` v3.12.0 at `0fb18b02c8ad56299d6a2910be0bab8ad601ef24`, touching `Include/cpython/pystate.h`, `Python/ceval_gil.c`, and `Python/pystate.c`; it is not represented as a Linux patch.

- The issue-0011 native model was recompiled on physical aarch64 with GCC 14.2.0: legacy free-while-SaveThread-pin-live ordering reproduced; fixed `head_mutex` detach and atomic-pin drain frees only after decrement to zero; no-pin baseline passes. **2/2 passed**.
- UBSan execution: **2/2 passed**. Requested FAIL_TO_PASS/PASS_TO_PASS pytest entry points: **2 passed in 0.10s**.
- The real patched CPython binary passed `test__xxsubinterpreters`, `test_embed`, and `test_threading` again in this run: **SUCCESS, 339 tests run, 13 skipped, 41.1s**.
- This is a deterministic regression model plus real CPython suites, not a claimed deterministic upstream race reproducer. The `file_sha256_of_this_json` field uses a documented zero-field hash convention; `solution_payload_sha256.txt` binds the final transmitted bytes.

## B→A RF fire — COMPLETE; Alpha capture verdict pending

Resolved JSON: 7,779 bytes, SHA-256 `f9431886d52fec42e6d2e63d8f5b5f3980c7f5acad2f8f0deb84501c4d3e2276`, sealed as 44 canonical RAW-mode CHIRP245 frames. Staged-SHA gate passed 44/44.

- Alpha's earlier windows closed before staging completed; **zero issue-0011 RF airtime occurred** before the fresh-window request. This timing miss is disclosed in ready/request posts **B5413/A1754** and **B5414/A1755**.
- Bravo fired inside Alpha window **B5411**, closing `2026-11-23T19:05:58Z`: **44/44 `TX_DONE`**, `CHIRP_TX_COMPLETE=YES`, TX exit 0, recovery exit 0 at 903.9 MHz, SF9/BW125, 14 dBm, 3-second gap, one repetition. Verdict posts **B5417/A1757** returned `ok:true`; guard `fired_0011_B5411` prevents duplicate fire. Standby recovery passed and is active.
- Alpha's `DECRYPT_OK` + exact-SHA capture verdict is still required before this issue is complete both sides.

## On-chain attestation — FINALIZED

- Devnet attestation finalized at slot **525525743**, signature `4gTsc3kYvdUky3HMZjbvAL1F…` (full signature in `onchain_attest_readback.json`).
- Record PDA `HM9pEhnoKuXoFjU3zzQfiZZb3Ky4w36wbChSEfCxBJby` read back at 103 bytes: authority, session, legal coordinates, signature presence, and `merkle_root == sha256(solution)` all match; `all_checks_pass=true`.
- Dual-bus notices **B5418/A1758**. This is a digest-only attestation, not a claim of RF settlement.
