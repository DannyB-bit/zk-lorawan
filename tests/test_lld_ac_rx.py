"""LLD-AC B-side RX tests — P2 semantic legs (Node-B).

Covers tools/lld_ac_rx.py against proof_compression/lld_ac_encoder.py:
1. pack -> unpack structural round-trip (magic, flags, coords, FEC)
2. fail-closed rejects: bad magic, truncated body, bad flags
3. end-to-end: synthetic Groth16 proof -> LLD-AC -> frame -> RX verdict MATCH
4. tamper detection: bit-flipped body must NOT match the declared SHA
"""
from __future__ import annotations

import hashlib
import importlib.util
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from proof_compression.lld_ac_encoder import (
    LLDACEncoder, pack_lora_frame, serialize_groth16_proof,
)
import importlib.util
_spec = importlib.util.spec_from_file_location(
    "lld_ac_rx", Path(__file__).resolve().parents[1] / "tools" / "lld_ac_rx.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
unpack_lora_frame = _mod.unpack_lora_frame
verify_frame = _mod.verify_frame
FrameReject = _mod.FrameReject


def make_frame(with_fec: bool = False):
    enc = LLDACEncoder()
    a_hex = "0x" + os.urandom(32).hex()
    b_hex = "0x" + os.urandom(64).hex()
    c_hex = "0x" + os.urandom(32).hex()
    pub = ["0x" + os.urandom(32).hex(), "0x" + os.urandom(32).hex()]
    serial = serialize_groth16_proof(a_hex, b_hex, c_hex, pub)
    comp = enc.encode(serial)
    coords = [6, 23, 7, 7, 4, 1]
    fec = bytes([0x5A] * 8) if with_fec else None
    frame = pack_lora_frame(comp, coords, fec_parity=fec)
    return frame, serial, coords


class TestUnpack(unittest.TestCase):
    def test_roundtrip_structure(self):
        frame, _, coords = make_frame()
        p = unpack_lora_frame(frame)
        self.assertEqual(p["coords"], coords)
        self.assertIsNone(p["fec"])
        self.assertEqual(p["trailing"], b"")

    def test_roundtrip_with_fec(self):
        frame, _, _ = make_frame(with_fec=True)
        p = unpack_lora_frame(frame)
        self.assertEqual(p["fec"], bytes([0x5A] * 8))

    def test_bad_magic_rejected(self):
        frame, _, _ = make_frame()
        with self.assertRaises(FrameReject):
            unpack_lora_frame(b"\x00" + frame[1:])

    def test_truncated_rejected(self):
        frame, _, _ = make_frame()
        with self.assertRaises(FrameReject):
            unpack_lora_frame(frame[:6])

    def test_reserved_flags_rejected(self):
        frame, _, _ = make_frame()
        bad = bytes([frame[0], frame[1] | 0x04]) + frame[2:]
        with self.assertRaises(FrameReject):
            unpack_lora_frame(bad)


class TestEndToEnd(unittest.TestCase):
    def test_full_verdict_match(self):
        frame, serial, _ = make_frame()
        sha = hashlib.sha256(serial).hexdigest()
        rec = verify_frame(frame, len(serial), sha)
        self.assertEqual(rec["verdict"], "MATCH")
        self.assertEqual(rec["sha256"], sha)
        self.assertEqual(rec["proof_len_decompressed"], len(serial))

    def test_tamper_detected(self):
        frame, serial, _ = make_frame()
        sha = hashlib.sha256(serial).hexdigest()
        tampered = bytearray(frame)
        tampered[10] ^= 0x01  # flip one bit inside the compressed body
        rec = verify_frame(bytes(tampered), len(serial), sha)
        self.assertEqual(rec["verdict"], "MISMATCH")

    def test_wrong_expected_sha(self):
        frame, serial, _ = make_frame()
        rec = verify_frame(frame, len(serial), "00" * 32)
        self.assertEqual(rec["verdict"], "MISMATCH")


if __name__ == "__main__":
    unittest.main()
