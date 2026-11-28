#!/usr/bin/env python3
"""Authenticated ZK-LoRa cluster control messages.

Real cryptography only: Ed25519 signs canonical JSON with domain separation.
The full manifest is fast-plane data; LoRa carries only compact commitments.
This module does not implement or claim a tensor-RPC tunnel.
"""
from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import math
import os
import struct
import tempfile
from pathlib import Path
from typing import Any, Iterable

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

MANIFEST_DOMAIN = b"ZK-LORAWAN-CLUSTER-MANIFEST-V1\x00"


def canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _sign(payload: dict[str, Any], private_hex: str, public_hex: str,
          domain: bytes) -> dict[str, Any]:
    private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(private_hex))
    derived_public = private.public_key().public_bytes_raw().hex()
    if derived_public != public_hex:
        raise ValueError("coordinator public key does not match private key")
    signature = private.sign(domain + canonical_json(payload))
    return {
        "payload": payload,
        "signer": public_hex,
        "signature": signature.hex(),
    }


def _verify_envelope(envelope: dict[str, Any], domain: bytes) -> dict[str, Any]:
    if set(envelope) != {"payload", "signer", "signature"}:
        raise ValueError("invalid signed envelope fields")
    payload = envelope["payload"]
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    public = Ed25519PublicKey.from_public_bytes(bytes.fromhex(envelope["signer"]))
    try:
        public.verify(
            bytes.fromhex(envelope["signature"]),
            domain + canonical_json(payload),
        )
    except InvalidSignature as exc:
        raise ValueError("invalid Ed25519 signature") from exc
    return payload


def build_manifest(*, coordinator_private: str, coordinator_public: str,
                   model_sha256: str, workers: list[dict[str, Any]],
                   session_id: str, epoch: int, issued_at: int,
                   expires_at: int, nonce: str) -> dict[str, Any]:
    payload = {
        "version": "zklc1",
        "model_sha256": model_sha256,
        "workers": workers,
        "session_id": session_id,
        "epoch": epoch,
        "issued_at": issued_at,
        "expires_at": expires_at,
        "nonce": nonce,
    }
    return _sign(payload, coordinator_private, coordinator_public, MANIFEST_DOMAIN)


def _hex(value: Any, length: int, field: str) -> str:
    if not isinstance(value, str) or len(value) != length or value.lower() != value:
        raise ValueError(f"invalid {field}")
    try:
        bytes.fromhex(value)
    except ValueError as exc:
        raise ValueError(f"invalid {field}") from exc
    return value


def _integer(value: Any, field: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"invalid {field}")
    return value


class ReplayGuard:
    """Persistent one-manifest-per-epoch fence with atomic cross-process writes."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")

    def check_and_record(self, payload: dict[str, Any]) -> None:
        session = payload["session_id"]
        epoch = payload["epoch"]
        nonce = payload["nonce"]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            state = {"sessions": {}}
            if self.path.exists():
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(loaded, dict) or not isinstance(loaded.get("sessions"), dict):
                    raise ValueError("corrupt replay state")
                state = loaded
            previous = state["sessions"].get(session)
            if previous is not None:
                if not isinstance(previous, dict) or set(previous) != {
                    "epoch", "nonce", "expires_at"
                }:
                    raise ValueError("corrupt replay record")
                old_epoch = _integer(previous.get("epoch"), "stored epoch", 1)
                _hex(previous["nonce"], 32, "stored nonce")
                _integer(previous["expires_at"], "stored expiry", 1)
                if epoch <= old_epoch:
                    raise ValueError("replay or stale epoch rejected")
            state["sessions"][session] = {
                "epoch": epoch, "nonce": nonce,
                "expires_at": payload["expires_at"],
            }
            descriptor, temporary = tempfile.mkstemp(
                prefix=self.path.name + ".", dir=self.path.parent)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                    json.dump(state, output, sort_keys=True, separators=(",", ":"))
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary, self.path)
                directory_fd = os.open(
                    self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)


def verify_manifest(envelope: dict[str, Any], *, now: int,
                    trusted_coordinators: Iterable[str],
                    expected_model_sha256: str | None = None,
                    replay_guard: ReplayGuard | None = None) -> dict[str, Any]:
    payload = _verify_envelope(envelope, MANIFEST_DOMAIN)
    if envelope["signer"] not in set(trusted_coordinators):
        raise ValueError("untrusted coordinator")
    expected = {"version", "model_sha256", "workers", "session_id", "epoch",
                "issued_at", "expires_at", "nonce"}
    if set(payload) != expected or payload.get("version") != "zklc1":
        raise ValueError("unsupported manifest fields or version")
    _hex(payload["model_sha256"], 64, "model hash")
    _hex(payload["session_id"], 32, "session id")
    _hex(payload["nonce"], 32, "nonce")
    if expected_model_sha256 is not None and payload["model_sha256"] != expected_model_sha256:
        raise ValueError("model hash mismatch")
    epoch = _integer(payload["epoch"], "epoch", 1)
    issued_at = _integer(payload["issued_at"], "issued_at")
    expires_at = _integer(payload["expires_at"], "expires_at", 1)
    if expires_at <= issued_at or not issued_at <= now < expires_at:
        raise ValueError("manifest is not currently valid")
    workers = payload["workers"]
    if not isinstance(workers, list) or not workers:
        raise ValueError("workers must be a non-empty list")
    next_layer = 0
    identities = set()
    for worker in workers:
        if not isinstance(worker, dict) or set(worker) != {
            "node_id", "x25519_pub", "layer_start", "layer_end", "weight"
        }:
            raise ValueError("invalid worker fields")
        node = _hex(worker["node_id"], 64, "worker identity")
        _hex(worker["x25519_pub"], 64, "worker X25519 key")
        if node in identities:
            raise ValueError("duplicate worker identity")
        identities.add(node)
        start = _integer(worker["layer_start"], "layer start")
        end = _integer(worker["layer_end"], "layer end", 1)
        if start != next_layer or end <= start:
            raise ValueError("worker layer ranges must be contiguous and non-empty")
        next_layer = end
        weight = worker["weight"]
        if isinstance(weight, bool) or not isinstance(weight, (int, float)) \
                or weight <= 0 or weight > 1_000_000_000_000:
            raise ValueError("invalid worker weight")
        if isinstance(weight, float) and not math.isfinite(weight):
            raise ValueError("invalid worker weight")
    if replay_guard is not None:
        replay_guard.check_and_record(payload)
    return payload


ANNOUNCEMENT_MAGIC = b"ZKC1"
ANNOUNCEMENT_BYTES = 60


def manifest_digest(envelope: dict[str, Any]) -> bytes:
    """Commit to the complete signed envelope, including its signature."""
    return hashlib.sha256(MANIFEST_DOMAIN + canonical_json(envelope)).digest()


def pack_announcement(envelope: dict[str, Any]) -> bytes:
    payload = envelope["payload"]
    session = bytes.fromhex(_hex(payload["session_id"], 32, "session id"))
    epoch = _integer(payload["epoch"], "epoch", 1)
    expiry = _integer(payload["expires_at"], "expires_at", 1)
    if epoch > 0xFFFFFFFF or expiry > 0xFFFFFFFF:
        raise ValueError("announcement integer overflow")
    return struct.pack(
        ">4s16sII32s", ANNOUNCEMENT_MAGIC, session, epoch, expiry,
        manifest_digest(envelope),
    )


def unpack_announcement(data: bytes) -> dict[str, Any]:
    if len(data) != ANNOUNCEMENT_BYTES:
        raise ValueError("announcement must be exactly 60 bytes")
    magic, session, epoch, expiry, digest = struct.unpack(">4s16sII32s", data)
    if magic != ANNOUNCEMENT_MAGIC:
        raise ValueError("unknown announcement version")
    return {
        "session_id": session.hex(), "epoch": epoch, "expires_at": expiry,
        "manifest_sha256": digest.hex(),
    }


def verify_announcement(data: bytes, envelope: dict[str, Any]) -> dict[str, Any]:
    decoded = unpack_announcement(data)
    if not hmac.compare_digest(data, pack_announcement(envelope)):
        raise ValueError("announcement digest or session fields do not match manifest")
    return decoded
