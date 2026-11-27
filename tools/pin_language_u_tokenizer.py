#!/usr/bin/env python3
"""Pin the exact tokenizer identity behind a LUCX1 capsule (issue-0059 fix).

The LUCX1 capsule header carries no tokenizer ID, so cross-node exact decode
is only reproducible if both nodes pin the SAME tokenizer snapshot. This
script prints (and optionally writes) the identity record:
  tokenizer class, tokenizer.json SHA256, and the exact token IDs for a
  given payload, and FAILS CLOSED if the local tokenizer.json hash differs
from the pinned value.

Usage:
  python3 tools/pin_language_u_tokenizer.py PAYLOAD [--out identity.json]
  python3 tools/pin_language_u_tokenizer.py PAYLOAD --expect-sha256 HEX

Pinned snapshot for issue-0059:
  local path: ~/fleet-repos/ufo-compression-python (HF-style snapshot dir,
              not a git checkout; contains tokenizer.json + merges.txt)
  class:      GemmaTokenizer (transformers AutoTokenizer, local_files_only)
  tokenizer.json sha256:
              cc8d3a0ce36466ccc1278bf987df5f71db1719b9ca6b4118264f45cb627bfe0f
NOTE: the codec docstring historically said "local Qwen token IDs". That was
wrong: the pinned snapshot loads as GemmaTokenizer. Qwen/Qwen3.5-0.8B and the
Trinity tokenizer variants do NOT reproduce this capsule.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path

PINNED_SHA256 = "cc8d3a0ce36466ccc1278bf987df5f71db1719b9ca6b4118264f45cb627bfe0f"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("payload")
    ap.add_argument("--out")
    ap.add_argument("--expect-sha256", default=PINNED_SHA256)
    ap.add_argument("--tokenizer-dir",
                    default=os.environ.get("LANGUAGE_U_TOKENIZER_DIR",
                                           str(Path.home() / "fleet-repos/ufo-compression-python")))
    args = ap.parse_args()
    tdir = Path(args.tokenizer_dir)
    tj = tdir / "tokenizer.json"
    actual = hashlib.sha256(tj.read_bytes()).hexdigest()
    if actual != args.expect_sha256:
        raise SystemExit(f"TOKENIZER PIN MISMATCH: {actual} != {args.expect_sha256} — refusing to produce IDs")
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(str(tdir), local_files_only=True)
    raw = Path(args.payload).read_bytes()
    ids = tok.encode(raw.decode("utf-8"))
    if tok.decode(ids).encode("utf-8") != raw:
        raise SystemExit("tokenizer is not byte-exact for this payload")
    rec = {
        "tokenizer_dir": str(tdir),
        "tokenizer_class": type(tok).__name__,
        "tokenizer_json_sha256": actual,
        "payload": str(args.payload),
        "payload_sha256": hashlib.sha256(raw).hexdigest(),
        "token_count": len(ids),
        "token_ids": ids,
    }
    text = json.dumps(rec, indent=1)
    if args.out:
        Path(args.out).write_text(text)
    print(text)


if __name__ == "__main__":
    main()
