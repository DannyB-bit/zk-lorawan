#!/usr/bin/env python3
"""chirp_raw_tx.py — seal an arbitrary file into N 245B LoRa chirps (RAW-byte mode).

Reuses the EXACT canonical AEAD envelope from tools/chirp245.py (PR #12):
  frame (245B) = [ver=1][n][nonce(12)][eph_x25519_pub(32)][AES-256-GCM ct(183)||tag(16)]
  key = HKDF-SHA256(X25519(eph_sk, recipient_pub), salt=b"zk-lora-chirp245-v1",
                    info=b"chirp245-aead-key", length=32)

RAW mode difference: the 183B plaintext is NOT a coord bitstream. It is:
  plaintext = b'\\x02' + bytes([total_chunks, idx]) + chunk   (chunk <= 180B)
so a receiver can reassemble the original file byte-for-byte (bit-exact).

Usage:
  python3 chirp_raw_tx.py <file> <recipient_pub_hex> <out_dir>
Writes out_dir/frame_00.bin ... frame_NN.bin plus manifest.json:
  {file_sha256, total_chunks, frames:[{idx, frame_sha256, chunk_sha256, bytes}]}
"""
import sys, os, json, hashlib
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey, X25519PublicKey)
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

CHIRP_LEN = 245
HDR_LEN = 46          # ver(1)+n(1)+nonce(12)+ephpub(32)
TAG_LEN = 16
CT_LEN = CHIRP_LEN - HDR_LEN - TAG_LEN   # 183
PLAINTEXT_LEN = CT_LEN
CHUNK_MAX = PLAINTEXT_LEN - 3            # 180B payload per chirp (3B mini-header)


def seal_frame(plaintext: bytes, recipient_pub_hex: str, n_field: int, rng=os.urandom) -> bytes:
    assert len(plaintext) == PLAINTEXT_LEN
    eph = X25519PrivateKey.generate()
    recipient_pub = X25519PublicKey.from_public_bytes(bytes.fromhex(recipient_pub_hex))
    shared = eph.exchange(recipient_pub)
    key = HKDF(algorithm=hashes.SHA256(), length=32,
               salt=b"zk-lora-chirp245-v1", info=b"chirp245-aead-key").derive(shared)
    nonce = rng(12)
    ct = AESGCM(key).encrypt(nonce, plaintext, None)   # ct || 16B tag
    assert len(ct) == CT_LEN + TAG_LEN
    eph_pub = eph.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    hdr = bytes([1, n_field]) + nonce + eph_pub
    frame = hdr + ct
    assert len(frame) == CHIRP_LEN
    return frame


def main():
    if len(sys.argv) != 4:
        print(__doc__); sys.exit(2)
    src = Path(sys.argv[1]).read_bytes()
    recipient_pub_hex = sys.argv[2].strip()
    out_dir = Path(sys.argv[3]); out_dir.mkdir(parents=True, exist_ok=True)

    chunks = [src[i:i + CHUNK_MAX] for i in range(0, len(src), CHUNK_MAX)] or [b""]
    total = len(chunks)
    assert total <= 255
    manifest = {"file": str(sys.argv[1]), "file_bytes": len(src),
                "file_sha256": hashlib.sha256(src).hexdigest(),
                "total_chunks": total, "chunk_max": CHUNK_MAX, "frames": []}
    for idx, ch in enumerate(chunks):
        plaintext = b"\x02" + bytes([total, idx]) + ch
        plaintext = plaintext.ljust(PLAINTEXT_LEN, b"\x00")
        frame = seal_frame(plaintext, recipient_pub_hex, n_field=total)
        fsha = hashlib.sha256(frame).hexdigest()
        (out_dir / f"frame_{idx:02d}.bin").write_bytes(frame)
        manifest["frames"].append({"idx": idx, "frame_sha256": fsha,
                                    "chunk_sha256": hashlib.sha256(ch).hexdigest(),
                                    "chunk_bytes": len(ch)})
        print(f"frame_{idx:02d}.bin 245B sha256={fsha[:16]}... chunk={len(ch)}B")
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print(json.dumps({"ok": True, "file_sha256": manifest["file_sha256"],
                      "total_chunks": total, "out_dir": str(out_dir)}))


if __name__ == "__main__":
    main()
