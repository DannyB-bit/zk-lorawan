"""Real cross-node Language-U + AEAD + Groth16 transport integration test."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption, PublicFormat

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from zk_drill_proof import generate_proof_packet, verify_proof_packet


class ExactZkFrameE2E(unittest.TestCase):
    def test_bravo_to_alpha_exact_payload_and_bound_proof(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # Explicitly nonsecret, ephemeral test identities.
            a = x25519.X25519PrivateKey.generate()
            b = x25519.X25519PrivateKey.generate()
            a_sk, b_sk = root / "a.key", root / "b.key"
            a_sk.write_text(a.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption()).hex())
            b_sk.write_text(b.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption()).hex())
            a_pub = a.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
            raw = root / "solution.json"
            raw.write_text(json.dumps({"issue_id": "FRONTIER-GH-0059", "resolved": True,
                                       "solution": "def verify(x): return x == 42",
                                       "evidence": "Language-U exact + Groth16"}))
            frames = root / "frames"
            subprocess.run([sys.executable, str(ROOT / "tools/chirp_raw_tx.py"), str(raw), a_pub,
                            str(frames), "--codec", "language-u-exact"], check=True,
                           capture_output=True, timeout=120)
            transport = frames / "transport.bin"
            packet, public = root / "solution.zkdp", root / "proof.json"
            generate_proof_packet(transport, 59, packet, public,
                                  private_key_file=b_sk, gateway_address=a_pub)
            proof_frames = root / "proof_frames"
            subprocess.run([sys.executable, str(ROOT / "tools/chirp_raw_tx.py"), str(packet), a_pub,
                            str(proof_frames), "--codec", "raw"], check=True,
                           capture_output=True, timeout=60)
            decoded, decoded_proof = root / "decoded.json", root / "decoded.zkdp"
            for manifest, frame_dir, output in [
                (frames / "manifest.json", frames, decoded),
                (proof_frames / "manifest.json", proof_frames, decoded_proof),
            ]:
                result = subprocess.run([sys.executable, str(ROOT / "tools/chirp_raw_rx.py"), "reassemble",
                                         str(manifest), str(frame_dir), str(a_sk), str(output)],
                                        capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(decoded.read_bytes(), raw.read_bytes())
            self.assertEqual(decoded_proof.read_bytes(), packet.read_bytes())
            self.assertTrue(verify_proof_packet(decoded_proof, transport, gateway_address=a_pub))
            transport.write_bytes(transport.read_bytes()[:-1] + bytes([transport.read_bytes()[-1] ^ 1]))
            self.assertFalse(verify_proof_packet(decoded_proof, transport, gateway_address=a_pub))


if __name__ == "__main__":
    unittest.main()
