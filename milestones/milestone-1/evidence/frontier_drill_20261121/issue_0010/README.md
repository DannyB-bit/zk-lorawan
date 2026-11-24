# FRONTIER-GH-0010 — CLOSED both sides; RF + native tests + on-chain attest complete

## RF receive verdict (Bravo, 2026-11-23)

Alpha declared issue #10 in **B5353**. Bravo captured all 12 declared 245-byte frames at 903.9 MHz, SF9/BW125, status `0x10`; all 12 decrypted and the 2,018-byte payload matched SHA-256 `cbf396dcd65fee01b3d9e0ad0180b38a71b044f9a4af73b1edeffb6cabe0efa8`. `frontier_issue_verdict` posts **B5366/A1726** were read back.

## Native solution and executed tests

This is a native Rust scheduler regression model for the declared Tokio worker starvation issue, not a claimed upstream Tokio patch.

- Legacy negative control: nonempty local queue repeatedly polls an unyielding nested future; after 256 ticks the global task remains unfinished (`global_completed=0`), exit **2**, `LEGACY_STARVATION_REPRODUCED=YES`.
- Fixed worker decrements a 128-poll cooperative budget and forces global-queue fallback every 64 ticks despite pending local work. Global completion occurs exactly at tick **64**, `COOPERATIVE_BUDGET_PASS=YES`.
- Rust unit tests: **2/2 passed**. Requested FAIL_TO_PASS/PASS_TO_PASS pytest entry points: **2 passed in 0.13s** on physical aarch64, rustc 1.98.1.
- Initial fixed harness ran to the 256-tick bound instead of stopping after global completion; that discarded failure was corrected by breaking on completion before the final passing runs.

## B→A RF fire and Alpha capture — COMPLETE

Resolved JSON: 4,171 bytes, SHA-256 `e775213044a75678735992d9df07a9faea07e47b1015ef3e4a776fa68b924d60`, sealed as 24 canonical RAW-mode CHIRP245 frames. Staged-SHA gate passed 24/24.

- First fire attempt failed closed because Alpha window B5354 had closed at `2026-11-23T16:57:57Z`; **zero RF airtime occurred**. Fresh-window request posts **B5372/A1730** disclose this miss.
- Bravo fired inside fresh Alpha window **B5373**, closing `2026-11-23T17:33:57Z`: **24/24 `TX_DONE`**, `CHIRP_TX_COMPLETE=YES`, TX exit 0, recovery exit 0 at 903.9 MHz, SF9/BW125, 14 dBm, 3-second gap, one repetition. Verdict posts **B5375/A1732** returned `ok:true`; guard `fired_0010_B5373` prevents duplicate fire in that window.
- Alpha's delayed capture verdict **B5389** reports `DECRYPT_OK`, all **24 frames decrypted**, and exact payload-SHA agreement with Bravo's verdict. This closes the receiver side; the full raw event is committed as `alpha_capture_verdict_raw.json`.
- Before that delayed verdict was observed, Bravo lawfully re-fired the **same SHA-gated frames** into new, unfired Alpha window **B5387** (one fire per window seq): **24/24 `TX_DONE`**, `CHIRP_TX_COMPLETE=YES`, TX/recovery exit 0. Verdict posts **B5390/A1741** and guard `fired_0010_B5387` are committed. The current TX log therefore records the B5387 fire; B5373's original verdict JSON preserves its RF evidence.

## On-chain attestation — FINALIZED

- Devnet attestation finalized at slot **525500600**, signature `3LPJohzL8TdErNGFp94jf9w3…` (full signature in `onchain_attest_readback.json`).
- Record PDA `2BroMyWxAo1Pc22zNNhiDqa7Y5h8xsZSJ3BS2D8oCFsx` read back at 103 bytes: authority, session, legal coordinates, signature presence, and `merkle_root == sha256(solution)` all match; `all_checks_pass=true`.
- Dual-bus notices **B5376/A1733**. This is a digest-only attestation, not a claim of RF settlement.
