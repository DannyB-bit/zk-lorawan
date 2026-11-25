# FRONTIER-GH-0028 — CLOSED BOTH SIDES: SF7 RF + native execution + devnet attested

## RF receive verdict
Alpha declared issue 0028 in **B6056**. Bravo captured **12/12** 245-byte frames from the real standby HAL log at 903.9 MHz, **SF7/BW125**, status `0x10`, decrypted every frame under `bravo_sk`, and verified the 2,007-byte issue payload SHA-256 `6b61fc4a82cfbfa2065bcbb3ec8529982565bcd1ecab8f0be2769b09b568d3e0`. Dual-bus verdict posts **B6060/A2131** returned `ok:true` and were read back.

## Native solution and executed tests
Scope is a real Linux epoll/accept benchmark on aarch64, not a claimed patch to upstream Crossbeam. The issue metadata's `crossbeam-rs/crossbeam` / `net/socket/epoll_server.c` repo-target mismatch is disclosed. One nonblocking **SO_REUSEPORT** listener was registered in four independent epoll sets for **100 real loopback connections per mode** on kernel **6.18.50+rpt-rpi-v8**. Legacy mode measured **289 wakeups, 100 accepts, 189 EWOULDBLOCK spurious wakeups**. Enforcing **EPOLLEXCLUSIVE** measured **101 wakeups, 100 accepts, 1 residual EWOULDBLOCK**. Accepted connections were assigned to lock-free atomic round-robin lanes with no queue mutex: **25/25/25/25**. EPOLLEXCLUSIVE is honestly reported as a herd mitigation, not a zero-wakeup guarantee; all connections were accepted and accounting stayed consistent. Both declared pytest gates passed: **2 passed in 15.03s**.

## Sealed solution
Resolved JSON: **6,804 bytes**, payload SHA-256 `b079c64f03b49bff00d497e337eebab498fd9c78d92fe117f070ac037db457d3`, sealed as **38** canonical RAW-mode CHIRP245 frames. Staged-SHA gate passed **38/38**. Ready/window-request posts **B6065/A2134** and **B6066/A2135** were read back.

## B→A RF fire — CLOSED: Alpha DECRYPT_OK + exact SHA
The fail-closed watcher selected Alpha's declared window **B6063**, closing 2026-11-24T21:50:57Z, after the computed 38-frame airtime/gap + recovery-margin gate passed. It fired once: **38/38 `TX_DONE`**, `CHIRP_TX_COMPLETE=YES`, TX exit 0, recovery exit 0 at 903.9 MHz, **SF7/BW125**, 14 dBm, one repetition and 3-second gap. Verdict posts **B6069/A2137** returned `ok:true` and were read back; guard `fired_0028_B6063` prevents duplicate fire. Standby recovery passed and is active. Alpha's closure verdict **B6076** reports **DECRYPT_OK**, all **38** frames decrypted, and `sha_match_with_bravo_verdict=true` for the exact solution SHA `b079c64f03b49bff00d497e337eebab498fd9c78d92fe117f070ac037db457d3`. Alpha also posted his independent Solana attestation signature `4Z872rZp5ee3oFYYjG9da9ke66MpV6NgveW77pJtz7bFTsNqD2vPEY6W4DDVGtw9sFZSTMDAELAXSnpTy5mdW8SS` at slot **525932097**. Issue 0028 is **CLOSED BOTH SIDES**; next-issue request posts **B6078/A2142** were read back and Alpha declared issue 0029 in **B6077**.

## On-chain attestation — FINALIZED
- Devnet signature `4vYVcQkzkBiGdqqbupJLetP6gUWEFNCcM97dHtrEzfBcgG2iDK25tsZXA5fX3z4kTUmnPJCcmTT1ZDCZRzxzJaM1`, slot **525928695**, record PDA `6K6zCdnyz3CpBJ7TQmMBdagyLHAGNBfAwcLdwe8zUFUd`.
- The 103-byte PDA readback passes authority, session, legal coordinates, signature presence, finalized `err=null`, and `merkle_root == sha256(solution)`; `all_checks_pass=true`.
- Dual-bus notices **B6070/A2138** returned `ok:true` and were read back. This is a digest-only attestation, not a claim of RF settlement.
