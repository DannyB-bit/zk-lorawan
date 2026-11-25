# FRONTIER-GH-0021 — COMPLETE BOTH SIDES (RF + native execution + finalized devnet attestation)

## RF receive verdict
Alpha declared issue #21 in **B5797**. Bravo captured all 12 declared 245-byte frames at 903.9 MHz, SF9/BW125, status `0x10`; all 12 decrypted and the 2,020-byte payload matched SHA-256 `2720f5e3e4f888cb494f20f52b160538bba66441e7d13f189b24c3d08baea717`. Verdict posts **B5804/A1981** were read back. No rejected or non-target 245-byte frames were observed.

## Native solution and executed tests
This is a native C11/pthreads + aarch64 assembly regression model on the physical Cortex-A72, not a claimed CPython patch. A deterministic suspended-pop schedule starts `A→B→C`, performs two pops plus A recycling, then resumes the suspended CAS. Pointer-only CAS reproduces ABA and installs stale B. The fixed head is an aligned 128-bit `{pointer, uint64_t epoch}` pair; native `LDAXP/STLXP` performs acquire/release pair CAS without a mutex or libatomic fallback. Every pop/push increments the 64-bit epoch, so recycled A at epoch 3 rejects the suspended epoch-0 CAS and retry follows `A→C`.

Real execution rejected **100,000/100,000 tagged ABA schedules**, passed five independent repetitions, and passed UBSan with no finding. Both compatibility pytest entry points passed: **2 passed in 0.08s**. Objdump proves `LDAXP` and `STLXP` in the executed binary. Scope is head-pointer ABA using preallocated nodes; general safe memory reclamation is not claimed.

## Sealed solution
Resolved JSON: 16,350 bytes, SHA-256 `195fd0c11d47a6729de11805cfd3cc26c01c55473e2596ae8540757e6ac1edb6`, sealed as 91 canonical RAW-mode CHIRP245 frames. Staged-SHA gate passed 91/91. Ready/window-request posts **B5809/A1984** and **B5810/A1985** were read back.

## B→A RF fire and Alpha receiver closure — COMPLETE BOTH SIDES
The no-LLM watcher waited for fresh window **B5815** and fired as a background process: **91/91 `TX_DONE`**, `CHIRP_TX_COMPLETE=YES`, TX exit 0, recovery exit 0 at 903.9 MHz, SF9/BW125, 14 dBm, one repetition. Verdict posts **B5819/A1990** returned `ok:true` and were read back; guard `fired_0021_B5815` prevents duplicate fire. Standby recovery passed and is active.

Alpha's receiver verdict **B5830** (`alpha_solution_capture_verdict_B5830_raw.json`) reports **DECRYPT_OK**, **91 frames decrypted**, and `sha_match_with_bravo_verdict=true` for the exact solution SHA above. Bravo independently checked that verdict against the local solution bytes and finalized PDA readback. **Issue 0021 is closed both sides: 21/1000 bilateral closures and 21/1000 finalized Bravo devnet attestations.**

## On-chain attestation — FINALIZED
- Devnet attestation finalized at slot **525775917**, signature and record PDA in `onchain_attest_readback.json`.
- The 103-byte PDA readback passes authority, session, legal coordinates, signature presence, and `merkle_root == sha256(solution)`; `all_checks_pass=true`.
- Dual-bus notices **B5822/A1992** returned `ok:true` and were read back. This is a digest-only attestation, not a claim of RF settlement.
