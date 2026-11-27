"""Real Groth16 drill-packet tests; no prover/verifier mocks."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import time
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO / "tools" / "zk_drill_proof.py"
SPEC = importlib.util.spec_from_file_location("zk_drill_proof", MODULE_PATH)
zk_drill_proof = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(zk_drill_proof)


def test_packet_codec_is_exact_and_fail_closed() -> None:
    fields = {
        "proof_a_compressed": bytes(range(32)),
        "proof_b_compressed": bytes(range(64)),
        "proof_c_compressed": bytes(range(32, 64)),
        "identity_hash": bytes(range(32)),
        "nullifier_hash": bytes(reversed(range(32))),
        "attestation_hash": bytes([7]) * 32,
        "ciphertext_hash": bytes([8]) * 32,
        "payload_sha256": bytes([9]) * 32,
        "payload_commitment": bytes([10]) * 32,
    }

    packet = zk_drill_proof.pack_proof_packet(fields)
    assert len(packet) == 326
    assert packet[:4] == zk_drill_proof.MAGIC
    assert packet[4] == zk_drill_proof.VERSION
    assert zk_drill_proof.unpack_proof_packet(packet) == fields

    with pytest.raises(ValueError):
        zk_drill_proof.unpack_proof_packet(packet[:-1])
    with pytest.raises(ValueError):
        zk_drill_proof.unpack_proof_packet(b"BAD!" + packet[4:])
    with pytest.raises(ValueError):
        zk_drill_proof.unpack_proof_packet(packet[:4] + b"\xff" + packet[5:])


def test_real_bound_proof_packet_round_trip_and_tamper_rejection(tmp_path: Path) -> None:
    payload = bytes(range(245))
    payload_file = tmp_path / "language_u_transport.bin"
    payload_file.write_bytes(payload)

    # Deliberately nonsecret test identity; production defaults read the real key file.
    identity_bytes = bytes(range(64))
    identity_file = tmp_path / "test_identity.key"
    identity_file.write_text(json.dumps(list(identity_bytes)), encoding="utf-8")
    packet_file = tmp_path / "drill.proofpacket"
    proof_file = tmp_path / "drill_proof.json"

    started = time.perf_counter()
    generated = zk_drill_proof.generate_proof_packet(
        payload_file,
        59,
        packet_file,
        proof_file,
        private_key_file=identity_file,
    )
    generation_seconds = time.perf_counter() - started
    assert packet_file.stat().st_size == 326
    assert generated["issue_number"] == 59
    assert generated["payload_sha256"] == hashlib.sha256(payload).hexdigest()
    assert json.loads(proof_file.read_text(encoding="utf-8")) == generated
    assert identity_bytes.hex() not in proof_file.read_text(encoding="utf-8")
    assert hashlib.sha256(identity_bytes).hexdigest() not in proof_file.read_text(encoding="utf-8")

    started = time.perf_counter()
    assert zk_drill_proof.verify_proof_packet(packet_file, payload_file) is True
    verification_seconds = time.perf_counter() - started
    print(
        f"real-proof generation={generation_seconds:.3f}s "
        f"verification={verification_seconds:.3f}s packet={packet_file.stat().st_size}B"
    )

    tampered_packet = bytearray(packet_file.read_bytes())
    tampered_packet[102] ^= 0x01
    tampered_packet_file = tmp_path / "tampered.proofpacket"
    tampered_packet_file.write_bytes(tampered_packet)
    assert zk_drill_proof.verify_proof_packet(tampered_packet_file, payload_file) is False

    tampered_payload_file = tmp_path / "tampered_transport.bin"
    tampered_payload_file.write_bytes(payload + b"x")
    assert zk_drill_proof.verify_proof_packet(packet_file, tampered_payload_file) is False
