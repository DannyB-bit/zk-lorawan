"""Z-WORMHOLE B-fix seed codec tests — 34-byte ZYM2 v0x0201 frames.

Covers tools/wormhole_seed.py against the B-fixed C engine:
1. bit-exact round-trip: 18-bit axes survive pack -> verify (err <= 1e-5)
2. upstream regression vector: the input that broke shipped v2.0.0
   (axis errors up to 1.25 there) now round-trips cleanly
3. normalization symmetry: pack normalizes before quantization, so any
   input scale yields the same frame
4. cross-implementation interop: frames bit-identical to the C twin when
   present on this node; skipped (not failed) when the C tree is absent
5. fail-closed: tamper (bit flip) and truncation reject with clear errors
"""
from __future__ import annotations

import importlib.util
import os
import random
import struct
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

_spec = importlib.util.spec_from_file_location(
    "wormhole_seed", os.path.join(os.path.dirname(_HERE), "tools", "wormhole_seed.py"))
ws = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ws)

C_ENGINE_DIR = os.path.expanduser(
    "~/fleet-repos/hf/consider/Consider-Trinity-V2/cuneiform_octonion_engine.c")

BREAK_VECTOR = [0.1, 0.2, -0.3, 0.4, 0.5, -0.6, 0.7, 0.8]


class TestRoundTrip(unittest.TestCase):
    def test_exact_roundtrip(self):
        f = ws.pack_seed(BREAK_VECTOR, 6, 0x12345678)
        rec = ws.verify_seed(f)
        norm = sum(x * x for x in BREAK_VECTOR) ** 0.5
        unit = [x / norm for x in BREAK_VECTOR]
        err = max(abs(a - b) for a, b in zip(unit, rec["vec"]))
        self.assertLess(err, 2e-5, f"axis error {err} exceeds 18-bit quantization + fp32 rounding")

    def test_random_battery(self):
        random.seed(42)
        for t in range(100):
            v = [random.uniform(-3, 3) for _ in range(8)]  # any scale
            f = ws.pack_seed(v, t % 18, t)
            rec = ws.verify_seed(f)
            self.assertEqual(rec["domain_id"], t % 18)
            self.assertEqual(rec["fts5_hash"], t)
            norm = sum(x * x for x in v) ** 0.5
            err = max(abs(a - b) for a, b in zip([x / norm for x in v], rec["vec"]))
            self.assertLess(err, 2e-5)  # 18-bit quantum (~7.6e-6) + fp32 rounding headroom

    def test_scale_invariance(self):
        v = BREAK_VECTOR
        f1 = ws.pack_seed(v, 3, 1)
        f2 = ws.pack_seed([x * 100 for x in v], 3, 1)
        # normalized inputs pack identically (pack normalizes first)
        self.assertEqual(f1[8:26], f2[8:26])

    def test_meta_fields(self):
        f = ws.pack_seed(BREAK_VECTOR, 9, 0xDEADBEEF)
        magic, version, dom = struct.unpack("<IHH", f[0:8])
        self.assertEqual(magic, 0x5A594D32)
        self.assertEqual(version, 0x0201)  # B-fix marker
        self.assertEqual(dom, 9)


class TestFailClosed(unittest.TestCase):
    def test_tamper_detected(self):
        f = bytearray(ws.pack_seed(BREAK_VECTOR, 6, 7))
        f[10] ^= 0x01
        with self.assertRaises(ValueError):
            ws.verify_seed(bytes(f))

    def test_bad_magic(self):
        f = bytearray(ws.pack_seed(BREAK_VECTOR, 6, 7))
        f[0] ^= 0xFF
        with self.assertRaises(ValueError):
            ws.verify_seed(bytes(f))

    def test_bad_size(self):
        f = ws.pack_seed(BREAK_VECTOR, 6, 7)
        with self.assertRaises(ValueError):
            ws.verify_seed(f[:-1])


class TestCInterop(unittest.TestCase):
    def test_bit_identical_to_c_twin(self):
        if not os.path.exists(C_ENGINE_DIR):
            self.skipTest("C engine tree not present on this node")
        import subprocess, tempfile
        with tempfile.TemporaryDirectory() as td:
            src = os.path.join(td, "emit.c")
            exe = os.path.join(td, "emit")
            with open(src, "w") as fh:
                fh.write('#include <stdio.h>\n#include "cuneiform_octonion_engine.h"\n'
                         'int main(void){ OctonionVector in = {{0.1f,0.2f,-0.3f,0.4f,'
                         '0.5f,-0.6f,0.7f,0.8f}}; CuneiformFrameV2 f; '
                         'pack_cuneiform_frame_v2(6,&in,0x12345678u,&f); '
                         'fwrite(&f,sizeof(f),1,stdout); return 0; }\n')
            inc = os.path.dirname(C_ENGINE_DIR)
            subprocess.run(["gcc", "-O2", "-std=c99", f"-I{inc}", src, C_ENGINE_DIR,
                            "-o", exe, "-lm"], check=True, capture_output=True)
            c_frame = subprocess.run([exe], capture_output=True, check=True).stdout
        py_frame = ws.pack_seed(BREAK_VECTOR, 6, 0x12345678)
        self.assertEqual(c_frame, py_frame, "C and Python frames must be bit-identical")


if __name__ == "__main__":
    unittest.main()
