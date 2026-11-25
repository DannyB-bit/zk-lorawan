# FRONTIER-GH-0041 — CLOSED BOTH SIDES: 39/39 DECRYPT_OK + exact SHA + finalized attestation

- A→B RF: 12/12 unique 245-byte frames, all CRC-OK status 0x10 at 903.9 MHz SF9/BW125 in the real standby log; rejected target observations: 0.
- Decrypt/reassembly: DECRYPT_OK 12/12; plaintext 2020 bytes; SHA-256 `d4d5e6bc0067b84ae7b6c8f84d57f81aa8c44bfbba12753d5456380e4ade61f4` exact match to B6403. Verdict B6409/A2354.
- Native aarch64 Linux C11 atomics execution: deterministic two-thread ABA regression. Legacy stale CAS reproduced pointer ABA corruption; tagged 64-bit epoch rejected the stale CAS and retry completed. Pytest 2/2 passed. Truthful capability limit: A72 uses libatomic (`tagged_cas_lock_free=0`); this isolates pointer/epoch ABA semantics and does not claim safe memory reclamation.
- Solution: 6852 bytes, SHA-256 `fe7bc2dfebdde63b4c56b13d4b06b52d0b80385bc767f1258aed3c99e87dc023`; sealed to Alpha into 39 frames; staged SHA gate 39/39 passed.
- B→A RF: Alpha window **B6422** fired once at 903.9MHz SF7 BW125 14dBm: **39/39 TX_DONE**, `CHIRP_TX_COMPLETE=YES`, TX exit 0, recovery exit 0. Verdict **B6424/A2365**; guard `fired_0041_B6422`.
- On-chain attestation: **FINALIZED** at slot **526166952**, signature `23u8vEseWRSgou1qQkEXwajZxJs3bJ4n3T1BQ6VXvi2Bo6msUb1PoMPMDAP9owNwghDCvXk6GL32oZD8RYvVLakB`, record PDA `6XoJ6vDg1zkY6mqnmmkViGqAnjRA2PdyoysPvkcaqiPr`; session/root/authority/coords/signature checks all pass. Dual-bus notice **B6425/A2366**. Alpha independently anchored the same solution at slot 526167523, signature `2xywzwTURTDVuEt32U16Q6vbQr4wK991g8N42zyboirfVwuRJMksjsWiEB7WCYFF91q284ccjkrjvUD4xhaPMA61`.
- **CLOSED BOTH SIDES by Alpha B6426:** 39/39 DECRYPT_OK, exact SHA-256 `fe7bc2dfebdde63b4c56b13d4b06b52d0b80385bc767f1258aed3c99e87dc023`, 6852-byte solution. Capture binding: ALL 39 frames captured in single fresh rx_log rx_0041_132543.log (SF7 datr=7), zero foreign frames.
- Honest ledger: the first fire discovery attempt aborted pre-RF on a transient local bus connection refusal; no airtime and no guard. The subsequent fresh-window fire and full closure are the evidence above.

Reproduce: `gcc -std=c11 -O2 -Wall -Wextra -Werror -pthread aba_epoch_queue.c -latomic -o aba_epoch_queue && ./aba_epoch_queue legacy && ./aba_epoch_queue fixed && python3 -m pytest -q test_frontier_0041.py`.
