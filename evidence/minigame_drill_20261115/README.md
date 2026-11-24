# Minigame Drill 2026-11-15 — A↔B working code over zk-LoRaWAN (COMPLETE both directions)

**Mission (Dan-ordered):** each agent codes game logic to the other over real LoRa; full evidence log; DECRYPT_OK audit both directions. No internet, no A2A protocol in the RF path — the bus is used only for declare/verdict bookkeeping.

## The game
- `game_core.py` (914 B, coded by Researcher A): deterministic number-guessing core, `Game(lo=1, hi=100, seed=1337)`, 7-guess budget.
- `player_ai.py` (2,420 B, coded by Researcher B): binary-search player using ONLY high/low feedback (never peeks at the secret `guess()` leaks). Worst case for 1..100 is exactly 7 guesses — the core's budget.
- **Result:** combined game ran on Alpha's node — B's AI beat A's core in **7 guesses, within budget — win**. Bravo local sweep: 2,000 seeds, 0 failures, worst case 7.

## RF legs (903.9 MHz, SF9, BW125, canonical chirp245 AEAD: X25519 + HKDF-SHA256 + AES-256-GCM, 245 B frames)

### Leg 1 — A→B (`game_core.py`), 6 chirps
- Declared file SHA-256: `94c1838794bdec1942674a9300611425c70b7c4a29102fd30cb7c227c173889b`
- Alpha fired 6×245 B frames (3 reps total across initial+refire), all TX_DONE.
- Bravo captured 6/6 unique frames (18 observations, CRC status 0x10, SNR ~10.8–11.2 dB), reassembled 914 B, **sha_match: true**, verdict `DECRYPT_OK` posted B[4312]/A[1438].
- Evidence: `leg1_capture_inventory.json`, `leg1_frame_decrypt.json`, `leg1_frames/`, `game_core.py` (sha256 verified on commit).

### Leg 2 — B→A (`player_ai.py`), 14 chirps + 4-frame re-fire
- Declared file SHA-256: `c94a2cecbacd811a944559f4f44ffb21bf6fdf275bf960ee314c9f9184581b8f`
- fire01: 14 frames × 2 reps = 28 sends, all TX_DONE (`leg2_tx_fire01.log`); Alpha captured 10/14 unique — receiver-side miss disclosed on-bus (A[1445]/B[4320]).
- fire02: exactly the 4 missed frames (idx 10–13) × 3 reps = 12 sends, all TX_DONE (`leg2_tx_fire02.log`); Alpha captured 14/14, verdict `DECRYPT_OK` (A[1448]/A[1450]).
- Bravo cross-check vs sealed payload: sha_match, chunk_count_match, byte_count_match — all true (B[4328]).
- Evidence: `leg2_frames/`, `leg2_frames_refire_missing4/`, `leg2_frame_sha_inventory.json`, `chirp_frames_tx.c` (B-side multi-frame TX: ONE `lgw_start` for all frames, per-send TX_STATUS polled to TX_FREE), `minigame_b2a_fire.sh` (fail-closed: staged-SHA gate → stop RX chain-guard → kill listener → cd-first fire → recovery → standby re-arm), `staged_sha_gate.py`.

## Final audits (cross-posted, both buses)
- Alpha final: A[1449]/B[4325] — `minigame_conversation_audit_final`, status COMPLETE both directions.
- Bravo final: A[1451]/B[4328] — `minigame_conversation_audit`, status COMPLETE, CROSS-CONFIRMED.
- Dossier: `EVIDENCE_DOSSIER.json` (mirrored at both nodes' `~/fleet/minigame-drill/`).

## Honest disclosures
- Alpha's fire01 capture missed 4 of 14 unique frames; re-fired per drill rules. Disclosed, not hidden.
- Tooling finding: `chirp_raw_rx.py` `frame` mode expects HEX-TEXT while `reassemble` expects RAW bytes — asymmetric interface; worked around by writing both forms from the same captured bytes; flagged to Alpha.
- `bravo_sk.hex` (private key) was deliberately EXCLUDED from this evidence drop. Private keys never ship.

## Verification
`verify_minigame_drill.py` — re-verifies the drill from the artifacts in this directory (frame SHAs, reassembly, decrypt reports, game outcome). Run: `python3 verify_minigame_drill.py` from this directory's parent layout as staged on the node.
