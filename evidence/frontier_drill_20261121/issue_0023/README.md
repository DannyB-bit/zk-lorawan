# FRONTIER-GH-0023 — COMPLETE both sides: RF + native execution + devnet attested

## RF receive verdict
Alpha declared issue #23 in **B5857**. Bravo captured all 12 declared 245-byte frames at 903.9 MHz, SF9/BW125, status `0x10`; all 12 decrypted and the 2,033-byte payload matched SHA-256 `c4014c1d5e9d8862578fc9697054755c08c46c4a857e237eeae07c1660a4dffc`. Verdict posts **B5868/A2019** were read back. No rejected or non-target 245-byte frames were observed.

## Native solution and executed tests
This is a native C11/pthreads interpreter-list and tstate-lifetime regression model on physical aarch64, not a claimed upstream CPython patch. A deterministic two-thread schedule suspends a daemon thread at a `PyEval_SaveThread`-style GIL-release window while interpreter deletion runs. The legacy path mutates the list without requiring `head_mutex` and retains only a borrowed tstate pointer; poisoning the still-allocated model object exposes the stale access without invoking C undefined behavior. The fixed path takes a daemon-owned tstate reference, serializes list unlinking under `head_mutex`, and uses 32-bit acq_rel atomic decrements: deletion observes refcount 2→1 and retains the object; the daemon's valid access is followed by final 1→0 destruction.

Five repeated runs, 1,000 threaded stress schedules per run, seven compatibility pytest checks, and UBSan passed: **7 passed in 0.29s**. No upstream CPython integration validation is claimed.

## Sealed solution
Resolved JSON: 12,891 bytes, SHA-256 `459fdf65606b30cc7d39921670a0f1e45ce028468ce394d46285ee531a8beb43`, sealed as 72 canonical RAW-mode CHIRP245 frames. Staged-SHA gate passed 72/72. Ready/window-request posts **B5875/A2023** and **B5876/A2024** were read back.

## B→A RF fire — COMPLETE both sides
The no-LLM watcher used declared window **B5873** and fired as a background process: **72/72 `TX_DONE`**, `CHIRP_TX_COMPLETE=YES`, TX exit 0, recovery exit 0 at 903.9 MHz, SF9/BW125, 14 dBm, one repetition. Verdict posts **B5881/A2027** returned `ok:true` and were read back; guard `fired_0023_B5873` prevents duplicate fire. Standby recovery passed and is active. Alpha's **B5890** capture verdict confirms **72/72 `DECRYPT_OK`** frames and exact solution SHA `459fdf65606b30cc7d39921670a0f1e45ce028468ce394d46285ee531a8beb43`; the raw verdict is committed as `alpha_solution_capture_verdict_B5890_raw.json`. **Issue 0023 is closed both sides.**

## On-chain attestation — FINALIZED
- Devnet signature `5PppzKf3qRZ9onQ1NEbdw2rmVpRCxcMRJLFFJjYydm1D99JhWg7YnBF6fGdFeGkwbbgPfH5PREtr9fuaSFSZg4ke`, slot **525813113**, record PDA `EWPVJYEmyobiE7wLDsBpFRzpGnVuGgzNuiigsozhSmLp`.
- The PDA readback passes authority, session, legal coordinates, signature presence, and `merkle_root == sha256(solution)`; `all_checks_pass=true`.
- Dual-bus notices **B5882/A2028** returned `ok:true` and were read back. This is a digest-only attestation, not a claim of RF settlement.
