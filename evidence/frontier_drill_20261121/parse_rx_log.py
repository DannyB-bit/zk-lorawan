#!/usr/bin/env python3
"""Parse a sx1302 test_loragw_hal_rx log -> unique 245B frames -> decrypt (alpha_sk)
-> reassemble RAW file -> verify sha256. Emits evidence JSON.
Usage: parse_rx_log.py <rx_log> <sk_hex_file> <expected_sha256> <out_reassembled> <evidence_json>
"""
import sys, json, hashlib, re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from chirp_raw_rx import decrypt_frame  # canonical chirp245 AEAD open

rx_log, sk_file, expected_sha, out_file, ev_file = sys.argv[1:6]
sk_hex = Path(sk_file).read_text().strip()
text = Path(rx_log).read_text(errors="replace")

# Split into packet blocks
blocks = re.split(r"----- LoRa packet -----", text)[1:]
packets = []
for b in blocks:
    meta = {}
    for key in ["count_us", "size", "chan", "status", "datr", "codr", "rf_chain",
                "freq_hz", "snr_avg", "rssi_chan", "rssi_sig", "crc"]:
        m = re.search(rf"{key}\s*:\s*([^\n]+)", b)
        if m:
            meta[key] = m.group(1).strip()
    # hex payload = lines of hex bytes after the metadata, until "Received"
    hexpart = b.split("Received")[0]
    hexbytes = re.findall(r"\b[0-9A-Fa-f]{2}\b", hexpart)
    # only keep the long hex run (the payload), not metadata numbers
    # payload lines are the ones with many bytes; join all 2-hex tokens that appear
    # after the 'crc:' line
    after_crc = hexpart.split("crc:", 1)[-1] if "crc:" in hexpart else hexpart
    # P2 fix (codex review): the crc line value (e.g. 0xFFDA) would otherwise be
    # picked up as 2 payload bytes -> strip 0x-prefixed tokens before extracting pairs
    after_crc = re.sub(r"0x[0-9A-Fa-f]+", "", after_crc)
    payload_hex = "".join(re.findall(r"[0-9A-Fa-f]{2}", after_crc))
    payload = bytes.fromhex(payload_hex) if payload_hex else b""
    packets.append({"meta": meta, "payload": payload})

# Dedupe by frame sha
uniq = {}
for p in packets:
    if len(p["payload"]) == 245:
        sha = hashlib.sha256(p["payload"]).hexdigest()
        if sha not in uniq:
            uniq[sha] = p

results, chunks = [], {}
total = None
for sha, p in uniq.items():
    rec = {"frame_sha256": sha, "size": len(p["payload"]),
           "freq_hz": p["meta"].get("freq_hz"), "datr": p["meta"].get("datr"),
           "snr_avg": p["meta"].get("snr_avg"), "rssi_chan": p["meta"].get("rssi_chan"),
           "rssi_sig": p["meta"].get("rssi_sig"), "crc": p["meta"].get("crc"),
           "count_us": p["meta"].get("count_us")}
    try:
        pt = decrypt_frame(p["payload"], sk_hex)
        rec["verdict"] = "DECRYPT_OK"
        if pt[0] != 2:
            rec["verdict"] = "DECRYPT_OK_BAD_MAGIC"
        else:
            t, idx = pt[1], pt[2]
            total = t
            chunk = pt[3:].rstrip(b"\x00")
            chunks[idx] = chunk
            rec["idx"] = idx
            rec["total"] = t
            rec["chunk_bytes"] = len(chunk)
    except Exception as e:
        rec["verdict"] = "DECRYPT_FAIL"
        rec["error"] = type(e).__name__
    results.append(rec)

reassembled = b""
complete = False
if total is not None and len(chunks) == total:
    reassembled = b"".join(chunks[i] for i in range(total))
    complete = True
file_sha = hashlib.sha256(reassembled).hexdigest() if complete else None
Path(out_file).write_bytes(reassembled)

out = {
    "rx_log": rx_log, "packets_total": len(packets), "unique_245B_frames": len(uniq),
    "expected_sha256": expected_sha, "reassembled_bytes": len(reassembled),
    "reassembled_sha256": file_sha, "complete": complete,
    "sha_match": (file_sha == expected_sha) if complete else False,
    "total_chunks": total, "chunks_have": len(chunks),
    "per_frame": sorted(results, key=lambda r: r.get("idx", 999)),
}
Path(ev_file).write_text(json.dumps(out, indent=1))
print(json.dumps({k: out[k] for k in ["packets_total", "unique_245B_frames", "total_chunks",
      "chunks_have", "complete", "reassembled_bytes", "reassembled_sha256", "sha_match"]}, indent=1))
