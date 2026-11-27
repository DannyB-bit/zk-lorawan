"""Real-tokenizer tests for the lossless Language-U Exact capsule codec."""

from pathlib import Path
import sys

import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from language_u_exact_codec import decode_payload, encode_payload


class LanguageUExactCodecTests(unittest.TestCase):
    def test_round_trip_utf8_payload(self):
        raw = "Language-U exact: ASCII, Ελληνικά, 中文, and 🦀.\n".encode("utf-8")

        capsule = encode_payload(raw)

        self.assertTrue(capsule.startswith(b"LUCX1"))
        self.assertEqual(decode_payload(capsule), raw)

    def test_five_real_frontier_issue_payloads_are_byte_exact(self):
        root = Path(__file__).resolve().parents[1]
        issues = sorted((root / "evidence/frontier_drill_20261121/issues").glob("FRONTIER-GH-*.json"))[-5:]
        self.assertEqual(len(issues), 5)
        for issue in issues:
            with self.subTest(issue=issue.name):
                raw = issue.read_bytes()
                capsule = encode_payload(raw)
                self.assertLess(len(capsule), len(raw))
                self.assertEqual(decode_payload(capsule), raw)

    def test_source_code_snippets_are_byte_exact(self):
        samples = [
            b"def solve(x):\n    return x * x + 1\n",
            b"fn main() { println!(\"zk-lorawan\"); }\n",
            b"const verify = async (proof) => contract.verify(proof);\n",
        ]
        for raw in samples:
            with self.subTest(raw=raw):
                self.assertEqual(decode_payload(encode_payload(raw)), raw)

    def test_truncation_trailing_and_tampering_fail_closed(self):
        raw = b'{"issue_id":"TEST","solution":"return x + 1;","unicode":"\xe4\xb8\xad"}\n'
        capsule = encode_payload(raw)
        invalid = [capsule[:-1], capsule + b"trailing", capsule[:20] + b"X" + capsule[21:]]
        body = bytearray(capsule)
        body[-8] ^= 1
        invalid.append(bytes(body))
        for candidate in invalid:
            with self.subTest(size=len(candidate)):
                with self.assertRaises(ValueError):
                    decode_payload(candidate)


if __name__ == "__main__":
    unittest.main()
