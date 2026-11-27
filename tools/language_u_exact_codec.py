#!/usr/bin/env python3
"""Language-U Exact v1: reversible token-radical adaptive range coding.

Real implementation derived from Language-U Inventions 08/10/32. This is the
exact code/text lane, NOT the lossy 6D semantic-coordinate projection.
Every token ID is preserved as three 6-bit radicals; decoded UTF-8 must match
the source SHA-256 or decoding fails closed.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import struct
from pathlib import Path

MAGIC = b"LUCX1"
VERSION = 1
HEADER = struct.Struct(">5sBII32s")  # magic, version, tokens, raw bytes, raw SHA-256
ALPHABET = 256  # reference model width; exact radicals themselves remain 6-bit values
TOP = 1 << 32
BOT = 1 << 24
_TOKENIZER = None


def _tokenizer():
    global _TOKENIZER
    if _TOKENIZER is None:
        from transformers import AutoTokenizer
        candidates = []
        if os.environ.get("LANGUAGE_U_TOKENIZER_DIR"):
            candidates.append(Path(os.environ["LANGUAGE_U_TOKENIZER_DIR"]))
        candidates += [
            Path.home() / "fleet-repos/ufo-compression-python",
            Path("/home/researcher-alpha/fleet-repos/ufo-compression-python"),
            Path("/home/researcher-bravo/fleet-repos/ufo-compression-python"),
        ]
        errors = []
        for candidate in candidates:
            if (candidate / "tokenizer.json").is_file():
                try:
                    _TOKENIZER = AutoTokenizer.from_pretrained(str(candidate), local_files_only=True)
                    break
                except Exception as exc:
                    errors.append(f"{candidate}: {type(exc).__name__}")
        if _TOKENIZER is None:
            raise RuntimeError("local Qwen tokenizer unavailable: " + "; ".join(errors))
    return _TOKENIZER


class PythonRadicalPredictor:
    """Exact Language-U three-context adaptive predictor (Invention 32)."""
    def __init__(self, alpha=1, weight=128):
        self.alpha, self.weight = alpha, weight
        self.trans_rc, self.trans_rf, self.trans_ra = {}, {}, {}
        self.prev_rc = self.prev_rf = self.prev_ra = 0

    def observe(self, rc, rf, ra):
        key_rc = self.prev_rc
        self.trans_rc.setdefault(key_rc, {})[rc] = self.trans_rc.setdefault(key_rc, {}).get(rc, 0) + self.weight
        key_rf = (rc << 8) | self.prev_rf
        self.trans_rf.setdefault(key_rf, {})[rf] = self.trans_rf.setdefault(key_rf, {}).get(rf, 0) + self.weight
        key_ra = (rc << 16) | (rf << 8) | self.prev_ra
        self.trans_ra.setdefault(key_ra, {})[ra] = self.trans_ra.setdefault(key_ra, {}).get(ra, 0) + self.weight
        self.prev_rc, self.prev_rf, self.prev_ra = rc, rf, ra

    @staticmethod
    def _cumulative(freqs):
        result = [0] * 257
        for i in range(256):
            result[i + 1] = result[i] + freqs[i]
        return result

    def cumulative(self, step, symbols):
        freqs = [self.alpha] * 256
        if step == 0:
            counts = self.trans_rc.get(self.prev_rc, {})
        elif step == 1:
            counts = self.trans_rf.get((symbols[0] << 8) | self.prev_rf, {})
        else:
            counts = self.trans_ra.get((symbols[0] << 16) | (symbols[1] << 8) | self.prev_ra, {})
        for sym, count in counts.items():
            freqs[sym] += count
        return self._cumulative(freqs)


class BitWriter:
    def __init__(self):
        self.buffer, self.current_byte, self.bit_count = [], 0, 0

    def write_bit(self, bit):
        self.current_byte = (self.current_byte << 1) | (bit & 1)
        self.bit_count += 1
        if self.bit_count % 8 == 0:
            self.buffer.append(self.current_byte)
            self.current_byte = 0

    def write_bit_helper(self, underflow_bits, bit):
        self.write_bit(bit)
        for _ in range(underflow_bits[0]):
            self.write_bit(1 - bit)
        underflow_bits[0] = 0

    def flush(self):
        if self.bit_count % 8:
            padding = 8 - self.bit_count % 8
            self.current_byte <<= padding
            self.buffer.append(self.current_byte)
            self.current_byte = 0
            self.bit_count += padding
        return bytes(self.buffer)


class BitReader:
    def __init__(self, data):
        self.data, self.byte_index, self.bit_index = data, 0, 0

    def read_bit(self):
        if self.byte_index >= len(self.data):
            return 0
        bit = (self.data[self.byte_index] >> (7 - self.bit_index)) & 1
        self.bit_index += 1
        if self.bit_index == 8:
            self.bit_index, self.byte_index = 0, self.byte_index + 1
        return bit


def range_encode_radicals(radicals) -> bytes:
    pred, writer = PythonRadicalPredictor(), BitWriter()
    low, high, underflow = 0, 0xFFFFFFFF, [0]
    for rc, rf, ra in radicals:
        symbols = [rc, rf, ra]
        if any(not isinstance(sym, int) or not 0 <= sym <= 63 for sym in symbols):
            raise ValueError("radical outside reversible 6-bit alphabet")
        for step in range(3):
            cumulative = pred.cumulative(step, symbols)
            sym = symbols[step]
            total, cum_low, cum_high = cumulative[256], cumulative[sym], cumulative[sym + 1]
            width = high - low + 1
            high = low + (width * cum_high) // total - 1
            low = low + (width * cum_low) // total
            while True:
                if high < 0x80000000:
                    writer.write_bit_helper(underflow, 0)
                    low = (low << 1) & 0xFFFFFFFF
                    high = ((high << 1) | 1) & 0xFFFFFFFF
                elif low >= 0x80000000:
                    writer.write_bit_helper(underflow, 1)
                    low = ((low - 0x80000000) << 1) & 0xFFFFFFFF
                    high = (((high - 0x80000000) << 1) | 1) & 0xFFFFFFFF
                elif low >= 0x40000000 and high < 0xC0000000:
                    underflow[0] += 1
                    low = ((low - 0x40000000) << 1) & 0xFFFFFFFF
                    high = (((high - 0x40000000) << 1) | 1) & 0xFFFFFFFF
                else:
                    break
        pred.observe(rc, rf, ra)
    underflow[0] += 1
    writer.write_bit_helper(underflow, 0 if low < 0x40000000 else 1)
    return writer.flush()


def range_decode_radicals(data: bytes, count: int):
    if not data:
        raise ValueError("empty range-coded body")
    pred, reader = PythonRadicalPredictor(), BitReader(data)
    value = 0
    for _ in range(32):
        value = (value << 1) | reader.read_bit()
    low, high, decoded = 0, 0xFFFFFFFF, []
    for _ in range(count):
        symbols = [0, 0, 0]
        for step in range(3):
            cumulative = pred.cumulative(step, symbols)
            total, width = cumulative[256], high - low + 1
            scaled = (((value - low) + 1) * total - 1) // width
            sym, left, right = 0, 0, 255
            while left <= right:
                mid = (left + right) // 2
                if cumulative[mid] <= scaled < cumulative[mid + 1]:
                    sym = mid
                    break
                if scaled >= cumulative[mid + 1]:
                    left = mid + 1
                else:
                    right = mid - 1
            else:
                raise ValueError("range stream has no valid symbol")
            symbols[step] = sym
            high = low + (width * cumulative[sym + 1]) // total - 1
            low = low + (width * cumulative[sym]) // total
            while True:
                if high < 0x80000000:
                    low = (low << 1) & 0xFFFFFFFF
                    high = ((high << 1) | 1) & 0xFFFFFFFF
                    value = ((value << 1) | reader.read_bit()) & 0xFFFFFFFF
                elif low >= 0x80000000:
                    low = ((low - 0x80000000) << 1) & 0xFFFFFFFF
                    high = (((high - 0x80000000) << 1) | 1) & 0xFFFFFFFF
                    value = (((value - 0x80000000) << 1) | reader.read_bit()) & 0xFFFFFFFF
                elif low >= 0x40000000 and high < 0xC0000000:
                    low = ((low - 0x40000000) << 1) & 0xFFFFFFFF
                    high = (((high - 0x40000000) << 1) | 1) & 0xFFFFFFFF
                    value = (((value - 0x40000000) << 1) | reader.read_bit()) & 0xFFFFFFFF
                else:
                    break
        if any(sym > 63 for sym in symbols):
            raise ValueError("decoded radical exceeds reversible 6-bit alphabet")
        decoded.append(tuple(symbols))
        pred.observe(*symbols)
    # Strict physical-stream integrity: canonical bytes, no trailing suffix.
    if range_encode_radicals(decoded) != data:
        raise ValueError("non-canonical, truncated, or trailing range-coded bytes")
    return decoded


def encode_payload(raw: bytes) -> bytes:
    if not isinstance(raw, bytes):
        raise TypeError("raw payload must be bytes")
    text = raw.decode("utf-8")
    ids = _tokenizer().encode(text)
    if any(not 0 <= token < (1 << 18) for token in ids):
        raise ValueError("token ID exceeds reversible 18-bit radical representation")
    if _tokenizer().decode(ids).encode("utf-8") != raw:
        raise ValueError("tokenizer is not byte-exact for this payload")
    radicals = [((token >> 12) & 63, (token >> 6) & 63, token & 63) for token in ids]
    body = range_encode_radicals(radicals)
    return HEADER.pack(MAGIC, VERSION, len(ids), len(raw), hashlib.sha256(raw).digest()) + body


def decode_payload(capsule: bytes) -> bytes:
    if not isinstance(capsule, bytes) or len(capsule) < HEADER.size:
        raise ValueError("truncated Language-U Exact capsule")
    magic, version, count, raw_len, expected_sha = HEADER.unpack_from(capsule)
    if magic != MAGIC or version != VERSION:
        raise ValueError("unsupported Language-U Exact capsule")
    if count > 10_000_000 or raw_len > 100_000_000:
        raise ValueError("unreasonable capsule dimensions")
    radicals = range_decode_radicals(capsule[HEADER.size:], count)
    ids = [(a << 12) | (b << 6) | c for a, b, c in radicals]
    raw = _tokenizer().decode(ids).encode("utf-8")
    if len(raw) != raw_len or hashlib.sha256(raw).digest() != expected_sha:
        raise ValueError("Language-U Exact UTF-8 parity check failed")
    return raw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("encode", "decode"):
        p = sub.add_parser(command)
        p.add_argument("source")
        p.add_argument("destination")
    args = parser.parse_args()
    source = Path(args.source).read_bytes()
    result = encode_payload(source) if args.command == "encode" else decode_payload(source)
    Path(args.destination).write_bytes(result)
    print(f"{args.command}_OK source={len(source)} destination={len(result)} sha256={hashlib.sha256(result).hexdigest()}")


if __name__ == "__main__":
    main()
