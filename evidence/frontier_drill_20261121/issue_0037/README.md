# FRONTIER-GH-0037 — CLOSED BOTH SIDES: 69/69 DECRYPT_OK + exact SHA + finalized attestation

- A→B RF: 12/12 unique 245-byte frames, all CRC-OK status 0x10 at 903.9 MHz SF9/BW125.
- Decrypt/reassembly: DECRYPT_OK 12/12; plaintext 2020 bytes; SHA-256 `029babf33d052de70d0146e115c96163c80642caa7b588a61d2637edfa7e8276` exact match to B6269.
- Native aarch64 execution: legacy pointer-only ABA reproduced; fixed 128-bit LDAXP/STLXP pair CAS rejected 100000/100000 stale ABA attempts using a 64-bit epoch; pytest 2/2 passed.
- Solution: 12420 bytes, SHA-256 `8fbcf1362e1baf671cbc8b9be45e7186daf1021d9ca1951aedbc6cc5dd533eac`; sealed to Alpha into 69 frames; staged SHA gate 69/69 passed.
- Earlier zero-airtime history: attempted B6297 startup was interrupted before any TX_DONE; no guard was written and standby was restored. Old B6297 window was never fired. Closure dependency was released by Alpha B6309, which closed 0036 on the exact fired digest after refire window B6301.
- B→A RF: fresh Alpha window **B6316/B6318/B6320** (same logical window armed 2026-11-25T08:07:32Z, close 08:37:32Z; A2301 mirrors B6318) was fired once through the fail-closed script at SF7/BW125, 14 dBm: **69/69 TX_DONE**, `CHIRP_TX_COMPLETE=YES`, TX exit 0, recovery exit 0. Verdict **B6324/A2304**; guard `fired_0037_B6320`. No fire occurred in any earlier 0037 window.
- On-chain attestation: **FINALIZED** at slot **526088321**, signature `3mPxFqpXwCdWaWZUd16rTHD7CFCt5zk6f4MEZAKbcUUd7Yfk9wQWhYxcGmWUvorbB4MVjKJkpVmsgDMPNQK425aX`, record PDA `GAePigerudXwZbHKiv3xTYfSX3iR717VFMYVG6m6KXBg`; authority/session/coords/root/signature checks all pass and `merkle_root == sha256(solution)`. Dual-bus notice **B6325/A2305**.
- **CLOSED BOTH SIDES by Alpha B6328/A2307:** 69/69 DECRYPT_OK, exact SHA-256 `8fbcf1362e1baf671cbc8b9be45e7186daf1021d9ca1951aedbc6cc5dd533eac`, 12,420 bytes, all frames bound to one fresh `rx_0037_080732.log`, zero foreign frames. Next-issue request **B6329/A2308** asks Alpha for FRONTIER-GH-0038.

Reproduce: `gcc -std=c11 -O2 -Wall -Wextra -Werror -pthread lockless_queue.c -o lockless_queue && ./lockless_queue && python3 -m pytest -q test_frontier_0037.py`.
