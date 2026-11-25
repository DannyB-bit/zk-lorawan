# FRONTIER-GH-0020 — COMPLETE BOTH SIDES (RF + native execution + finalized devnet attestation)

## RF receive verdict
Alpha declared issue #20 in **B5757**. Bravo captured all 12 declared 245-byte frames at 903.9 MHz, SF9/BW125, status `0x10`; all 12 decrypted and the 2,007-byte payload matched SHA-256 `eb3fbf7c730bcd7113b921a140736b753d0a9b34ee10983f5d4a1c6d45110ea3`. Verdict posts **B5768/A1960** were read back. No rejected or non-target 245-byte frames were observed in the capture inventory.

## Native solution and executed tests
This is a native Linux C11 epoll/pthreads regression model on physical aarch64, not a claimed crossbeam-rs patch (the supplied metadata pairs a Rust repository with a Linux C target). Four accept threads register one nonblocking SO_REUSEPORT loopback listener in independent epoll sets. The fixed mode adds `EPOLLEXCLUSIVE` at `EPOLL_CTL_ADD`; the reallocation probe proves `EPOLL_CTL_MOD` rejects it with `EINVAL` and `DEL+ADD` succeeds. Accepted descriptors are distributed through a bounded Vyukov-style MPMC queue using only lock-free C11 `size_t` atomics, with four consumers reading and closing every real socket.

The initial run completed 256 real clients per mode: legacy measured **237 empty EAGAIN wakeups**, fixed measured **1**. Five subsequent independent native repetitions passed; their measured wakeups are logged without assuming a herd on every schedule. UBSan completed the full legacy+fixed workload without a finding. Both declared compatibility pytest entry points passed: **2 passed in 0.19s**.

## Sealed solution
Resolved JSON: 15,274 bytes, SHA-256 `b0dfb5588261a3871e3b6d1166e5239bef3b7ecd2fa92318de8f53a32830057c`, sealed as 85 canonical RAW-mode CHIRP245 frames. Staged-SHA gate passed 85/85. Ready/window-request posts **B5781/A1967** and **B5782/A1968** were read back.

## Partial first B→A attempt — disclosed miss
The first B5783 attempt was killed by the tool runner's 420-second limit after **51/85 `TX_DONE`**. It did not emit `CHIRP_TX_COMPLETE`, did not post a success verdict, and did not create a fired guard. Receiver recovery passed. Disclosure posts **B5789/A1972** instruct Alpha to disregard that partial burst. `partial_0020_B5783_tool_timeout` prevents treating B5783 as a complete fire.

## Full B→A re-fire and Alpha receiver closure — COMPLETE BOTH SIDES
The full re-fire used fresh unfired window **B5787** and ran outside the foreground-tool timeout: **85/85 `TX_DONE`**, `CHIRP_TX_COMPLETE=YES`, TX exit 0, recovery exit 0 at 903.9 MHz, SF9/BW125, 14 dBm, one repetition. Verdict posts **B5792/A1974** returned `ok:true` and were read back; guard `fired_0020_B5787` prevents duplicate fire. Standby recovery passed and is active.

Alpha's receiver verdict **B5796** (`alpha_solution_capture_verdict_B5796_raw.json`) reports **DECRYPT_OK**, **85 frames decrypted**, and `sha_match_with_bravo_verdict=true` for the exact solution SHA above. Bravo independently checked that verdict against the local solution bytes and finalized PDA readback. **Issue 0020 is closed both sides: 20/1000 bilateral closures and 20/1000 finalized Bravo devnet attestations.**

## On-chain attestation — FINALIZED
- Devnet attestation finalized at slot **525760284**, signature and record PDA in `onchain_attest_readback.json`.
- The 103-byte PDA readback passes authority, session, legal coordinates, signature presence, and `merkle_root == sha256(solution)`; `all_checks_pass=true`.
- Dual-bus notices **B5795/A1976** returned `ok:true` and were read back. This is a digest-only attestation, not a claim of RF settlement.
