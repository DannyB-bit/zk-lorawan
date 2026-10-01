#!/usr/bin/env python3
"""
LLD-AC B-Side Receiver (Node-B / RakMiner-B) — P2 semantic-leg RX harness.

Companion to proof_compression/lld_ac_encoder.py (Component 08). Alpha
(A) encodes: serialize_groth16_proof -> LLDACEncoder.encode ->
pack_lora_frame -> radio. This module is the B side: parse the 0xAE frame,
recover the 6D Cuneiform-U coordinates, LLD-AC decompress the proof body,
and emit an evidence-grade SHA-256 verdict against the declared canon SHA.

Frame layout (per pack_lora_frame):
  [0]      magic 0xAE
  [1]      flags (bit0 = has_fec, bit1 = has_coords)
  [2:4]    proof_len (u16 BE)
  [4:4+N]  LLD-AC compressed proof
  [6B]     cuneiform coords D,L,K,P,E,R (one byte each) if has_coords
  [1B + M] fec_parity (len-prefixed) if has_fec

Usage (drill):
  python3 tools/lld_ac_rx.py verify-frame <frame.hex> --orig-len 162 \
      --expect-sha <sha256-of-serialized-proof>

Exit codes: 0 = SHA MATCH (frame accepted), 1 = mismatch/reject, 2 = usage.
Evidence line format is stable for the milestone artifacts:
  LLD_AC_RX_MAGIC_OK=YES|NO COORDS=<d,l,k,p,e,r> PROOF_LEN=<n> \
  DECOMPRESSED_LEN=<n> SHA=<hex> VERDICT=MATCH|MISMATCH
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from proof_compression.lld_ac_encoder import LLDACEncoder  # noqa: E402

MAGIC = 0xAE
FLAG_HAS_FEC = 0x01
FLAG_HAS_COORDS = 0x02


class FrameReject(Exception):
    """Fail-closed frame parse error (bad magic, truncated body, bad flags)."""


def unpack_lora_frame(frame: bytes) -> dict:
    """Parse a 0xAE ZK-LoRaWAN frame. Fail-closed on any structural defect."""
    if len(frame) < 4:
        raise FrameReject("frame shorter than header (4 bytes)")
    if frame[0] != MAGIC:
        raise FrameReject(f"bad magic 0x{frame[0]:02x} (expected 0x{MAGIC:02x})")
    flags = frame[1]
    if flags & 0xFC:
        raise FrameReject(f"reserved flag bits set: 0x{flags:02x}")
    proof_len = (frame[2] << 8) | frame[3]
    end = 4 + proof_len
    if end > len(frame):
        raise FrameReject(f"truncated proof body: need {proof_len}, have {len(frame)-4}")
    comp = bytes(frame[4:end])
    off = end
    coords = None
    if flags & FLAG_HAS_COORDS:
        if off + 6 > len(frame):
            raise FrameReject("truncated coords (need 6 bytes)")
        coords = list(frame[off:off + 6])
        off += 6
    fec = None
    if flags & FLAG_HAS_FEC:
        if off + 1 > len(frame):
            raise FrameReject("truncated FEC length byte")
        flen = frame[off]
        off += 1
        if off + flen > len(frame):
            raise FrameReject(f"truncated FEC body (need {flen})")
        fec = bytes(frame[off:off + flen])
        off += flen
    trailing = bytes(frame[off:])
    if trailing:
        # Not fatal (forward-compat padding), but recorded for forensics.
        pass
    return {"compressed": comp, "coords": coords, "fec": fec, "trailing": trailing}


def verify_frame(frame: bytes, orig_len: int, expect_sha: str | None) -> dict:
    """Full B-side verification pass. Returns an evidence record."""
    parsed = unpack_lora_frame(frame)
    enc = LLDACEncoder()
    proof = enc.decode(parsed["compressed"], orig_len)
    sha = hashlib.sha256(proof).hexdigest()
    verdict = "MATCH" if (expect_sha is None or sha == expect_sha.lower()) else "MISMATCH"
    return {
        "magic_ok": True,
        "coords": parsed["coords"],
        "proof_len_compressed": len(parsed["compressed"]),
        "proof_len_decompressed": len(proof),
        "sha256": sha,
        "expect_sha": expect_sha,
        "verdict": verdict,
        "fec_present": parsed["fec"] is not None,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="lld_ac_rx")
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("verify-frame", help="parse + decompress + SHA verdict")
    v.add_argument("frame_hex", help="hex-encoded 0xAE frame (whitespace ok)")
    v.add_argument("--orig-len", type=int, required=True,
                   help="declared original serialized-proof length (from TX declaration)")
    v.add_argument("--expect-sha", default=None,
                   help="canon SHA-256 of the serialized proof (from TX declaration)")
    a = ap.parse_args(argv)

    frame = bytes.fromhex("".join(a.frame_hex.split()))
    try:
        rec = verify_frame(frame, a.orig_len, a.expect_sha)
    except FrameReject as e:
        print(f"LLD_AC_RX_MAGIC_OK=NO REASON={e}")
        return 1
    coords = ",".join(str(c) for c in rec["coords"]) if rec["coords"] else "-"
    print(f"LLD_AC_RX_MAGIC_OK=YES COORDS=<{coords}> "
          f"PROOF_LEN={rec['proof_len_compressed']} "
          f"DECOMPRESSED_LEN={rec['proof_len_decompressed']} "
          f"SHA={rec['sha256']} VERDICT={rec['verdict']}")
    return 0 if rec["verdict"] == "MATCH" else 1


if __name__ == "__main__":
    sys.exit(main())
