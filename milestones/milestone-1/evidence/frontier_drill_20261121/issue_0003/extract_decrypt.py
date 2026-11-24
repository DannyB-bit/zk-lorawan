#!/usr/bin/env python3
"""Extract the declared issue-0003 target frames from the live HAL log and decrypt them."""
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

EV = Path(__file__).resolve().parent
LOG = Path(sys.argv[1])
EXPECT_SHA = "edb6130d55422084de34b3005dabf71db8384d658cb7d24d6917c6c1fd024cde"
SK = Path.home() / "fleet/evidence/minigame_drill_20261115/bravo_sk.hex"
TOOL = Path.home() / "fleet-repos/solana-cuneiform-milestone1/tools/chirp_raw_rx.py"
spec = importlib.util.spec_from_file_location("chirp_raw_rx", TOOL)
rx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rx)

text = LOG.read_text(errors="replace")
observations = []
for block in text.split("----- LoRa packet -----")[1:]:
    def field(name):
        m = re.search(r"^\s*" + re.escape(name) + r":?\s+(\S+)", block, re.M)
        return m.group(1) if m else None
    size = field("size")
    if size != "245":
        continue
    hex_lines = re.findall(r"^((?:[0-9A-F]{2} ?)+)\s*$", block, re.M)
    raw = bytes.fromhex("".join(hex_lines))
    if len(raw) != 245:
        raise RuntimeError(f"parsed frame length {len(raw)} != 245")
    observations.append({
        "size": 245,
        "status": field("status"),
        "freq_hz": int(field("freq_hz")),
        "datr": int(field("datr")),
        "count_us": int(field("count_us")),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "raw": raw,
    })

target = [o for o in observations if o["status"] == "0x10" and o["freq_hz"] == 903900000 and o["datr"] == 9]
unique = {}
for o in target:
    unique.setdefault(o["sha256"], o)
rejected = [{k: v for k, v in o.items() if k != "raw"} for o in observations if o not in target]
frames_dir = EV / "frames_issue"
frames_dir.mkdir(parents=True, exist_ok=True)
for o in unique.values():
    (frames_dir / f"frame_{o['sha256'][:12]}.bin").write_bytes(o["raw"])
inventory = {
    "source_log": str(LOG),
    "observations_245b": len(observations),
    "crc_ok_target_observations": len(target),
    "unique_crc_ok_target_frames": len(unique),
    "rejected_245b": rejected,
    "frames": [{k: v for k, v in o.items() if k not in ("raw", "count_us")} for o in unique.values()],
}
(EV / "capture_inventory.json").write_text(json.dumps(inventory, indent=1) + "\n")

sk_hex = SK.read_text().strip()
groups = {}
per_frame = []
for sha, o in sorted(unique.items()):
    rec = {"file": f"frame_{sha[:12]}.bin", "frame_sha256": sha, "bytes": 245}
    try:
        pt = rx.decrypt_frame(o["raw"], sk_hex)
        if pt[0] != 2:
            raise ValueError(f"bad plaintext magic {pt[0]}")
        total, idx = pt[1], pt[2]
        chunk = pt[3:].rstrip(b"\x00")
        rec.update(ok=True, verdict="DECRYPT_OK", magic=2, total=total, idx=idx,
                   chunk_bytes=len(chunk), chunk_sha256=hashlib.sha256(chunk).hexdigest())
        groups.setdefault(total, {})[idx] = chunk
    except Exception as exc:
        rec.update(ok=False, verdict="DECRYPT_FAIL", error=type(exc).__name__)
    per_frame.append(rec)
report = {"frames_dir": str(frames_dir), "frames_seen": len(unique),
          "decrypt_ok": sum(r.get("ok") is True for r in per_frame),
          "decrypt_fail": sum(r.get("ok") is not True for r in per_frame),
          "groups": {}, "per_frame": per_frame}
for total, chunks in sorted(groups.items()):
    g = {"total_chunks": total, "have": len(chunks),
         "missing": [i for i in range(total) if i not in chunks]}
    if len(chunks) == total:
        payload = b"".join(chunks[i] for i in range(total))
        out = EV / "FRONTIER-GH-0003.json"
        out.write_bytes(payload)
        sha = hashlib.sha256(payload).hexdigest()
        g.update(reassembled_bytes=len(payload), reassembled_sha256=sha,
                 wrote=str(out), expect_sha256=EXPECT_SHA, sha_match=sha == EXPECT_SHA)
    report["groups"][str(total)] = g
(EV / "FRONTIER-GH-0003.json.decrypt_report.json").write_text(json.dumps(report, indent=1) + "\n")
print(json.dumps({"inventory": {k: v for k, v in inventory.items() if k not in ("frames", "rejected_245b")},
                  "decrypt_ok": report["decrypt_ok"], "decrypt_fail": report["decrypt_fail"],
                  "groups": report["groups"]}, indent=1))
if report["groups"].get("12", {}).get("sha_match") is not True:
    raise SystemExit(1)
