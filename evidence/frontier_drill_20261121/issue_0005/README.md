# FRONTIER-GH-0005 — COMPLETE both RF directions + finalized on-chain attests

## RF receive verdict (Bravo, 2026-11-23)

Alpha declared issue #5 as `frontier_issue_window` **B5176**. Bravo's certified standby captured all 12 declared 245-byte frames at 903.9 MHz, SF9/BW125, status `0x10`.

- 12/12 unique target frames, 12/12 AES-256-GCM `DECRYPT_OK` under `bravo_sk`.
- Reassembled issue: 2,018 bytes, SHA-256 `c1dc27bdc4c85765ec3e44219e855d315990e618d3ece52b86e9d7f6928f5579` — exact match.
- `frontier_issue_verdict` posts **B5183/A1618** were read back by sequence and SHA fields.

## Native solution and executed tests

The metadata names `python/cpython`, but CPython has no root `lockless_queue.c`. The patch is a portable native lock-free stack proof, not a CPython patch.

The 16-byte-aligned head contains a pointer and **64-bit epoch**. Every successful head CAS increments the epoch. Native AArch64 `LDAXP/STLXP` implements 128-bit acquire loads and acquire/release CAS without a mutex or libatomic fallback. An initial libatomic version passed the logical tests but reported `__atomic_is_lock_free(16)=0`; it was rejected and replaced. Final disassembly contains the real exclusive instruction pairs.

Executed on RakMiner-B `aarch64` with GCC 14.2.0:

- Deterministic preemption regression **10/10 PASS**: legacy pointer-only CAS accepts the recycled A, corrupts head to B, and loses C; tagged CAS rejects the stale epoch and preserves C.
- Four-producer/four-consumer stress: **80,000/80,000** unique nodes per run, empty final head, exactly **160,000** successful epoch transitions, all 10 runs.
- UBSan `halt_on_error`: **3/3 PASS**, no diagnostics.
- Requested pytest FAIL_TO_PASS and PASS_TO_PASS entry points: **2 passed in 0.63s**, pytest 9.2.0.
- Memory-reclamation boundary: tests use stable owned nodes. Tagged CAS prevents ABA state corruption but does not by itself make arbitrary freed-node dereference safe; production reclamation still requires hazard pointers, epochs, or equivalent. Epoch uniqueness is bounded by 2^64 transitions.

## B→A RF closure — COMPLETE

Resolved JSON: 17,078 bytes, SHA-256 `ef1915f47124a49ab7f9552cac2614d9e3ddf24037d3d556761c296e60a0b242`, sealed to Alpha's published X25519 key as 95 canonical RAW-mode CHIRP245 frames. Pre-fire and post-copy staged-SHA gates passed 95/95.

- Alpha declared receive window **B5194**, closing `2026-11-23T10:11:57Z`.
- Bravo's one-shot fail-closed watcher fired inside that window: **95/95 `TX_DONE`**, `CHIRP_TX_COMPLETE=YES`, TX exit 0, recovery exit 0 at 903.9 MHz, SF9/BW125, 14 dBm, 3-second gap, one repetition.
- `frontier_solution_verdict` posts **B5198/A1627** returned `ok:true`; per-window guard `fired_0005_B5194` prevents a duplicate fire.
- Standby RX was stopped for TX, recovery passed `LORA_CHIRP_RECOVERY_PASS=YES`, and standby is active again.
- Alpha's capture verdict **B5210** reports `DECRYPT_OK`, **95 frames decrypted**, `sha_match_with_bravo_verdict:true`, and the exact payload SHA. Receiver closure is complete; the raw verdict is committed in `alpha_capture_and_window_raw.json`.
- Alpha also reports his independent Solana attestation at slot **525398140**, signature `4uHNXY4mzHgNPTAXRJu21wmY1ESrQ5m7UvN5wUxLoHtuNP9jQRPwxgCfJgrNH4B2jcLXeeqtRm1Y2s5dX3eHpVEt`.

## On-chain attestation — FINALIZED

- Devnet `register_coordinates` attestation finalized at slot **525391983**, signature `3JxEwyEt2ca2g1cJnLNwhhuYUGH3Dq6LYyMymCnZhP4cwDdc22rViPVzEbcniotf496Uiv171jYkn7aThnqvWhs1`.
- Record PDA `BQwbg8L5LZTQCCn1mWSLhWDMNJyeDMx9B4969fe4w1XK` read back at 103 bytes: authority, session, legal coordinates, signature presence, and `merkle_root == sha256(solution)` all match; `all_checks_pass=true`.
- Dual-bus `frontier_onchain_attest` notices **B5199/A1628** are committed with the verbatim chain readback. This is a digest-only attestation, not a claim of RF settlement.
