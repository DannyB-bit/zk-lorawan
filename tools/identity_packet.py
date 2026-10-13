#!/usr/bin/env python3
"""ZK-LoRaWAN Identity Packet v1 — RF-carried public inputs.

Converts a Groth16 proof bundle JSON (zk_lorawan_prove generate output) into
TWO LoRa packets that together let ANY receiver verify transmitter identity
and content binding using ONLY over-the-air bytes:

  Packet P1 (128 B): compressed proof  A||B||C  (G1||G2||G1 = 32+64+32)
  Packet P2 (128 B): public input hashes:
        identity_hash    (32B)  MiMC(private_key)          <- WHO
        nullifier_hash   (32B)  MiMC(private_key + 9999)  <- replay guard
        attestation_hash (32B)  MiMC(private_key + firmware) <- WHICH FIRMWARE
        ciphertext_hash  (32B)  MiMC(decryption_key + coordinate) <- WHAT

Plus, carried on the declaration (public, not secret): gateway parts 1/2,
deposit commitment, firmware hash — the receiver needs those to run
`zk_lorawan_prove verify`. They are NOT secret-dependent (they are public
inputs), so publishing them costs zero privacy.

Verification from RF alone:
  1. Receive P1 + P2 over the air (CRC OK, same burst window).
  2. Verify sha256(P1) == declared proof sha (chain of custody).
  3. Run zk_lorawan_prove verify <P1 split> <P2 split> <gateway hex>
     <deposit> <firmware hex>  ->  VALID
  4. The identity_hash in P2 pins the transmitter: a proof with a
     different private key CANNOT produce this identity_hash (MiMC
     preimage binding inside the circuit's constraints).
  5. The ciphertext_hash pins the content: changing the coordinate or
     decryption key changes the hash; only the key holder can re-prove.

No toys, no mocks: every byte below comes from the real arkworks prover.
"""
import json
import hashlib
import sys


def bundle_to_packets(bundle_json: dict) -> dict:
    """Split a real prover bundle into P1 (proof) + P2 (public hashes)."""
    p1 = bytes.fromhex(bundle_json["proof_a_compressed"]) \
       + bytes.fromhex(bundle_json["proof_b_compressed"]) \
       + bytes.fromhex(bundle_json["proof_c_compressed"])
    p2 = bytes.fromhex(bundle_json["identity_hash"]) \
       + bytes.fromhex(bundle_json["nullifier_hash"]) \
       + bytes.fromhex(bundle_json["attestation_hash"]) \
       + bytes.fromhex(bundle_json["ciphertext_hash"])
    assert len(p1) == 128, f"P1 must be 128B, got {len(p1)}"
    assert len(p2) == 128, f"P2 must be 128B, got {len(p2)}"
    return {
        "p1_proof_hex": p1.hex(),
        "p2_pubinputs_hex": p2.hex(),
        "p1_sha256": hashlib.sha256(p1).hexdigest(),
        "p2_sha256": hashlib.sha256(p2).hexdigest(),
        "identity_hash_hex": bundle_json["identity_hash"],
        "nullifier_hash_hex": bundle_json["nullifier_hash"],
        "attestation_hash_hex": bundle_json["attestation_hash"],
        "ciphertext_hash_hex": bundle_json["ciphertext_hash"],
        "verify_cmd": (
            "zk_lorawan_prove verify "
            f"{bundle_json['proof_a_compressed']} "
            f"{bundle_json['proof_b_compressed']} "
            f"{bundle_json['proof_c_compressed']} "
            f"{bundle_json['identity_hash']} "
            f"{bundle_json['nullifier_hash']} "
            f"{bundle_json['attestation_hash']} "
            f"{bundle_json['ciphertext_hash']} "
            "<gateway_address_hex> <deposit_value> <firmware_hash_hex>"
        ),
    }


def packets_from_rf(p1_bytes: bytes, p2_bytes: bytes) -> dict:
    """Reassemble prover-CLI arguments from raw RF-captured bytes."""
    assert len(p1_bytes) == 128 and len(p2_bytes) == 128
    return {
        "proof_a": p1_bytes[0:32].hex(),
        "proof_b": p1_bytes[32:96].hex(),
        "proof_c": p1_bytes[96:128].hex(),
        "identity_hash": p2_bytes[0:32].hex(),
        "nullifier_hash": p2_bytes[32:64].hex(),
        "attestation_hash": p2_bytes[64:96].hex(),
        "ciphertext_hash": p2_bytes[96:128].hex(),
    }


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in ("split", "reassemble"):
        print("usage: identity_packet.py split <bundle.json> | reassemble <p1.hex> <p2.hex>")
        sys.exit(2)
    if sys.argv[1] == "split":
        out = bundle_to_packets(json.load(open(sys.argv[2])))
        print(json.dumps(out, indent=1))
    else:
        out = packets_from_rf(bytes.fromhex(sys.argv[2]), bytes.fromhex(sys.argv[3]))
        print(json.dumps(out, indent=1))
