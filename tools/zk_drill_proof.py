#!/usr/bin/env python3
"""Pack and verify real identity-bound Groth16 drill proof packets."""

from __future__ import annotations

import hashlib
import json
import subprocess
import struct
from collections.abc import Mapping
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[1]
DEFAULT_PROVER_BINARY = REPO / "target" / "release" / "zk_lorawan_prove"
DEFAULT_PRIVATE_KEY_FILE = Path.home() / ".config" / "solana" / "chirp245_alpha_sk.key"
GATEWAY_PUBLIC_KEY = "c51a77e603e376223a3796a7817ead68333754cd677a6a06a5fb54be75bfb118"
DEFAULT_DEPOSIT = 100_000
MAGIC = b"ZKDP"
VERSION = 1
HEADER = struct.Struct(">4sBB")
HEADER_SIZE = HEADER.size
FIELD_SIZES = (
    ("proof_a_compressed", 32),
    ("proof_b_compressed", 64),
    ("proof_c_compressed", 32),
    ("identity_hash", 32),
    ("nullifier_hash", 32),
    ("attestation_hash", 32),
    ("ciphertext_hash", 32),
    ("payload_sha256", 32),
    ("payload_commitment", 32),
)
PROOF_BODY_SIZE = sum(size for _, size in FIELD_SIZES)
PACKET_SIZE = HEADER_SIZE + PROOF_BODY_SIZE


def pack_proof_packet(fields: Mapping[str, bytes]) -> bytes:
    """Serialize one proof with a fixed six-byte magic/version/header prefix."""
    encoded = bytearray(HEADER.pack(MAGIC, VERSION, HEADER_SIZE))
    for name, expected_size in FIELD_SIZES:
        value = fields[name]
        if not isinstance(value, bytes) or len(value) != expected_size:
            raise ValueError(f"{name} must be exactly {expected_size} bytes")
        encoded.extend(value)
    return bytes(encoded)


def unpack_proof_packet(packet: bytes) -> dict[str, bytes]:
    """Strictly decode a packet, rejecting every truncation or trailing byte."""
    if not isinstance(packet, bytes) or len(packet) != PACKET_SIZE:
        raise ValueError(f"proof packet must be exactly {PACKET_SIZE} bytes")
    magic, version, header_size = HEADER.unpack_from(packet)
    if magic != MAGIC or version != VERSION or header_size != HEADER_SIZE:
        raise ValueError("unsupported proof packet header")

    fields: dict[str, bytes] = {}
    offset = HEADER_SIZE
    for name, size in FIELD_SIZES:
        fields[name] = packet[offset : offset + size]
        offset += size
    return fields


def _read_identity(private_key_file: str | Path) -> bytes:
    """Read a Solana JSON byte-array key or a hexadecimal test key."""
    text = Path(private_key_file).read_text(encoding="utf-8").strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        value = None
    if isinstance(value, list):
        if not value or any(not isinstance(item, int) or not 0 <= item <= 255 for item in value):
            raise ValueError("identity key byte array is invalid")
        return bytes(value)
    try:
        key = bytes.fromhex(text)
    except ValueError:
        raise ValueError("identity key must be a JSON byte array or hexadecimal") from None
    if not key:
        raise ValueError("identity key must not be empty")
    return key


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    """Run without echoing command arguments, which include generation witnesses."""
    try:
        return subprocess.run(
            command,
            cwd=REPO,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            check=False,
            timeout=600,
        )
    except (OSError, subprocess.SubprocessError):
        raise RuntimeError("Groth16 prover subprocess failed") from None


def _bundle_from_stdout(stdout: str) -> dict[str, bytes]:
    try:
        public = json.loads(stdout)
        bundle = {name: bytes.fromhex(public[name]) for name, _ in FIELD_SIZES}
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        raise RuntimeError("Groth16 prover returned malformed public output") from None
    # pack_proof_packet enforces every canonical compressed size.
    pack_proof_packet(bundle)
    return bundle


def generate_proof_packet(
    payload_file: str | Path,
    issue_number: int,
    packet_file: str | Path,
    proof_json_file: str | Path | None = None,
    *,
    private_key_file: str | Path = DEFAULT_PRIVATE_KEY_FILE,
    prover_binary: str | Path = DEFAULT_PROVER_BINARY,
    gateway_address: str = GATEWAY_PUBLIC_KEY,
    deposit_value: int = DEFAULT_DEPOSIT,
) -> dict[str, Any]:
    """Generate a real proof bound to the exact compressed transport bytes."""
    if isinstance(issue_number, bool) or not isinstance(issue_number, int) or not 0 <= issue_number < 2**64:
        raise ValueError("issue_number must be an unsigned 64-bit integer")
    gateway_bytes = bytes.fromhex(gateway_address)
    if len(gateway_bytes) != 32:
        raise ValueError("gateway address must be exactly 32 bytes")

    binary = Path(prover_binary)
    firmware_hash = hashlib.sha256(binary.read_bytes()).digest()
    private_key = _read_identity(private_key_file)
    decryption_key = hashlib.sha256(private_key).digest()
    payload = Path(payload_file).read_bytes()
    command = [
        str(binary),
        "generate-bound",
        private_key.hex(),
        decryption_key.hex(),
        str(issue_number),
        firmware_hash.hex(),
        gateway_address,
        str(deposit_value),
        str(Path(payload_file).resolve()),
    ]
    result = _run(command)
    if result.returncode != 0:
        raise RuntimeError("Groth16 proof generation failed")
    bundle = _bundle_from_stdout(result.stdout)
    packet = pack_proof_packet(bundle)

    packet_path = Path(packet_file)
    packet_path.parent.mkdir(parents=True, exist_ok=True)
    packet_path.write_bytes(packet)
    public_output: dict[str, Any] = {
        "issue_number": issue_number,
        "packet_bytes": len(packet),
        "payload_bytes": len(payload),
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "transport_sha256": hashlib.sha256(payload).hexdigest(),
        "firmware_sha256": firmware_hash.hex(),
        "verifying_key_sha256": hashlib.sha256(
            (REPO / "keys" / "verifying_key.bin").read_bytes()
        ).hexdigest(),
        "zk_proof_sha256": hashlib.sha256(packet).hexdigest(),
        "gateway_address": gateway_address,
        "deposit_value": deposit_value,
        "proof": {name: value.hex() for name, value in bundle.items()},
    }
    if proof_json_file is not None:
        proof_path = Path(proof_json_file)
        proof_path.parent.mkdir(parents=True, exist_ok=True)
        proof_path.write_text(json.dumps(public_output, indent=2) + "\n", encoding="utf-8")
    return public_output


def verify_proof_packet(
    packet_file: str | Path,
    payload_file: str | Path,
    *,
    prover_binary: str | Path = DEFAULT_PROVER_BINARY,
    gateway_address: str = GATEWAY_PUBLIC_KEY,
    deposit_value: int = DEFAULT_DEPOSIT,
    firmware_sha256: str | None = None,
) -> bool:
    """Return true only for a canonical packet cryptographically bound to payload_file.

    Cross-node rule (PR42, issue-0059): the verifier MUST use the
    prover-declared firmware_sha256 from the public proof JSON, not the hash
    of the verifier's own binary — each node builds a different binary.
    The payload hash is still always recomputed from payload_file.
    Both nodes must pin the identical circuit verifying key at keys/. The public
    declaration carries its SHA-256; a different or substituted VK is rejected.
    """
    try:
        fields = unpack_proof_packet(Path(packet_file).read_bytes())
        binary = Path(prover_binary)
        firmware_hash = firmware_sha256 or hashlib.sha256(binary.read_bytes()).hexdigest()
        command = [str(binary), "verify-bound"]
        command.extend(fields[name].hex() for name, _ in FIELD_SIZES[:7])
        command.extend([gateway_address, str(deposit_value), firmware_hash])
        command.extend(fields[name].hex() for name, _ in FIELD_SIZES[7:])
        command.append(str(Path(payload_file).resolve()))
        result = _run(command)
    except (OSError, RuntimeError, ValueError):
        return False
    return result.returncode == 0 and result.stdout.strip() == "VALID"
