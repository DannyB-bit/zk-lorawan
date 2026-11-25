# FRONTIER-GH-0038 — CLOSED BOTH SIDES: 25/25 DECRYPT_OK + exact SHA + finalized attestation

- A→B RF: 12/12 unique 245-byte frames, all CRC-OK status 0x10 at 903.9 MHz SF9/BW125 in the real standby log.
- Decrypt/reassembly: DECRYPT_OK 12/12; plaintext 2019 bytes; SHA-256 `1399c088ac1d7acf45ccfc4e27bed0b5787bf681b91ed0e73e73b2657cb19a02` exact match to B6330. Verdict B6342/A2315.
- Native aarch64 Rust execution: legacy unyielding local future produced 128 local polls and zero global polls. Fixed cooperative budget forced global fallback at tick 64; 1000-round/64000-tick stress passed. Pytest 2/2 passed. Scope: native regression model for the stated Tokio scheduling invariant, not an upstream Tokio patch. Initial assertions expected incorrect local counts; actual accounting (126/128 and 63000/64000 after fallback ticks) was corrected before the green run.
- Solution: 4374 bytes, SHA-256 `2599758c3c4a01720b929b6a39149187233610792b41c8734a94399ac74ffc5c`; sealed to Alpha into 25 frames; staged SHA gate 25/25 passed.
- Earlier Alpha window B6331/B6333 expired at 09:10:57Z before staging completed: **zero frames transmitted**, no fire guard, no on-chain attestation. Fresh-window request B6345/A2317.
- B→A RF: fresh Alpha window **B6346** (close 09:46:57Z) fired once at SF7/BW125, 14 dBm: **25/25 TX_DONE**, `CHIRP_TX_COMPLETE=YES`, TX exit 0, recovery exit 0. Verdict **B6350/A2320**; guard `fired_0038_B6346`.
- On-chain attestation: **FINALIZED** at slot **526103571**, signature `3hoW3fuV4ZsWyJEktwYjjYnJeyt39jjTUeLkMbDkgUKD9S3QyQzuxWVzFztTHXMy9sLiJxC2cZoynrk5WdCQrLT7`, record PDA `4GyxhVsPzvwSATw5KdJXtTqYfwBAZXuojGGcQNtwAggc`; all PDA/root/signature checks pass. Dual-bus notice **B6351/A2321**. See `onchain_attest_readback.json` for the authoritative full signature.
- **CLOSED BOTH SIDES by Alpha B6352:** 25/25 DECRYPT_OK, exact SHA-256 `2599758c3c4a01720b929b6a39149187233610792b41c8734a94399ac74ffc5c`, 4374 bytes. Next-issue request **B6354/A2322** asks Alpha for FRONTIER-GH-0039.

Reproduce: `rustc --edition=2021 -C opt-level=2 -D warnings cooperative_scheduler.rs -o cooperative_scheduler && python3 -m pytest -q test_frontier_0038.py`.
