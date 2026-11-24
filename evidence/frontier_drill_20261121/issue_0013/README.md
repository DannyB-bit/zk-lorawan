# FRONTIER-GH-0013 — RF + native tests + on-chain attest complete; matching Alpha capture pending

## RF receive verdict (Bravo, 2026-11-23)

Alpha declared issue #13 in **B5451**. Bravo captured all 12 declared 245-byte frames at 903.9 MHz, SF9/BW125, status `0x10`; all 12 decrypted and the 2,019-byte payload matched SHA-256 `da1c9cae3f13808e8e57cff0edfe5baf6af893462c2b59bdb639025980b464c5`. `frontier_issue_verdict` posts **B5461/A1785** were read back.

## Native solution and executed tests

The issue metadata says `python/cpython`, but its `lockless_queue.c` target is not a CPython source path. The submitted artifact is therefore a deterministic two-pthread regression model of the specified ABA defect, not a claimed upstream CPython patch.

- Legacy negative control: a preempted consumer snapshots head A/next B; another consumer pops A and B then recycles A. The stale pointer-only CAS succeeds (`STALE_CAS_SUCCESS=1`), resurrects B, and leaves `B_SELF_CYCLE=1`; `LEGACY_ABA_REPRODUCED=YES`.
- Fixed tagged head: pointer + `uint64_t` epoch in a 128-bit GCC `__atomic`/libatomic compare-exchange on physical aarch64. Every pop/push increments the epoch. The stale A/epoch-0 CAS fails against A/epoch-3; a consistent retry pops A to C at epoch 4. `ABA_TAGGED_EPOCH_PASS=YES`.
- Baseline passes at final epoch 2. Requested FAIL_TO_PASS/PASS_TO_PASS semantic entry points (hyphens normalized to valid Python identifiers): **2 passed in 0.07s**. UBSan legacy/tagged/baseline all exited 0.
- An initial harness implementation failed before printing its fixed-mode result because its orchestrator reused a stale expected tagged value. That expected-state bug was corrected, the binary rebuilt, and all three modes rerun successfully; no passing result is inferred from the discarded run.
- This proves the required tagged-generation CAS invariant in the regression model. Production-safe memory reclamation still requires hazard epochs or an equivalent reclamation protocol.

## B→A RF fire — COMPLETE; matching Alpha capture verdict pending

Resolved JSON: 7,832 bytes, SHA-256 `13d1182eabb35a011ab19003cc09a192b5f34664858c52fdae919802c2194875`, sealed as 44 canonical RAW-mode CHIRP245 frames. Staged-SHA gate passed 44/44.

- Bravo fired inside Alpha window **B5470**, closing `2026-11-23T21:15:57Z`: **44/44 `TX_DONE`**, `CHIRP_TX_COMPLETE=YES`, TX exit 0, recovery exit 0 at 903.9 MHz, SF9/BW125, 14 dBm, 3-second gap, one repetition. Verdict posts **B5473/A1791** returned `ok:true`; guard `fired_0013_B5470` prevents duplicate fire. Standby recovery passed and is active.
- Alpha event **B5472** is preserved but does **not** close this fire: it predates Bravo verdict B5473 and binds different SHA-256 `367f2dc06e0fcf88345093789e57e0366c52590d9df6e9021996535f9b1e4eb9`. Bravo requested a fresh capture verdict for the exact B5473 payload in **B5475/A1793**. No receiver-closure claim is made from B5472.

## On-chain attestation — FINALIZED

- Devnet attestation finalized at slot **525559999**, signature `2W6ERPtXPiqqPh7JVzV935GG…` (full signature in `onchain_attest_readback.json`).
- Record PDA `4Luts3g9npz45vqVUjmc1jWfS575fwagR2cd6YkRBAde` read back at 103 bytes: authority, session, legal coordinates, signature presence, and `merkle_root == sha256(solution)` all match; `all_checks_pass=true`.
- Dual-bus notices **B5474/A1792**. This is a digest-only attestation, not a claim of RF settlement.
