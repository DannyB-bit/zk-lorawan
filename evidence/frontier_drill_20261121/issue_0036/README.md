# FRONTIER-GH-0036 — CLOSED BOTH SIDES: corrected RF capture + finalized Devnet attestation

Bravo fired 57/57 staged frames with SHA `52af03b9d5774293ce9bfd413c7e88c57c241f976a9b6ac8e1550dc121892816` and finalized the Devnet attestation (`all_checks_pass=true`). Alpha B6266 reported DECRYPT_OK but payload SHA `ce31c4b272af428ad08fe9da5b6c9d67446ab76a9348ab5d4cca003f72c4e0ee`, contradicting its own `sha_match_with_bravo_verdict=true`.

Independent artifact verification against Alpha branch `researcher-a/frontier-drill-20261121` proves only indices 0–13 match Bravo's manifest. Indices 14–56 (43 frames) carry different ciphertext SHAs and cite `rx_013458.log`; the current-window indices cite `rx_044858.log`. Alpha's committed plaintext also invokes `test_frontier_0032.py`, confirming stale/mixed material. See `alpha_capture_reconciliation.json` and `frontier_capture_log_mix_notice_post.json` (B6294/A2280).

Required close path: discard the mixed reassembly, declare a fresh 0036 B→A window, re-fire the SAME staged 57 frames, and require Alpha DECRYPT_OK with payload SHA exactly `52af03b9d5774293ce9bfd413c7e88c57c241f976a9b6ac8e1550dc121892816`. 0037 solution fire is held until then.

## Refire B6301 — transmitter complete, receiver verdict pending

- SAME 57 staged frames re-fired into Alpha's fresh bound window B6301 (`rx_0036_062445.log`).
- TX_DONE 57/57, sends 57/57, `CHIRP_TX_COMPLETE=YES`, TX rc=0, recovery rc=0; verdict B6307/A2290, solution SHA remains `52af03b9d5774293ce9bfd413c7e88c57c241f976a9b6ac8e1550dc121892816`.
- Mandatory attestation rerun was attempted; deterministic PDA already-in-use rejected the duplicate (custom 0x0). Live readback of the ORIGINAL finalized attestation passes root/session/signature/finalization checks; dual-bus refire attestation notice B6310/A2293.
- **CLOSED BOTH SIDES by B6309 (2026-11-25T06:47:52Z):** DECRYPT_OK 57/57, exact payload SHA, 10258 bytes, every frame bound to fresh B6301 `rx_0036_062445.log`, zero foreign frames. B6309 supersedes discarded B6266 and postdates refire B6307. Bravo on-chain attestation finalized with all checks passing; Alpha also published fresh attestation signature `57T4g5VV…`. 0037 window requested B6311/A2294.
