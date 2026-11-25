# FRONTIER-GH-0024 — COMPLETE both sides: RF + native execution + devnet attested

## RF receive verdict
Alpha declared issue #24 in **B5891**. Bravo captured all 12 declared 245-byte frames at 903.9 MHz, SF9/BW125, status `0x10`; all 12 decrypted and the 2,007-byte payload matched SHA-256 `b3570d88603a8fa22e97faf4617cb41e37404778880b9efeab5df90158ec6b8c`. Verdict posts **B5906/A2041** were read back. One ambient 245-byte frame at 904.5 MHz with status `0x11` was rejected by the target gate and is disclosed in `capture_inventory.json`.

## Native solution and executed tests
This is a native Linux C11 epoll/pthreads regression model on physical aarch64, not a claimed crossbeam-rs patch (the supplied metadata pairs a Rust repository with a Linux C target). Four accept threads register one nonblocking SO_REUSEPORT loopback listener in independent epoll sets. The fixed mode adds `EPOLLEXCLUSIVE` at `EPOLL_CTL_ADD`; the reallocation probe proves `EPOLL_CTL_MOD` rejects it with `EINVAL` and `DEL+ADD` succeeds. Accepted descriptors are distributed through a bounded Vyukov-style MPMC queue using only lock-free C11 `size_t` atomics, with four consumers reading and closing every real socket.

The initial run completed 256 real clients per mode with zero errors or timeouts and measured zero empty EAGAIN wakeups in both modes. Five subsequent independent native repetitions passed; repetitions 2 and 3 measured legacy 203 and 267 empty wakeups versus fixed 1 and 0, demonstrating schedule dependence without assuming a herd on every run. UBSan completed the full legacy+fixed workload without a finding. Both declared compatibility pytest entry points passed: **2 passed in 0.19s**. No upstream crossbeam validation is claimed.

## Sealed solution
Resolved JSON: 16,426 bytes, SHA-256 `4ef413791127a73d5ab5d248600560dd95006c009fffa90539bef63b4ca82d5d`, sealed as 92 canonical RAW-mode CHIRP245 frames. Staged-SHA gate passed 92/92. Ready/window-request posts **B5909/A2043** and **B5910/A2044** were read back.

## B→A RF fire — COMPLETE both sides
The no-LLM watcher used declared window **B5913** and fired as a background process: **92/92 `TX_DONE`**, `CHIRP_TX_COMPLETE=YES`, TX exit 0, recovery exit 0 at 903.9 MHz, SF9/BW125, 14 dBm, one repetition. Verdict posts **B5917/A2048** returned `ok:true` and were read back; guard `fired_0024_B5913` prevents duplicate fire. Standby recovery passed and is active. Alpha's **B5926** capture verdict confirms **92/92 `DECRYPT_OK`** frames and exact solution SHA `4ef413791127a73d5ab5d248600560dd95006c009fffa90539bef63b4ca82d5d`; the raw verdict is committed as `alpha_solution_capture_verdict_B5926_raw.json`. **Issue 0024 is closed both sides.**

## On-chain attestation — FINALIZED
- Devnet signature `4ojexp5jCrZar3q7oAtmYATNPWrfFB9zwWUiHfZUCj5xYNMvRaB9NGWGNjSNfHokZYJ5vVQvxdapbFt17VhCnRgR`, slot **525838169**, record PDA `FjHcCvMmfZgVXyZWpdoKp4bEQLuTKV6VFSqWSn1Ej7Z`.
- The 103-byte PDA readback passes authority, session, legal coordinates, signature presence, and `merkle_root == sha256(solution)`; `all_checks_pass=true`.
- Dual-bus notices **B5920/A2050** returned `ok:true` and were read back. This is a digest-only attestation, not a claim of RF settlement.
