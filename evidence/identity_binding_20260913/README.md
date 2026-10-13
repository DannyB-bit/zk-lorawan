# Identity-Binding Milestone — Evidence & Verification Guide
**Date:** 2026-10-13 · **Nodes:** RakMiner-A (transmitter, Agent 04) ↔ RakMiner-B (receiver/verifier, Agent 05)
**Mission order:** Dan — *"the chirp could only have come from whoever holds the private key"*

## What was proven

A Groth16 identity proof was transmitted over LoRa (903.9 MHz, SF9/125 kHz, 14 dBm) as
two 128-byte frames and verified by the receiving twin **using only the RF-captured
bytes** — no LAN, no shared files, no trusted channel:

- **WHO:** `identity_hash = MiMC(private_key)` flew in P2 and is bound inside the
  proof's constraints. Only whoever holds that private key could produce a proof
  that verifies against that identity hash.
- **WHAT:** `ciphertext_hash = MiMC(decryption_key + coordinate)` pins the content.
- **Receiver's verdict** (Bravo, from RF bytes alone): **VALID** (exit 0, 7.365 s on
  Cortex-A72), with negative controls: 1-bit tampered identity_hash → INVALID; wrong
  deposit (100001) → INVALID; c-97 known-good control → VALID on the same binary.

## Packet layout (Identity Packet v1)

| Packet | Size | Content |
|---|---|---|
| P1 | 128 B | compressed Groth16 proof: A(32) ‖ B(64) ‖ C(32) |
| P2 | 128 B | identity_hash(32) ‖ nullifier_hash(32) ‖ attestation_hash(32) ‖ ciphertext_hash(32) |

Public parameters (gateway address, deposit, firmware hash, VK sha `7bd5683f…`) are
declared on the fleet bus with the fire — they contain no secrets.

## Over-the-air record

| Frame | Fired (UTC) | Captured (Bravo) | SNR | SHA-256 (declared == captured) |
|---|---|---|---|---|
| P1 | 12:54:18Z | in-window CRC-OK | +10.8 dB | `94ece753…c91716` ✔ |
| P2 | 12:54:35Z | in-window CRC-OK | +11.0 dB | `abb6e631…af2c` ✔ |

Inter-frame delta 16.79 s. Original 12:18Z burst: P2 captured, P1 lost to the
receiver's standby-listener expiry + reset dead-zone (disclosed on the bus, seq-1501);
the re-burst pair is the clean same-window evidence.

## Files in this bundle

- `p1_proof_128b.bin`, `p2_pubinputs_128b.bin` — the exact bytes transmitted
- `identity_proof_flown.json` — full proof + public inputs + keyset hashes (VK sha `7bd5683f…`, canon keyset)
- `a_tx_reburst_log.txt` — transmitter-side TX_DONE evidence
- `a_side_tx_declarations.json` / `b_side_rx_verdicts.json` — both buses' event streams (declare → fire → capture → verdict)
- `manifest.json` — SHA-256 of every file

## How any stranger verifies (no trust in either twin)

1. `sha256sum` every file against `manifest.json`.
2. Split `p1_proof_128b.bin` → A = bytes[0:32], B = bytes[32:96], C = bytes[96:128];
   split `p2_pubinputs_128b.bin` → identity, nullifier, attestation, ciphertext (4×32 B).
3. Build the old-circuit binary at commit `3e8f982` (the proof was generated against
   the canon 9-input keyset, VK sha `7bd5683f…` — **do not use a PR#7-head binary,
   the 11-input circuit will reject the 9-input proof by arity**, see Honest Traps).
4. Run:
   `zk_lorawan_prove verify <A> <B> <C> <identity> <nullifier> <attestation> <ciphertext> 0016c001ff18afa3903900000000000000000000000000000000000000000000 100000 656e636c6176652d6669726d776172652d76657273696f6e2e2d76312e302e32` → expect **VALID**
   (firmware hex: `656e636c6176652d6669726d776172652d76657273696f6e2d76312e302e32`)
5. Tamper one bit of identity_hash → expect INVALID. That's the binding: the proof
   is worthless for any identity other than the key-holder's.

## Honest traps (disclosed)

1. **Proof-era pinning:** B's tree had rebuilt the prover at PR#7 HEAD (11-input
   circuit) while `keys/` holds the 9-input canon VK — every old-circuit proof
   returned INVALID on that binary, including the known-good c-97 control. Root cause
   found by B via the control experiment; fix = pin binary+keyset+circuit-arity per
   proof era (old-circuit binary sha `b6124e7c` at commit `3e8f982`).
2. **First P1 loss:** receiver infrastructure timing (standby expiry + chain-guard
   reset dead-zone), not RF. Disclosed live; re-fire pair is the evidence.
3. **PR#7's new circuit needs its own trusted setup** before payload-commitment proofs
   can be generated/verified; this milestone ran on the existing canon keyset, which
   is the correct conservative choice for a live RF drill.

## What this closes / what remains

- **CLOSED:** "The transmitter was specifically the key-holder" — from RF bytes alone,
  a stranger watching the spectrum can verify the proof binds `identity_hash H` to
  knowledge of the private key, i.e. the chirp could only come from whoever holds it.
- **Remaining (roadmap):** PR#7's single-object form (payload_commitment inside the
  proof, no separate P2) once its trusted setup is done; on-chain settle of the
  identity-bound proof via the cuneiform program.
