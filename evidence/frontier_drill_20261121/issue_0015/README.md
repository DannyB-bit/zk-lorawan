# FRONTIER-GH-0015 — RF + native pthread execution + on-chain attest complete; Alpha capture pending

## RF receive verdict (Bravo, 2026-11-23)

Alpha declared issue #15 in **B5511**. Bravo captured all 12 declared 245-byte frames at 903.9 MHz, SF9/BW125, status `0x10`; all 12 decrypted and the 2,032-byte payload matched SHA-256 `b2cba195dbbd055f60d3bca7b6eb19110dfbdafcc2be11d51318a696e1681756`. Two additional 245-byte observations failed the target status/RF gate and were excluded. `frontier_issue_verdict` posts **B5520/A1820** were read back.

## Native solution and executed tests

The metadata pairs `torvalds/linux` with CPython's `Python/pylifecycle.c`. This is therefore a native pthread/C11 regression model of the specified lifetime protocol on physical aarch64, not a claimed upstream CPython patch or an upstream CPython execution.

- Legacy negative control: interpreter teardown unlinks and unmaps the page-backed tstate before the daemon's PyEval_SaveThread-equivalent read. The read deterministically raises `SIGSEGV` (shell exit 139; Python returncode `-11`).
- Fixed protocol: `head_mutex` protects every interpreter-list acquisition/unlink; a temporary atomic tstate reference is acquired while locked and held across the GIL-release section; atomic acq_rel decrements perform final destruction.
- Real concurrent fixed stress: **128 deletion rounds × 8 daemon savers**, **53,755 successful saves**, **54,108 head_mutex acquisitions**, **128 atomic deletes**, `SUBINTERPRETER_LIFETIME_PASS=YES`.
- Requested FAIL_TO_PASS/PASS_TO_PASS semantic entry points (hyphens normalized to valid Python identifiers): **2 passed in 0.28s**.
- An initial ASan build could not start on this aarch64 runtime: `sanitizer_allocator_primary64.h` CHECK failed while reserving its address range before test execution. No result is inferred from that environment failure; the deterministic mmap/munmap negative control and normal pthread fixed stress were used instead. An initial compile error was corrected before the passing build.

## B→A RF fire — COMPLETE; Alpha capture verdict pending

Resolved JSON: 8,479 bytes, SHA-256 `4b9d97b0f549e19e47a48652e97b9ead3eac1b611111664d7ff8d005a3b404a7`, sealed as 48 canonical RAW-mode CHIRP245 frames. Staged-SHA gate passed 48/48.

Bravo fired inside Alpha window **B5527**, closing `2026-11-23T23:49:57Z`: **48/48 `TX_DONE`**, `CHIRP_TX_COMPLETE=YES`, TX exit 0, recovery exit 0 at 903.9 MHz, SF9/BW125, 14 dBm, 3-second gap, one repetition. Verdict posts **B5533/A1828** returned `ok:true`; guard `fired_0015_B5527` prevents duplicate fire. Standby recovery passed and is active. Receiver closure remains pending Alpha's exact-SHA DECRYPT_OK verdict.

## On-chain attestation — FINALIZED

- Devnet attestation finalized at slot **525596034**, signature `2xJNgLA1fVaHG1Baw3aDmdFT…` (full signature in `onchain_attest_readback.json`).
- Record PDA `4tjHQu9CousTzGj3AQLhy7gjpqieUwBWVNuP5xGKcLRb` read back at 103 bytes: authority, session, legal coordinates, signature presence, and `merkle_root == sha256(solution)` all match; `all_checks_pass=true`.
- Dual-bus notices **B5534/A1829**. This is a digest-only attestation, not a claim of RF settlement.
