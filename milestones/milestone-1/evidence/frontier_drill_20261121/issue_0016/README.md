# FRONTIER-GH-0016 — COMPLETE both sides: RF + native epoll execution + on-chain attest

## RF receive verdict (Bravo, 2026-11-24)

Alpha declared issue #16 in **B5545**. Bravo captured all 12 declared 245-byte frames at 903.9 MHz, SF9/BW125, status `0x10`; all 12 decrypted and the 2,006-byte payload matched SHA-256 `b2eeffd0302439a40c247a1a03537602138b4b546fb0d41878fb2ab589730bab`. `frontier_issue_verdict` posts **B5550/A1837** were read back.

## Native solution and executed tests

The metadata pairs `crossbeam-rs/crossbeam` with `net/socket/epoll_server.c`. This is a native Linux epoll/SO_REUSEPORT regression model on physical aarch64, not a claimed upstream Crossbeam patch or an upstream Crossbeam execution.

- Legacy negative control: one shared nonblocking listener registered in four independent epoll sets without `EPOLLEXCLUSIVE`. Over 240 loopback connections: **714 wakeups**, **240 accepts**, **474 empty `EWOULDBLOCK` accepts**, zero errors; `LEGACY_HERD_REPRODUCED=YES`.
- Fixed protocol: the original probe listener is closed, then four independent `SO_REUSEPORT` listeners are created on the reallocated port and registered with `EPOLLIN|EPOLLEXCLUSIVE`. Kernel reuseport distribution selects a socket while exclusive wakeup prevents the thundering herd; no userspace accept mutex serializes distribution.
- Fixed execution: **238 wakeups**, **240 accepts**, **zero empty `EWOULDBLOCK` accepts**, zero errors; `EPOLL_EXCLUSIVE_PASS=YES`.
- Native GCC 14.2.0 C11 build passed with `-Wall -Wextra -Werror`; requested semantic FAIL_TO_PASS/PASS_TO_PASS entry points (hyphens normalized to valid Python identifiers): **2 passed in 0.12s**.

## B→A RF fire — COMPLETE both sides

Resolved JSON: 6,347 bytes, SHA-256 `e6401916c914e7b3a2d1a5847f8677e34c8bdf138914090748629e8aa7c18120`, sealed as 36 canonical RAW-mode CHIRP245 frames. Staged-SHA gate passed 36/36.

Bravo fired inside Alpha window **B5551**, closing `2026-11-24T00:39:57Z`: **36/36 `TX_DONE`**, `CHIRP_TX_COMPLETE=YES`, TX exit 0, recovery exit 0 at 903.9 MHz, SF9/BW125, 14 dBm, 3-second gap, one repetition. Verdict posts **B5557/A1842** returned `ok:true`; guard `fired_0016_B5551` prevents duplicate fire. Standby recovery passed and is active.

Alpha receiver closure **B5563** at `2026-11-24T00:46:03Z`: `DECRYPT_OK`, 36 frames decrypted, `sha_match_with_bravo_verdict=true`, payload SHA exactly `e6401916c914e7b3a2d1a5847f8677e34c8bdf138914090748629e8aa7c18120`. Alpha reports the capture evidence committed on `researcher-a/frontier-drill-20261121`. Issue 0016 is closed on both RF sides; its Bravo devnet attestation below is independently finalized.

## On-chain attestation — FINALIZED

- Devnet attestation finalized at slot **525610995**, signature `5zvdCwBAm7Hvx5ZDQ9wXkgXm…` (full signature in `onchain_attest_readback.json`).
- Record PDA `5pGtsEbMdTdfV2dYriLChqQtiSHL9bLDa6LBmA557B6F` read back at 103 bytes: authority, session, legal coordinates, signature presence, and `merkle_root == sha256(solution)` all match; `all_checks_pass=true`.
- Dual-bus notices **B5558/A1843**. This is a digest-only attestation, not a claim of RF settlement.
