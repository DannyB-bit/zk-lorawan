#!/usr/bin/env python3
"""Reassemble a CHIRP245 issue after full/partial RF re-fire, preserving duplicates."""
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
    if field("size") != "245":
        continue
    raw = bytes.fromhex("".join(re.findall(r"^((?:[0-9A-F]{2} ?)+)$", block, re.M)))
    item = {k: field(k) for k in ("size", "status", "datr", "freq_hz", "count_us", "crc")}
    item.update(sha256=hashlib.sha256(raw).hexdigest(), raw=raw)
    observations.append(item)
expected_n = int(data["frames"])
target_all = [o for o in observations if o["status"] == "0x10" and o["datr"] == "9" and o["freq_hz"] == "903900000" and len(o["raw"]) == 245]
unique_all = {o["sha256"]: o for o in target_all}
sk_hex = Path.home().joinpath(".config/solana/chirp245_bravo_sk.key").read_bytes().hex()
spec = importlib.util.spec_from_file_location("chirp_raw_rx", "/home/researcher-bravo/fleet-repos/solana-cuneiform-milestone1/tools/chirp_raw_rx.py")
rx = importlib.util.module_from_spec(spec); spec.loader.exec_module(rx)
by_idx = {}
decrypt_fail = 0
for o in unique_all.values():
    try:
        pt = rx.decrypt_frame(o["raw"], sk_hex)
        assert pt[0] == 2 and pt[1] == expected_n and 0 <= pt[2] < expected_n
    except Exception:
        decrypt_fail += 1
        continue
    idx = pt[2]
    chunk = pt[3:].rstrip(b"\x00")
    rec = dict(o, idx=idx, chunk=chunk, chunk_sha256=hashlib.sha256(chunk).hexdigest())
    by_idx.setdefault(idx, {}).setdefault(rec["chunk_sha256"], []).append(rec)
assert set(by_idx) == set(range(expected_n)), f"missing indices: {sorted(set(range(expected_n))-set(by_idx))}"
for idx, variants in by_idx.items():
    assert len(variants) == 1, f"conflicting plaintext variants at idx{idx}: {list(variants)}"
selected = [next(iter(by_idx[i].values()))[0] for i in range(expected_n)]
payload = b"".join(r["chunk"] for r in selected)
payload_sha = hashlib.sha256(payload).hexdigest()
assert payload_sha == data["payload_sha256"], f"SHA mismatch {payload_sha} != {data['payload_sha256']}"
issue_id = data["issue_id"]
payload_path = out_dir / f"{issue_id}.json"
payload_path.write_bytes(payload)
per_frame = []
for r in selected:
    idx = r["idx"]
    (frames_dir / f"frame_{idx:02d}.bin").write_bytes(r["raw"])
    per_frame.append({"file": f"frame_{idx:02d}.bin", "frame_sha256": r["sha256"], "bytes": 245, "ok": True, "verdict": "DECRYPT_OK", "magic": 2, "total": expected_n, "idx": idx, "chunk_bytes": len(r["chunk"]), "chunk_sha256": r["chunk_sha256"], "rf_ciphertext_variants_same_chunk": len(by_idx[idx][r["chunk_sha256"]])})
# The selected records are authoritative; retain all decrypted observations separately.
all_decrypted = [{"idx": r["idx"], "frame_sha256": r["sha256"], "count_us": r["count_us"], "chunk_sha256": r["chunk_sha256"], "selected": r["sha256"] == selected[r["idx"]]["sha256"]} for variants in by_idx.values() for records in variants.values() for r in records]
manifest = {"file": str(payload_path), "file_bytes": len(payload), "file_sha256": payload_sha, "total_chunks": expected_n, "chunk_max": 180, "frames": [{k: r[k] for k in ("idx", "frame_sha256", "chunk_sha256", "chunk_bytes")} for r in per_frame]}
(frames_dir / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
report = {"frames_dir": str(frames_dir), "frames_seen": expected_n, "decrypt_ok": expected_n, "decrypt_fail": decrypt_fail, "unique_authenticated_ciphertexts": sum(len(records) for variants in by_idx.values() for records in variants.values()), "refire_duplicate_ciphertexts": sum(len(records) for variants in by_idx.values() for records in variants.values()) - expected_n, "groups": {str(expected_n): {"total_chunks": expected_n, "have": expected_n, "missing": [], "reassembled_bytes": len(payload), "reassembled_sha256": payload_sha, "wrote": str(payload_path), "expect_sha256": data["payload_sha256"], "sha_match": True}}, "per_frame": per_frame, "all_decrypted": all_decrypted}
(out_dir / f"{issue_id}.json.decrypt_report.json").write_text(json.dumps(report, indent=1) + "\n")
inventory = {"source_log": str(log_path), "observations_245b": len(observations), "crc_ok_target_observations": len(target_all), "unique_crc_ok_target_ciphertexts": len(unique_all), "authenticated_issue_ciphertexts": sum(len(records) for variants in by_idx.values() for records in variants.values()), "selected_frames": expected_n, "refire_duplicate_ciphertexts": sum(len(records) for variants in by_idx.values() for records in variants.values()) - expected_n, "decrypt_fail_or_other_issue": decrypt_fail, "all_decrypted": all_decrypted}
(out_dir / "capture_inventory.json").write_text(json.dumps(inventory, indent=1) + "\n")
print(json.dumps({"ok": True, "issue_id": issue_id, "selected_frames": expected_n, "authenticated_issue_ciphertexts": sum(len(records) for variants in by_idx.values() for records in variants.values()), "payload_bytes": len(payload), "payload_sha256": payload_sha, "sha_match": True}))
