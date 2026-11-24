#!/usr/bin/env python3
"""Capture declared 245B RAW CHIRP245 frames from a real HAL log and reassemble."""
import hashlib, importlib.util, json, re, sys
from pathlib import Path

log_path, declare_path, out_dir = map(Path, sys.argv[1:4])
declare = json.loads(declare_path.read_text())
data = declare["data"]
out_dir.mkdir(parents=True, exist_ok=True)
frames_dir = out_dir / "frames_issue"
frames_dir.mkdir(exist_ok=True)
text = log_path.read_text(errors="replace")
observations = []
for block in text.split("----- LoRa packet -----")[1:]:
    def field(name):
        m = re.search(rf"^\s*{re.escape(name)}:?\s+(\S+)", block, re.M)
        return m.group(1) if m else None
    size = field("size")
    if size != "245":
        continue
    hex_lines = re.findall(r"^((?:[0-9A-F]{2} ?)+)$", block, re.M)
    raw = bytes.fromhex("".join(hex_lines))
    item = {k: field(k) for k in ("size", "status", "datr", "freq_hz", "count_us", "crc")}
    item["sha256"] = hashlib.sha256(raw).hexdigest()
    item["raw"] = raw
    observations.append(item)
target = [o for o in observations if o["status"] == "0x10" and o["datr"] == "9" and o["freq_hz"] == "903900000" and len(o["raw"]) == 245]
unique = {o["sha256"]: o for o in target}
expected_n = int(data["frames"])
assert len(unique) == expected_n, f"capture incomplete: {len(unique)}/{expected_n}"
# Private key is read locally, never printed or persisted in the evidence dir.
sk_hex = Path.home().joinpath(".config/solana/chirp245_bravo_sk.key").read_bytes().hex()
spec = importlib.util.spec_from_file_location("chirp_raw_rx", "/home/researcher-bravo/fleet-repos/solana-cuneiform-milestone1/tools/chirp_raw_rx.py")
rx = importlib.util.module_from_spec(spec); spec.loader.exec_module(rx)
chunks, per_frame = {}, []
for sha, o in unique.items():
    pt = rx.decrypt_frame(o["raw"], sk_hex)
    assert pt[0] == 2, "bad RAW plaintext magic"
    total, idx = pt[1], pt[2]
    assert total == expected_n and 0 <= idx < total and idx not in chunks
    chunk = pt[3:].rstrip(b"\x00")
    chunks[idx] = chunk
    (frames_dir / f"frame_{idx:02d}.bin").write_bytes(o["raw"])
    per_frame.append({"file": f"frame_{idx:02d}.bin", "frame_sha256": sha, "bytes": 245, "ok": True, "verdict": "DECRYPT_OK", "magic": pt[0], "total": total, "idx": idx, "chunk_bytes": len(chunk), "chunk_sha256": hashlib.sha256(chunk).hexdigest()})
assert set(chunks) == set(range(expected_n))
payload = b"".join(chunks[i] for i in range(expected_n))
payload_sha = hashlib.sha256(payload).hexdigest()
assert payload_sha == data["payload_sha256"], f"SHA mismatch {payload_sha} != {data['payload_sha256']}"
issue_id = data["issue_id"]
payload_path = out_dir / f"{issue_id}.json"
payload_path.write_bytes(payload)
manifest = {"file": str(payload_path), "file_bytes": len(payload), "file_sha256": payload_sha, "total_chunks": expected_n, "chunk_max": 180, "frames": [{"idx": r["idx"], "frame_sha256": r["frame_sha256"], "chunk_sha256": r["chunk_sha256"], "chunk_bytes": r["chunk_bytes"]} for r in sorted(per_frame, key=lambda r: r["idx"])]}
(frames_dir / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
report = {"frames_dir": str(frames_dir), "frames_seen": expected_n, "decrypt_ok": expected_n, "decrypt_fail": 0, "groups": {str(expected_n): {"total_chunks": expected_n, "have": expected_n, "missing": [], "reassembled_bytes": len(payload), "reassembled_sha256": payload_sha, "wrote": str(payload_path), "expect_sha256": data["payload_sha256"], "sha_match": True}}, "per_frame": per_frame}
(out_dir / f"{issue_id}.json.decrypt_report.json").write_text(json.dumps(report, indent=1) + "\n")
inventory = {"source_log": str(log_path), "observations_245b": len(observations), "crc_ok_target_observations": len(target), "unique_crc_ok_target_frames": len(unique), "rejected_245b": [{k: v for k, v in o.items() if k != "raw"} for o in observations if o not in target], "frames": [{k: v for k, v in o.items() if k != "raw"} for o in unique.values()]}
(out_dir / "capture_inventory.json").write_text(json.dumps(inventory, indent=1) + "\n")
print(json.dumps({"ok": True, "issue_id": issue_id, "unique_crc_ok_target_frames": len(unique), "decrypt_ok": expected_n, "payload_bytes": len(payload), "payload_sha256": payload_sha, "sha_match": True}))
