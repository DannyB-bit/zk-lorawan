# FRONTIER-GH-0022 — COMPLETE BOTH SIDES: RF + native execution + finalized devnet attestation

## RF receive verdict
Alpha declared issue #22 in **B5831**. Bravo captured all 12 declared 245-byte frames at 903.9 MHz, SF9/BW125, status `0x10`; all 12 decrypted and the 2,019-byte payload matched SHA-256 `91c6113d5e3ef33f8db5ebc4246ae0a85cc1cde5aabda59e6256ef84f10cf4de`. Verdict posts **B5836/A2000** were read back. No rejected or non-target 245-byte frames were observed.

## Native solution and executed tests
This is a native C11/pthreads scheduler regression model on physical aarch64, not a claimed Tokio patch. Four workers each poll a depth-4 nested unyielding local future for 4,096 scheduler ticks. The legacy path never decrements cooperative budget and never checks the shared global queue: all 256 global tasks starve at zero completions. The fixed path decrements a 32-bit per-worker budget on every local poll, checks the global queue at 64-tick boundaries and on budget exhaustion, and resets an exhausted budget to 128. An atomic global task index provides real cross-worker distribution.

Fixed execution completed all 256 global tasks with exact payload checksum while retaining all 16,384 local ticks and 65,536 nested polls. Five independent repetitions and UBSan passed; both compatibility pytest entry points passed: **2 passed in 0.06s**. No upstream Tokio validation is claimed.

## Sealed solution
Resolved JSON: 11,102 bytes, SHA-256 `12d04ca632a6543a7193fc0d3db83761467ebec58822abadacbbb6c9c13748fb`, sealed as 62 canonical RAW-mode CHIRP245 frames. Staged-SHA gate passed 62/62. Ready/window-request posts **B5839/A2002** and **B5840/A2003** were read back.

## B→A RF fire and Alpha capture — COMPLETE BOTH SIDES
The no-LLM watcher used fresh window **B5841** and fired as a background process: **62/62 `TX_DONE`**, `CHIRP_TX_COMPLETE=YES`, TX exit 0, recovery exit 0 at 903.9 MHz, SF9/BW125, 14 dBm, one repetition. Verdict posts **B5843/A2005** returned `ok:true` and were read back; guard `fired_0022_B5841` prevents duplicate fire. Standby recovery passed and is active.

Alpha's verdict **B5856** confirms **62/62 frames `DECRYPT_OK`**, reassembly, and exact SHA match with Bravo's solution verdict. The raw verdict is committed as `alpha_solution_capture_verdict_B5856_raw.json`; issue 0022 is closed both sides.

## On-chain attestation — FINALIZED
- Devnet attestation finalized at slot **525790661**, signature and record PDA in `onchain_attest_readback.json`.
- The 103-byte PDA readback passes authority, session, legal coordinates, signature presence, and `merkle_root == sha256(solution)`; `all_checks_pass=true`.
- Dual-bus notices **B5846/A2007** returned `ok:true` and were read back. This is a digest-only attestation, not a claim of RF settlement.
