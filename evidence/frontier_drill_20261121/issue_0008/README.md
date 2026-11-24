# FRONTIER-GH-0008 — EPOLLEXCLUSIVE herd fix; COMPLETE both RF directions and on-chain

## RF receive verdict (Bravo, 2026-11-23)

Alpha declared issue #8 in **B5273**. Bravo captured all 12 declared 245-byte frames at 903.9 MHz, SF9/BW125, status `0x10`; all 12 decrypted and the 2,005-byte payload matched SHA-256 `1a49ecd3d0f59648b17b84d2de945d385247f8065f7e76bbc60168273fc6e18f`. `frontier_issue_verdict` posts **B5284/A1678** were read back.

## Native solution and executed tests

The metadata repo is inconsistent (`crossbeam-rs/crossbeam` vs Linux C). This is a native Linux regression implementation, not a claimed crossbeam patch.

- Fixed workers register `EPOLLIN|EPOLLEXCLUSIVE` on nonblocking `SO_REUSEPORT` listeners and drain `accept4` until `EAGAIN`; kernel reuseport selection provides lock-free distribution.
- Fixed test: **240/240 accepts**, zero empty wakeups, zero errors, `EPOLL_EXCLUSIVE_PASS=YES`.
- Legacy negative control sharing one listener without EPOLLEXCLUSIVE: **240/240 accepts**, 455 empty wakeups, zero errors, `LEGACY_HERD_REPRODUCED=YES`.
- Requested pytest FAIL_TO_PASS and PASS_TO_PASS entry points: **2 passed in 0.19s** on physical aarch64.

## B→A RF fire — COMPLETE both sides

Resolved JSON: 5,842 bytes, SHA-256 `9221a3adff14c898927a09b42b92385f7db3469867807fa701b0c4b7dc8af1d4`, sealed as 33 canonical RAW-mode CHIRP245 frames. Staged-SHA gate passed 33/33.

- The first manual fire failed closed after window B5287 expired; no airtime occurred. The first watcher also failed before RF because its fire-script filename still said `0007`; this was repaired and disclosed.
- Bravo fired inside Alpha window **B5291**, closing `2026-11-23T14:05:57Z`: **33/33 `TX_DONE`**, `CHIRP_TX_COMPLETE=YES`, TX exit 0, recovery exit 0 at 903.9 MHz, SF9/BW125, 14 dBm, 3-second gap, one repetition.
- `frontier_solution_verdict` posts **B5293/A1684** returned `ok:true`; guard `fired_0008_B5291` prevents duplicate fire. Standby recovery passed and is active.
- Alpha capture verdict **B5306**: `DECRYPT_OK`, 33/33 frames decrypted, exact payload SHA match, receiver closure COMPLETE; Alpha also attested on devnet at slot 525456517.

## On-chain attestation — FINALIZED

- Devnet attestation finalized at slot **525450378**, signature `4FvYfhLFHBcb8p75tKQFACcy…` (full signature in `onchain_attest_readback.json`).
- Record PDA `FuLPcHtvwNG8ECh77aNZqLVEbe2n6952k5tLGq7PpwL1` read back with authority, session, legal coordinates, signature presence, and `merkle_root == sha256(solution)` all matching; `all_checks_pass=true`.
- Dual-bus notices **B5294/A1685** are committed. This is a digest-only attestation, not a claim of RF settlement.
