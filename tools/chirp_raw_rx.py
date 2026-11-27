#!/usr/bin/env python3
"""chirp_raw_rx.py — decrypt captured 245B chirps (RAW-byte mode) and reassemble a file.

Standalone (no chirp245.py import). Same canonical envelope as chirp245.py / chirp_raw_tx.py:
  frame (245B) = [ver=1][n][nonce(12)][eph_pub(32)][ct(183)||tag(16)]
  key = HKDF-SHA256(X25519(sk, eph_pub), salt=b"zk-lora-chirp245-v1",
                    info=b"chirp245-aead-key", length=32)
  plaintext = AESGCM(key).decrypt(nonce, frame[46:245], None)   # raises InvalidTag on tamper
  plaintext = b'\\x02' + bytes([total, idx]) + chunk  (zero-padded to 183B)

Usage:
  # decrypt one frame:
  python3 chirp_raw_rx.py frame <frame_hex_file> <sk_hex_file>
  # reassemble a whole file from a manifest + frame files:
  python3 chirp_raw_rx.py reassemble <manifest.json> <frames_dir> <sk_hex_file> <out_file>

Prints JSON with ok/verdict. Exit 0 on DECRYPT_OK, 1 on any failure.
"""
import sys, json, hashlib
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey, X25519PublicKey)
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes

CHIRP_LEN = 245


def decrypt_frame(frame: bytes, sk_hex: str) -> bytes:
    if len(frame) != CHIRP_LEN:
        raise ValueError(f"bad frame length {len(frame)}")
    ver, n = frame[0], frame[1]
    if ver != 1:
        raise ValueError(f"unsupported version {ver}")
    nonce = frame[2:14]
    eph_pub = X25519PublicKey.from_public_bytes(frame[14:46])
    ct_tag = frame[46:245]
    priv = X25519PrivateKey.from_private_bytes(bytes.fromhex(sk_hex))
    shared = priv.exchange(eph_pub)
    key = HKDF(algorithm=hashes.SHA256(), length=32,
               salt=b"zk-lora-chirp245-v1", info=b"chirp245-aead-key").derive(shared)
    return AESGCM(key).decrypt(nonce, ct_tag, None)   # raises on tamper


def load_frame(path) -> bytes:
    """Accept a RAW 245-byte frame file or a HEX-TEXT file (490 hex chars).

    Fix for minigame leg-2 bug (a): `frame` mode used to hex-decode only,
    while `reassemble` mode read raw bytes — the two modes disagreed.
    """
    raw = Path(path).read_bytes()
    if len(raw) == 245:
        return raw
    return bytes.fromhex(raw.decode().strip())


def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(2)
    mode = sys.argv[1]
    if mode == "frame":
        frame = load_frame(sys.argv[2])
        sk_hex = Path(sys.argv[3]).read_text().strip()
        try:
            pt = decrypt_frame(frame, sk_hex)
        except Exception as e:
            print(json.dumps({"ok": False, "verdict": "DECRYPT_FAIL",
                              "error": f"{type(e).__name__}",
                              "frame_sha256": hashlib.sha256(frame).hexdigest()}))
            sys.exit(1)
        sha = hashlib.sha256(frame).hexdigest()
        print(json.dumps({"ok": True, "verdict": "DECRYPT_OK", "frame_sha256": sha,
                          "plaintext_hex": pt.hex()}, indent=1))
        sys.exit(0)
    elif mode == "reassemble":
        manifest = json.loads(Path(sys.argv[2]).read_text())
        frames_dir = Path(sys.argv[3])
        sk_hex = Path(sys.argv[4]).read_text().strip()
        out_file = Path(sys.argv[5])
        chunks = {}
        results = []
        for fr in manifest["frames"]:
            idx = fr["idx"]
            frame = load_frame(frames_dir / f"frame_{idx:02d}.bin")
            fsha = hashlib.sha256(frame).hexdigest()
            try:
                pt = decrypt_frame(frame, sk_hex)
            except Exception as e:
                results.append({"idx": idx, "ok": False, "error": type(e).__name__,
                                "frame_sha256": fsha})
                continue
            if pt[0] != 2:
                results.append({"idx": idx, "ok": False, "error": "bad plaintext magic",
                                "frame_sha256": fsha})
                continue
            total, fidx = pt[1], pt[2]
            chunk = pt[3:].rstrip(b"\x00")
            # chunk length must match manifest unless it's the last chunk
            ok_sha = hashlib.sha256(chunk).hexdigest() == fr["chunk_sha256"]
            chunks[fidx] = chunk
            results.append({"idx": idx, "ok": True, "verdict": "DECRYPT_OK",
                            "frame_sha256": fsha, "chunk_sha_ok": ok_sha,
                            "chunk_bytes": len(chunk)})
        if len(chunks) != manifest["total_chunks"]:
            print(json.dumps({"ok": False, "verdict": "REASSEMBLE_INCOMPLETE",
                              "have": len(chunks), "want": manifest["total_chunks"],
                              "results": results}))
            sys.exit(1)
        transport = b"".join(chunks[i] for i in range(manifest["total_chunks"]))
        transport_sha = hashlib.sha256(transport).hexdigest()
        transport_ok = transport_sha == manifest.get("transport_sha256", transport_sha)
        codec = manifest.get("transport_codec", "raw")
        try:
            if codec == "language-u-exact":
                from language_u_exact_codec import decode_payload
                data = decode_payload(transport)
            elif codec == "raw":
                data = transport
            else:
                raise ValueError("unsupported transport codec")
        except Exception as exc:
            print(json.dumps({"ok": False, "verdict": "CODEC_DECODE_FAIL",
                              "error": f"{type(exc).__name__}: {exc}", "transport_sha256": transport_sha,
                              "expected_transport_sha256": manifest.get("transport_sha256"),
                              "transport_bytes": len(transport), "frames": results}, indent=1))
            sys.exit(1)
        fsha = hashlib.sha256(data).hexdigest()
        match = transport_ok and fsha == manifest["file_sha256"]
        out_file.write_bytes(data)
        all_ok = all(r.get("ok") and r.get("chunk_sha_ok", True) for r in results)
        print(json.dumps({"ok": match and all_ok,
                          "verdict": "DECRYPT_OK" if (match and all_ok) else "SHA_MISMATCH",
                          "file_sha256": fsha, "expected": manifest["file_sha256"],
                          "transport_codec": codec, "transport_sha256": transport_sha,
                          "transport_sha_match": transport_ok,
                          "sha_match": match, "out_file": str(out_file),
                          "frames": results}, indent=1))
        sys.exit(0 if (match and all_ok) else 1)
    else:
        print(__doc__); sys.exit(2)


if __name__ == "__main__":
    main()
