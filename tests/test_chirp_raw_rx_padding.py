import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from chirp_raw_rx import extract_declared_chunk


def test_trailing_zero_payload_is_not_padding():
    payload = b"range-coded-transport\x00\x00"
    plaintext = b"\x02" + bytes([180]) + b"\x00" + payload.ljust(180, b"\x00")
    assert extract_declared_chunk(plaintext, len(payload)) == payload


def test_nonzero_padding_is_rejected():
    payload = b"abc\x00"
    plaintext = b"\x02" + bytes([180]) + b"\x00" + payload + b"\x00" * 175 + b"\x01"
    with pytest.raises(ValueError, match="nonzero padding"):
        extract_declared_chunk(plaintext, len(payload))


@pytest.mark.parametrize("declared", [-1, 181])
def test_declared_chunk_length_is_bounded(declared):
    plaintext = b"\x02" + bytes([180]) + b"\x00" + b"\x00" * 180
    with pytest.raises(ValueError, match="outside payload range"):
        extract_declared_chunk(plaintext, declared)
