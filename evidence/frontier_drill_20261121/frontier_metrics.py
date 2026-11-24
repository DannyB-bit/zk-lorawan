#!/usr/bin/env python3
"""frontier_metrics.py — measured per-issue RF/loop calibration dossier.
Mines EVIDENCE.jsonl + tx/rx logs; writes CALIBRATION.json. Real data only."""
import json, re, glob, os, statistics
from pathlib import Path

HERE = Path(__file__).resolve().parent
EV = HERE

def parse_tx(logf):
    d = {"frames": 0, "tx_done": 0, "gaps_s": []}
    try:
        lines = open(logf).read().splitlines()
    except Exception:
        return d
    ts = []
    for l in lines:
        m = re.search(r"^(\S+) frame_(\d+) sha=(\w+).*A_LORA_TX_FILE_SEND_COMPLETE=YES", l)
        if m:
            d["tx_done"] += 1
        m2 = re.search(r"t=([0-9.]+)->([0-9.]+)", l)
        if m2:
            ts.append(float(m2.group(1)))
    d["frames"] = d["tx_done"]
    d["gaps_s"] = [round(ts[i+1]-ts[i], 2) for i in range(len(ts)-1)]
    return d

def rx_stats(logf):
    try:
        text = open(logf, errors="replace").read()
    except Exception:
        return {"packets": 0}
    pkts = text.count("----- LoRa packet -----")
    snrs = [float(x) for x in re.findall(r"snr:\s*(-?[0-9.]+)", text)]
    rssis = [float(x) for x in re.findall(r"rssi:\s*(-?[0-9.]+)", text)]
    return {"packets": pkts,
            "snr_mean": round(statistics.mean(snrs), 2) if snrs else None,
            "rssi_mean": round(statistics.mean(rssis), 2) if rssis else None}

events = [json.loads(l) for l in open(EV/"EVIDENCE.jsonl") if l.strip()]
issues = {}
for e in events:
    iid = e.get("issue_id")
    if not iid:
        continue
    r = issues.setdefault(iid, {})
    if e["event"] == "issue_sent":
        r["issue_utc"] = e["utc"]; r["issue_sha"] = e["payload_sha256"]
        r["issue_frames"] = e["frames"]; r["tx_log"] = e["tx_log"]
    if e["event"] == "solution_received":
        r["solution_utc"] = e["utc"]; r["solution_sha"] = e["payload_sha256"]
        r["solution_frames"] = len(e.get("solution", {}).get("_frames", [])) or None
        r["bus_verdict"] = e.get("bus_verdict")

# per-issue derived metrics
out = {"drill": "frontier_drill_20261121", "issues": {}, "aggregate": {}}
round_minutes = []
all_gaps = []
for iid, r in sorted(issues.items()):
    m = dict(r)
    tx = parse_tx(EV/"logs"/r.get("tx_log", "")) if r.get("tx_log") else {}
    m["tx_done"] = tx.get("tx_done")
    if tx.get("gaps_s"):
        m["tx_gap_mean_s"] = round(statistics.mean(tx["gaps_s"]), 2)
        all_gaps += tx["gaps_s"]
    cap = list((EV/"solutions").glob(f"{iid}_capture.json"))
    if cap:
        c = json.loads(cap[0].read_text())
        m["solution_frames"] = len(c["frames"])
        logs = sorted({f["rx_log"] for f in c["frames"]})
        stats = [rx_stats(EV/"logs"/l) for l in logs]
        m["rx_packets"] = sum(s["packets"] for s in stats)
        snrs = [s["snr_mean"] for s in stats if s.get("snr_mean") is not None]
        m["snr_mean"] = round(statistics.mean(snrs), 2) if snrs else None
        m["rx_logs"] = logs
    ch = EV/"attest"/f"{iid}_A_to_B_issue.chain.json"
    m["attest_issue_onchain"] = ch.exists() and bool(json.loads(ch.read_text()).get("signature"))
    ch2 = EV/"attest"/f"{iid}_B_to_A_solution.chain.json"
    m["attest_solution_onchain"] = ch2.exists() and bool(json.loads(ch2.read_text()).get("signature"))
    if r.get("issue_utc") and r.get("solution_utc"):
        import datetime
        f = "%Y-%m-%dT%H:%M:%SZ"
        dt = (datetime.datetime.strptime(r["solution_utc"], f) - datetime.datetime.strptime(r["issue_utc"], f)).total_seconds()/60
        m["round_minutes"] = round(dt, 2)
        round_minutes.append(dt)
    out["issues"][iid] = m

solved = [i for i, m in out["issues"].items() if m.get("solution_utc")]
out["aggregate"] = {
    "issues_fired": len([i for i, m in out["issues"].items() if m.get("issue_utc")]),
    "issues_solved": len(solved),
    "round_minutes_median": round(statistics.median(round_minutes), 2) if round_minutes else None,
    "round_minutes_min": round(min(round_minutes), 2) if round_minutes else None,
    "round_minutes_max": round(max(round_minutes), 2) if round_minutes else None,
    "tx_gap_mean_s": round(statistics.mean(all_gaps), 2) if all_gaps else None,
    "attestations_onchain": len(list((EV/"attest").glob("*.chain.json"))),
}
(EV/"CALIBRATION.json").write_text(json.dumps(out, indent=1))
print(json.dumps(out["aggregate"], indent=1))
for iid, m in sorted(out["issues"].items()):
    print(iid, "| round", m.get("round_minutes"), "min | tx", m.get("tx_done"), "| sol_frames", m.get("solution_frames"),
          "| rx_pkts", m.get("rx_packets"), "| snr", m.get("snr_mean"), "| gap_s", m.get("tx_gap_mean_s"),
          "| chain", m.get("attest_issue_onchain"), m.get("attest_solution_onchain"))
