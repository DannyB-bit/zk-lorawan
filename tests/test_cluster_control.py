import copy
import json
import multiprocessing
import os
import random
import stat
import struct
import tempfile
import time
import unittest
from unittest.mock import patch
from pathlib import Path
import sys

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, PublicFormat, NoEncryption

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from cluster_control import (
    ReplayGuard, build_manifest, pack_announcement, unpack_announcement,
    verify_announcement, verify_manifest,
)


def identity():
    key = Ed25519PrivateKey.generate()
    private = key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption()).hex()
    public = key.public_key().public_bytes_raw().hex()
    return private, public


def guard_race(arguments):
    path, payload = arguments
    try:
        ReplayGuard(path).check_and_record(payload)
        return True
    except ValueError:
        return False


class ClusterManifestTests(unittest.TestCase):
    def test_signed_manifest_binds_model_workers_layers_and_session(self):
        coordinator_private, coordinator_public = identity()
        _, worker_public = identity()
        now = int(time.time())
        envelope = build_manifest(
            coordinator_private=coordinator_private,
            coordinator_public=coordinator_public,
            model_sha256="11" * 32,
            workers=[{
                "node_id": worker_public,
                "x25519_pub": "22" * 32,
                "layer_start": 0,
                "layer_end": 12,
                "weight": 1.0,
            }],
            session_id="33" * 16,
            epoch=1,
            issued_at=now,
            expires_at=now + 300,
            nonce="44" * 16,
        )
        payload = verify_manifest(
            envelope,
            now=now + 1,
            trusted_coordinators={coordinator_public},
            expected_model_sha256="11" * 32,
        )
        self.assertEqual(payload["session_id"], "33" * 16)
        self.assertEqual(payload["workers"][0]["layer_end"], 12)

    def sample(self, *, epoch=1, nonce="44" * 16, now=None, weight=1.0):
        coordinator_private, coordinator_public = identity()
        _, worker_public = identity()
        now = int(time.time()) if now is None else now
        envelope = build_manifest(
            coordinator_private=coordinator_private,
            coordinator_public=coordinator_public,
            model_sha256="11" * 32,
            workers=[{
                "node_id": worker_public,
                "x25519_pub": "22" * 32,
                "layer_start": 0,
                "layer_end": 12,
                "weight": weight,
            }],
            session_id="33" * 16,
            epoch=epoch,
            issued_at=now,
            expires_at=now + 300,
            nonce=nonce,
        )
        return envelope, coordinator_public, now

    def test_tampered_model_hash_is_rejected(self):
        envelope, coordinator, now = self.sample()
        attacked = copy.deepcopy(envelope)
        attacked["payload"]["model_sha256"] = "99" * 32
        with self.assertRaisesRegex(ValueError, "signature"):
            verify_manifest(attacked, now=now + 1,
                            trusted_coordinators={coordinator})

    def test_expired_and_untrusted_coordinator_are_rejected(self):
        envelope, coordinator, now = self.sample()
        with self.assertRaisesRegex(ValueError, "not currently valid"):
            verify_manifest(envelope, now=now + 300,
                            trusted_coordinators={coordinator})
        with self.assertRaisesRegex(ValueError, "untrusted coordinator"):
            verify_manifest(envelope, now=now + 1,
                            trusted_coordinators=set())

    def test_layer_gap_is_rejected_even_with_valid_signature(self):
        private, coordinator = identity()
        _, worker = identity()
        _, second_worker = identity()
        now = int(time.time())
        envelope = build_manifest(
            coordinator_private=private,
            coordinator_public=coordinator,
            model_sha256="11" * 32,
            workers=[
                {"node_id": worker, "x25519_pub": "22" * 32,
                 "layer_start": 0, "layer_end": 12, "weight": 1.0},
                {"node_id": second_worker, "x25519_pub": "23" * 32,
                 "layer_start": 13, "layer_end": 20, "weight": 2.0},
            ],
            session_id="33" * 16, epoch=1, issued_at=now,
            expires_at=now + 300, nonce="44" * 16,
        )
        with self.assertRaisesRegex(ValueError, "layer"):
            verify_manifest(envelope, now=now + 1,
                            trusted_coordinators={coordinator})

    def test_replay_and_stale_epoch_survive_restart(self):
        envelope, coordinator, now = self.sample()
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "replay.json"
            guard = ReplayGuard(state)
            verify_manifest(envelope, now=now + 1,
                            trusted_coordinators={coordinator},
                            replay_guard=guard)
            with self.assertRaisesRegex(ValueError, "replay"):
                verify_manifest(envelope, now=now + 2,
                                trusted_coordinators={coordinator},
                                replay_guard=guard)
            restarted = ReplayGuard(state)
            with self.assertRaisesRegex(ValueError, "replay"):
                verify_manifest(envelope, now=now + 3,
                                trusted_coordinators={coordinator},
                                replay_guard=restarted)

    def test_announcement_is_60_bytes_and_binds_exact_manifest(self):
        envelope, _, _ = self.sample()
        announcement = pack_announcement(envelope)
        self.assertEqual(len(announcement), 60)
        decoded = unpack_announcement(announcement)
        self.assertEqual(decoded["session_id"], "33" * 16)
        self.assertEqual(decoded["epoch"], 1)
        verify_announcement(announcement, envelope)
        attacked = bytearray(announcement)
        attacked[-1] ^= 1
        with self.assertRaisesRegex(ValueError, "digest"):
            verify_announcement(bytes(attacked), envelope)

    def test_announcement_binary_roundtrips_and_malformed_fuzz(self):
        rng = random.Random(20261127)
        for _ in range(1000):
            session = rng.randbytes(16)
            epoch = rng.randrange(1, 2**32)
            expiry = rng.randrange(1, 2**32)
            digest = rng.randbytes(32)
            raw = struct.pack(">4s16sII32s", b"ZKC1", session, epoch, expiry, digest)
            decoded = unpack_announcement(raw)
            self.assertEqual(decoded["session_id"], session.hex())
            self.assertEqual(decoded["epoch"], epoch)
            self.assertEqual(decoded["expires_at"], expiry)
            self.assertEqual(decoded["manifest_sha256"], digest.hex())
        for _ in range(1000):
            raw = rng.randbytes(rng.randrange(0, 100))
            with self.assertRaises(ValueError):
                unpack_announcement(raw)
        with self.assertRaisesRegex(ValueError, "version"):
            unpack_announcement(b"BAD!" + rng.randbytes(56))

    def test_replay_guard_rejects_stale_epoch_and_accepts_higher_epoch(self):
        with tempfile.TemporaryDirectory() as directory:
            guard = ReplayGuard(Path(directory) / "replay.json")
            base = {"session_id": "33" * 16, "epoch": 2,
                    "nonce": "44" * 16, "expires_at": 2_000_000_000}
            guard.check_and_record(base)
            with self.assertRaisesRegex(ValueError, "stale"):
                guard.check_and_record({**base, "epoch": 1, "nonce": "55" * 16})
            guard.check_and_record({**base, "epoch": 3, "nonce": "66" * 16})

    def test_replay_state_fsyncs_file_and_parent_directory(self):
        observed = []
        real_fsync = os.fsync

        def recording_fsync(descriptor):
            observed.append(stat.S_ISDIR(os.fstat(descriptor).st_mode))
            return real_fsync(descriptor)

        with tempfile.TemporaryDirectory() as directory:
            with patch("cluster_control.os.fsync", side_effect=recording_fsync):
                ReplayGuard(Path(directory) / "replay.json").check_and_record({
                    "session_id": "33" * 16, "epoch": 1,
                    "nonce": "44" * 16, "expires_at": 2_000_000_000,
                })
        self.assertEqual(observed.count(False), 1)
        self.assertEqual(observed.count(True), 1)
        self.assertGreater(observed.index(True), observed.index(False))

    def test_huge_integer_weight_is_a_validation_error(self):
        envelope, coordinator, now = self.sample(weight=10**1000)
        with self.assertRaisesRegex(ValueError, "weight"):
            verify_manifest(envelope, now=now + 1,
                            trusted_coordinators={coordinator})

    def test_same_epoch_race_has_exactly_one_winner(self):
        payload = {"session_id": "33" * 16, "epoch": 1,
                   "nonce": "44" * 16, "expires_at": 2_000_000_000}
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "replay.json")
            with multiprocessing.get_context("fork").Pool(8) as pool:
                results = pool.map(guard_race, [(path, payload)] * 8)
        self.assertEqual(results.count(True), 1)
        self.assertEqual(results.count(False), 7)

    def test_corrupt_replay_state_fails_closed(self):
        session = "33" * 16
        cases = [
            "{",
            json.dumps({"sessions": {session: {"epoch": 0}}}),
            json.dumps({"sessions": {session: 7}}),
        ]
        for content in cases:
            with self.subTest(content=content), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "replay.json"
                path.write_text(content)
                with self.assertRaises(ValueError):
                    ReplayGuard(path).check_and_record({
                        "session_id": session, "epoch": 1,
                        "nonce": "44" * 16, "expires_at": 2_000_000_000,
                    })

    def test_invalid_manifest_cannot_advance_replay_state(self):
        envelope, coordinator, now = self.sample()
        attacked = copy.deepcopy(envelope)
        attacked["payload"]["model_sha256"] = "99" * 32
        with tempfile.TemporaryDirectory() as directory:
            guard = ReplayGuard(Path(directory) / "replay.json")
            with self.assertRaises(ValueError):
                verify_manifest(attacked, now=now + 1,
                                trusted_coordinators={coordinator}, replay_guard=guard)
            verify_manifest(envelope, now=now + 2,
                            trusted_coordinators={coordinator}, replay_guard=guard)

    def test_announcement_session_epoch_and_expiry_are_independently_bound(self):
        envelope, _, _ = self.sample()
        announcement = pack_announcement(envelope)
        for offset in [4, 20, 24, 59]:
            with self.subTest(offset=offset):
                attacked = bytearray(announcement)
                attacked[offset] ^= 1
                with self.assertRaises(ValueError):
                    verify_announcement(bytes(attacked), envelope)


if __name__ == "__main__":
    unittest.main()
