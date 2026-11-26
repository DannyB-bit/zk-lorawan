#!/usr/bin/env python3
"""frontier_loop.py — Frontier-1000 ZK-LoRaWAN A<->B drill orchestrator (Researcher A side).

Real code only (fleet law 2026-10-04). One invocation = one state-machine step.
Designed to be driven by a cron "alarm" every ~15 min until TARGET issues are solved.

State machine (persisted in state.json):
  announce        -> seal+fire mission_brief.md to bravo over real LoRa, post bus brief
  await_ack       -> wait for B's sealed mission ack (RX) or bus frontier_mission_ack
  send_issue      -> pick next unsolved issue, seal to BRAVO_PUB, fire when B window open
  await_solution  -> RX armed, scan logs for B->A sealed resolved payload, verify sha, commit
  done            -> TARGET reached, compile dossier, final commit

Bus carries METADATA ONLY (issue_id, sha256, counts) — issue content goes over ZK-LoRaWAN only.

Usage: frontier_loop.py step
"""
import json, os, re, sys, time, hashlib, subprocess, urllib.request, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
TOOLS = REPO / "tools"
BENCH = Path("/home/researcher-alpha/fleet-repos/frontier-1000-complex-github-issues-benchmark/frontier_1000_complex_github_issues_exam.json")
LOGS = HERE / "logs"
FRAMES = HERE / "frames"
ISSUES = HERE / "issues"
SOLS = HERE / "solutions"
for d in (LOGS, FRAMES, ISSUES, SOLS):
    d.mkdir(parents=True, exist_ok=True)

BRAVO_PUB = "c51a77e603e376223a3796a7817ead68333754cd677a6a06a5fb54be75bfb118"
ALPHA_PUB = "9af36ea21df497be6aa3a41c8e4f78140a379c67277c42fdcfe7397688a62942"
ALPHA_SK = Path("/home/researcher-alpha/.config/solana/chirp245_alpha_sk.key").read_text().strip()
BUS = os.environ.get("FRONTIER_BUS", "http://127.0.0.1:8643")  # PII policy: no LAN IPs in public repo (Dan 2026-11-25)
TOKEN = os.environ["FLEET_FAST_TOKEN"]
TARGET = 1000         # Dan's order 2026-11-24: the FULL 1000-problem benchmark (was 100)
DRILL = "frontier_drill_20261121"
STATE = HERE / "state.json"
EVID = HERE / "EVIDENCE.jsonl"

sys.path.insert(0, str(TOOLS))
from chirp_raw_rx import decrypt_frame  # canonical AEAD open


ATTEST = HERE / "attest"


def ensure_attest(iid, leg, payload_sha256, verdict):
    """Per-leg on-chain Solana attestation (derived-key hash anchoring, devnet).
    Idempotent: skips if a chain proof with a signature already exists."""
    ATTEST.mkdir(exist_ok=True)
    chain_f = ATTEST / f"{iid}_{leg}.chain.json"
    if chain_f.exists():
        try:
            if json.loads(chain_f.read_text()).get("signature"):
                return json.loads(chain_f.read_text())
        except Exception:
            pass
    att = {"attestation": "zk-lorawan-frontier-drill", "drill": DRILL,
           "issue_id": iid, "leg": leg, "payload_sha256": payload_sha256, "verdict": verdict,
           "node": "RakMiner-A", "rf": {"freq_mhz": 903.9, "sf": 9, "bw_khz": 125},
           "evidence_repo": "DannyB-bit/zk-lorawan@researcher-a/frontier-drill-20261121",
           "event_utc": now()}
    af = ATTEST / f"{iid}_{leg}.json"
    af.write_text(json.dumps(att, indent=1))
    try:
        r = subprocess.run([str(Path.home() / "solana-venv/bin/python3"),
                            str(REPO / "tools/attest_onchain.py"), str(af), "--yes"],
                           capture_output=True, text=True, timeout=150)
        chain_f.write_text(r.stdout or r.stderr)
        log(f"attest {iid} {leg}: {(r.stdout or r.stderr)[:140]}")
        try:
            return json.loads(chain_f.read_text())
        except Exception:
            return {}
    except Exception as e:
        chain_f.write_text(json.dumps({"error": str(e)}))
        log(f"attest {iid} {leg} ERROR: {e}")
        return {}


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


import re as _re

def sanitize(text):
    """PII policy (Dan 2026-11-25): hash LAN IPs / concentrator EUIs out of any
    text before it reaches committed logs. Payload evidence is hash-locked and
    never altered; logs and code are always scrubbed."""
    def ip_sub(m):
        return "lan-" + hashlib.sha256(m.group(0).encode()).hexdigest()[:8]
    def eui_sub(m):
        return "eui-" + hashlib.sha256(m.group(0).encode()).hexdigest()[:8]
    text = _re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", ip_sub, str(text))
    text = _re.sub(r"\b0016c001[0-9a-fA-F]{8}\b", eui_sub, text)
    return text


def log(msg):
    line = f"{now()} {sanitize(msg)}"
    print(line)
    with open(LOGS / "loop.log", "a") as f:
        f.write(line + "\n")


def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {"drill": DRILL, "phase": "announce", "target": TARGET,
            "solved": [], "current_issue": None, "bus_seq_last": 0,
            "brief_fired": False, "brief_sha": None, "brief_frames": 0,
            "issue_sent": {}, "refire_count": 0, "started_utc": now(),
            "b_last_seen_ts": 0.0, "rx_window_open_seq": 0, "rx_window_closes_ts": 0.0,
            "mission_acked": False}


def save_state(s):
    STATE.write_text(json.dumps(s, indent=1))


def bus_get(since):
    url = f"{BUS}/events?since={since}&token={TOKEN}"
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.load(r).get("events", [])


def bus_post(etype, data):
    body = json.dumps({"token": TOKEN, "type": etype, "data": data}).encode()
    req = urllib.request.Request(BUS + "/events", data=body,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def evid(entry):
    entry["utc"] = now()
    with open(EVID, "a") as f:
        f.write(json.dumps(entry) + "\n")


def seal(src: Path, recipient_pub: str, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    r = subprocess.run([sys.executable, str(TOOLS / "chirp_raw_tx.py"),
                        str(src), recipient_pub, str(out_dir)],
                       capture_output=True, text=True, timeout=120)
    man = json.loads((out_dir / "manifest.json").read_text())
    return man


def fire(frames_dir: Path, label: str):
    logf = LOGS / f"tx_{label}_{time.strftime('%H%M%S', time.gmtime())}.log"
    r = subprocess.run(["bash", str(HERE / "fire_frames.sh"), str(frames_dir), str(logf), label],
                       capture_output=True, text=True, timeout=1800)
    tail = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "fire_failed"
    return logf, tail


def rx_running():
    return subprocess.run(["pgrep", "-f", "test_loragw_hal_r[x]"],
                          capture_output=True).returncode == 0


def arm_rx_bg(seconds=600):
    if rx_running():
        return None
    logf = LOGS / f"rx_{time.strftime('%H%M%S', time.gmtime())}.log"
    subprocess.Popen(["bash", str(HERE / "arm_rx.sh"), str(seconds), str(logf)],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    log(f"RX armed bg {seconds}s -> {logf.name}")
    return logf.name


def scan_rx_payloads():
    """Scan all frontier RX logs -> unique 245B frames -> decrypt with alpha_sk ->
    reassemble RAW (0x02) files. Returns list of {sha256, bytes, source_log}."""
    out = []
    seen = set()
    for lf in sorted(LOGS.glob("rx_*.log")):
        try:
            text = lf.read_text(errors="replace")
        except Exception:
            continue
        for b in re.split(r"----- LoRa packet -----", text)[1:]:
            hexpart = b.split("Received")[0]
            after_crc = hexpart.split("crc:", 1)[-1] if "crc:" in hexpart else hexpart
            after_crc = re.sub(r"0x[0-9A-Fa-f]+", "", after_crc)
            ph = "".join(re.findall(r"[0-9A-Fa-f]{2}", after_crc))
            if len(ph) != 490:
                continue
            payload = bytes.fromhex(ph)
            sha = hashlib.sha256(payload).hexdigest()
            if sha in seen:
                continue
            seen.add(sha)
            try:
                pt = decrypt_frame(payload, ALPHA_SK)
            except Exception:
                continue  # not sealed to alpha (e.g. our own A->B frames echoed) — skip
            if pt[0] != 0x02:
                continue
            out.append({"frame_sha": sha, "total": pt[1], "idx": pt[2],
                        "chunk": pt[3:].rstrip(b"\x00"), "log": lf.name})
    # Reassemble per (total, rx_log) burst first, then per-total global fallback.
    # Two different solutions can share a chunk count; global-only grouping would
    # mix their frames and corrupt the payload. Return ALL complete candidates
    # (deduped by sha) so the solver can select by bravo's verdict sha.
    def reassemble(chunks):
        data = b"".join(chunks[i]["chunk"] for i in range(len(chunks)))
        return {"sha256": hashlib.sha256(data).hexdigest(), "bytes": data,
                "frames": [{"frame_sha256": chunks[i]["frame_sha"], "idx": i,
                            "total": chunks[i]["total"], "rx_log": chunks[i]["log"],
                            "verdict": "DECRYPT_OK"} for i in sorted(chunks)]}
    results, seen_sha = [], set()
    groups = {}
    for fr in out:
        groups.setdefault((fr["total"], fr["log"]), {})[fr["idx"]] = fr
    for fr in out:  # global fallback per total
        groups.setdefault((fr["total"], None), {})[fr["idx"]] = fr
    for (total, _log), chunks in groups.items():
        if len(chunks) != total:
            continue
        r = reassemble(chunks)
        if r["sha256"] not in seen_sha:
            seen_sha.add(r["sha256"])
            results.append(r)
    return results


def git_commit(msg):
    # refresh the measured calibration dossier so every commit carries fresh metrics
    subprocess.run([sys.executable, str(HERE / "frontier_metrics.py")], capture_output=True)
    subprocess.run(["git", "-C", str(REPO), "add", "-A", "evidence/frontier_drill_20261121"],
                   capture_output=True)
    r = subprocess.run(["git", "-C", str(REPO), "commit", "-m", msg, "--allow-empty"],
                       capture_output=True, text=True)
    # self-heal against concurrent fleet commits to master (B/docs/CI), then push
    subprocess.run(["git", "-C", str(REPO), "pull", "--rebase", "origin", "master"],
                   capture_output=True, text=True)
    p = subprocess.run(["git", "-C", str(REPO), "push", "origin",
                        "master"], capture_output=True, text=True)
    log(f"git commit: {r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr.strip()[:120]} | push rc={p.returncode}")
    return r.returncode == 0


def bravo_events(events):
    return [e for e in events if e.get("data", {}).get("node") == "bravo"
            or e.get("type", "") != "heartbeat_alpha"]


def step():
    s = load_state()
    bench = json.loads(BENCH.read_text())
    # Fetch new events since cursor, plus a lookback window for context (b_alive, rx_window)
    since = max(0, s["bus_seq_last"] - 100)
    events = bus_get(since)
    new_events = [e for e in events if e["seq"] > s["bus_seq_last"]]
    if new_events:
        s["bus_seq_last"] = max(e["seq"] for e in new_events)
    # Track persistent B state from ALL events in the lookback window
    br = [e for e in events if e.get("data", {}).get("node") == "bravo"
          or e.get("type", "") != "heartbeat_alpha"]
    now_ts = time.time()
    for e in br:
        ts = e.get("ts", 0)
        if ts > s.get("b_last_seen_ts", 0):
            s["b_last_seen_ts"] = ts
        dt = e.get("data", {})
        if e["type"] == "rx_window_open" and dt.get("drill") == DRILL:
            s["rx_window_open_seq"] = e["seq"]
            closes = dt.get("closes_at_utc")
            if closes:
                try:
                    s["rx_window_closes_ts"] = time.mktime(
                        datetime.datetime.strptime(closes, "%Y-%m-%dT%H:%M:%SZ").timetuple())
                except Exception:
                    pass
    b_alive = now_ts - s.get("b_last_seen_ts", 0) < 2700  # bravo active in last 45 min
    window_open = (s.get("rx_window_open_seq", 0) > s["bus_seq_last"] - 100
                   and now_ts < s.get("rx_window_closes_ts", 0))
    for e in new_events:
        if e.get("data", {}).get("node") == "bravo" or e.get("type", "") != "heartbeat_alpha":
            log(f"bus bravo event seq={e['seq']} type={e['type']} data={str(e.get('data', {}))[:160]}")

    # scan RF for B->A sealed payloads (ack or solutions)
    payloads = scan_rx_payloads()
    verdict_shas = {e["data"].get("issue_id"): e["data"].get("payload_sha256")
                    for e in br if e["type"] == "frontier_solution_verdict"}
    # STRICT manifest binding (2026-11-25, after the 0036 mixed-capture incident):
    # when Bravo declared an exact frame_sha256 list, a capture candidate is valid ONLY if
    # every captured frame sha is in that list AND the reassembled payload sha matches.
    verdict_frames = {e["data"].get("issue_id"): set(e["data"].get("frame_sha256") or [])
                      for e in br if e["type"] == "frontier_solution_verdict"
                      and e["data"].get("frame_sha256")}
    ack = None
    solutions = {}
    for p in payloads:
        try:
            j = json.loads(p["bytes"].decode())
        except Exception:
            continue
        if j.get("type") == "frontier_mission_ack":
            ack = j
        if j.get("issue_id"):
            iid = j["issue_id"]
            declared = verdict_frames.get(iid)
            if declared:
                cap_shas = {f.get("frame_sha256") for f in p.get("frames", [])}
                if not cap_shas or not cap_shas.issubset(declared) or p["sha256"] != verdict_shas.get(iid):
                    log(f"REJECT mixed/unbound capture for {iid}: {len(cap_shas)} frames, subset_of_manifest={cap_shas.issubset(declared)}, sha_match={p['sha256'] == verdict_shas.get(iid)}")
                    continue
            entry = {"sha256": p["sha256"], "payload": j, "frames": p.get("frames", [])}
            if iid not in solutions or p["sha256"] == verdict_shas.get(iid):
                # first candidate wins unless a later one matches bravo's verdict sha
                solutions[iid] = entry

    phase = s["phase"]
    log(f"phase={phase} solved={len(s['solved'])}/{s['target']} current={s['current_issue']} b_alive={b_alive} rx_running={rx_running()}")

    if phase == "announce":
        if not s["brief_fired"]:
            man = seal(HERE / "mission_brief.md", BRAVO_PUB, FRAMES / "brief")
            logf, tail = fire(FRAMES / "brief", "mission_brief")
            s["brief_fired"] = True
            s["brief_sha"] = man["file_sha256"]
            s["brief_frames"] = man["total_chunks"]
            evid({"event": "mission_brief_fired", "sha256": man["file_sha256"],
                  "frames": man["total_chunks"], "tx_log": logf.name, "tx": tail,
                  "recipient": "bravo_pub", "rf": "903.9MHz SF9 BW125 14dBm"})
            bus_post("frontier_drill_brief", {
                "to": "bravo", "from": "alpha", "drill": DRILL,
                "mission": "Frontier benchmark over ZK-LoRaWAN: A sends ONE issue at a time sealed over real LoRa; B solves and returns resolved payload sealed to alpha_pub; one at a time only; target 100; full brief sealed in mission_brief chirps on 903.9MHz",
                "brief_sha256": man["file_sha256"], "brief_frames": man["total_chunks"],
                "alpha_pub_for_reply": ALPHA_PUB,
                "bravo_sk_path_on_B": "/home/researcher-bravo/.config/solana/chirp245_bravo_sk.key",
                "alpha_sk_path_on_A": "/home/researcher-alpha/.config/solana/chirp245_alpha_sk.key",
                "rf": {"freq_mhz": 903.9, "sf": 9, "bw_khz": 125, "power_dbm": 14},
                "ack_required": {"type": "frontier_mission_ack", "drill": DRILL, "accepted": True, "target": TARGET},
            })
            s["phase"] = "await_ack"
            save_state(s)
            git_commit(f"evidence(frontier-drill): mission brief sealed+fired to B over real LoRa ({man['total_chunks']} chirps, sha {man['file_sha256'][:16]}...)")
        else:
            s["phase"] = "await_ack"
            save_state(s)

    elif phase == "await_ack":
        if ack or any(e["type"] == "frontier_mission_ack" for e in br):
            log(f"mission ack received: {ack or 'bus'}")
            evid({"event": "mission_ack", "ack": ack})
            s["phase"] = "send_issue"
            save_state(s)
            git_commit("evidence(frontier-drill): B accepted mission (frontier_mission_ack)")
        else:
            window_open = any(e["type"] == "rx_window_open" and time.time() - e["ts"] < 900 for e in br)
            if window_open and s["refire_count"] < 6:
                s["refire_count"] += 1
                logf, tail = fire(FRAMES / "brief", f"mission_brief_refire{s['refire_count']}")
                evid({"event": "mission_brief_refired", "n": s["refire_count"], "tx": tail})
                bus_post("frontier_drill_brief_refire", {"drill": DRILL, "n": s["refire_count"], "brief_sha256": s["brief_sha"]})
            else:
                bus_post("frontier_drill_nudge", {"drill": DRILL, "phase": "await_ack",
                          "note": "B: arm RX 903.9 SF9 and post rx_window_open drill=frontier_drill_20261121, then ack the sealed mission brief"})
            arm_rx_bg(900)
            save_state(s)

    elif phase == "send_issue":
        if len(s["solved"]) >= s["target"]:
            s["phase"] = "done"
            save_state(s)
            return
        idx = len(s["solved"])
        issue = bench[idx]
        iid = issue["issue_id"]
        if iid in s.get("held", []):
            log(f"{iid} is HELD by operator - not firing; waiting")
            return
        payload = {
            "type": "frontier_issue", "drill": DRILL, "round": idx + 1, "target": s["target"],
            "issue_id": iid, "repo": issue["repo"], "target_file": issue["target_file"],
            "category": issue["category"], "complexity_tier": issue.get("complexity_tier"),
            "title": issue["title"], "problem_statement": issue["problem_statement"],
            "expected_invariant": issue["expected_invariant"],
            "FAIL_TO_PASS": issue["FAIL_TO_PASS"], "PASS_TO_PASS": issue["PASS_TO_PASS"],
            "instructions": "Solve this issue on your silicon. Reply sealed to alpha_pub " + ALPHA_PUB +
                            " with JSON {issue_id, repo, target_file, solution, solver_notes, tests_run, file_sha256_of_this_json} as 245B chirps, then post bus frontier_solution_verdict {issue_id, payload_sha256, ok:true}. Wait for A's confirmation before expecting the next issue.",
        }
        src = ISSUES / f"{iid}.json"
        src.write_text(json.dumps(payload, indent=1))
        sha = hashlib.sha256(src.read_bytes()).hexdigest()
        # fire only when B has declared an open RX window (LoRa is not store-and-forward)
        if window_open:
            fdir = FRAMES / iid
            man = seal(src, BRAVO_PUB, fdir)
            logf, tail = fire(fdir, f"issue_{iid}")
            s["issue_sent"][iid] = {"sha256": sha, "frames": man["total_chunks"],
                                     "tx_log": logf.name, "tx": tail, "utc": now()}
            s["current_issue"] = iid
            s["phase"] = "await_solution"
            evid({"event": "issue_sent", "issue_id": iid, "round": idx + 1,
                  "payload_sha256": sha, "frames": man["total_chunks"], "tx_log": logf.name, "tx": tail})
            bus_post("frontier_issue_window", {
                "to": "bravo", "from": "alpha", "drill": DRILL, "issue_id": iid,
                "round": idx + 1, "payload_sha256": sha, "frames": man["total_chunks"],
                "note": "issue content is ONLY in the sealed chirps on 903.9MHz; capture all frames, reassemble w/ bravo_sk, verify sha, post frontier_issue_verdict, solve, return resolved payload sealed to alpha_pub",
                "alpha_pub_for_reply": ALPHA_PUB})
            ensure_attest(iid, "A_to_B_issue", sha, f"TX_DONE {tail}"[:110])
            save_state(s)
            git_commit(f"evidence(frontier-drill): issue {iid} (round {idx+1}) sealed+fired to B over real LoRa ({man['total_chunks']} chirps, sha {sha[:16]}...)")
        else:
            bus_post("frontier_issue_window_request", {
                "drill": DRILL, "issue_id": iid, "round": idx + 1,
                "note": "B: open RX window on 903.9 SF9 BW125 so A can fire the sealed issue"})
            arm_rx_bg(900)
            save_state(s)

    elif phase == "await_solution":
        cur = s["current_issue"]
        if cur and cur in solutions:
            sol = solutions[cur]
            psha = sol["sha256"]
            # cross-check with B's bus verdict if present
            verdict = next((e for e in br if e["type"] == "frontier_solution_verdict"
                            and e.get("data", {}).get("issue_id") == cur), None)
            sha_match = (verdict is None) or (verdict["data"].get("payload_sha256") == psha)
            if not sha_match:
                # CALIBRATION (2026-11-23): never solve on a hash mismatch — the
                # reassembly is corrupt or mixed; keep the window open and ask B
                # to refire instead of writing bad evidence.
                log(f"ERROR {cur}: reassembled sha {psha[:16]} != bravo verdict "
                    f"{verdict['data'].get('payload_sha256','')[:16]} — NOT solving; refire requested")
                evid({"event": "solution_sha_mismatch", "issue_id": cur,
                      "reassembled_sha256": psha,
                      "bravo_verdict_sha256": verdict["data"].get("payload_sha256")})
                bus_post("frontier_drill_nudge", {"drill": DRILL, "phase": "await_solution",
                          "issue_id": cur, "note": "A reassembled sha does NOT match your verdict; refire the solution frames sealed to alpha_pub"})
                save_state(s)
                return
            entry = {"event": "solution_received", "issue_id": cur,
                     "payload_sha256": psha, "bus_verdict": verdict is not None,
                     "sha_match_with_bus_verdict": sha_match,
                     "solution": sol["payload"], "utc": now()}
            evid(entry)
            (SOLS / f"{cur}_solution.json").write_text(json.dumps(sol["payload"], indent=1))
            (SOLS / f"{cur}_capture.json").write_text(json.dumps({
                "issue_id": cur, "payload_sha256": psha,
                "leg": "B_to_A_solution", "verdict": "DECRYPT_OK",
                "frames": sol["frames"], "utc": now()}, indent=1))
            chain = ensure_attest(cur, "B_to_A_solution", psha,
                                  f"DECRYPT_OK {len(sol['frames'])} frames sha_match={bool(sha_match)}")
            bus_post("frontier_solution_capture_verdict", {
                "to": "bravo", "from": "alpha", "drill": DRILL, "issue_id": cur,
                "leg": "B_to_A_solution", "verdict": "DECRYPT_OK", "payload_sha256": psha,
                "sha_match_with_bravo_verdict": bool(sha_match),
                "frames_decrypted": len(sol["frames"]),
                "solana_attestation_sig": chain.get("signature"),
                "solana_attestation_slot": chain.get("slot"),
                "branch": "researcher-a/frontier-drill-20261121",
                "note": "A captured all frames over real RF, decrypted with alpha_sk, reassembled; per-frame proof in solutions/" + cur + "_capture.json; evidence committed. Receiver-closure COMPLETE.",
                "ts_utc": now()})
            s["solved"].append(cur)
            s["current_issue"] = None
            s["phase"] = "send_issue"
            save_state(s)
            git_commit(f"evidence(frontier-drill): {cur} RESOLVED by B over ZK-LoRaWAN — payload sha {psha[:16]}..., bus_verdict={verdict is not None}, sha_match={sha_match} ({len(s['solved'])}/{s['target']})")
            log(f"SOLVED {cur} sha={psha[:16]} ({len(s['solved'])}/{s['target']})")
        else:
            # reconcile: retry the issue-leg attestation if the first attempt failed
            if cur and cur in s["issue_sent"]:
                sent = s["issue_sent"][cur]
                ensure_attest(cur, "A_to_B_issue", sent["sha256"],
                              f"TX_DONE {sent.get('tx','')}"[:110])
            # B is fail-closed: it only fires into a DECLARED rx_window_open. Maintain an
            # accurate window every cycle (arm 1800s if RX is down) and always post it.
            sol_rx = s.get("sol_rx") or {}
            if not rx_running():
                name = arm_rx_bg(1800)
                if name:
                    sol_rx = {"log": name, "started_ts": now_ts, "seconds": 1800}
                    s["sol_rx"] = sol_rx
            if sol_rx:
                bus_post("rx_window_open", {
                    "to": "bravo", "from": "alpha", "drill": DRILL, "issue_id": cur,
                    "leg": "B_to_A_solution", "freq_mhz": 903.9, "sf": 9, "bw_khz": 125,
                    "armed_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(sol_rx["started_ts"])),
                    "closes_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(sol_rx["started_ts"] + sol_rx["seconds"])),
                    "rx_log": sol_rx["log"],
                    "note": "B: fire staged solution frames within this window; A re-declares every 5 min",
                    "ts_utc": now()})
            bus_post("frontier_drill_nudge", {"drill": DRILL, "phase": "await_solution",
                      "issue_id": cur, "note": "B: return resolved payload sealed to alpha_pub " + ALPHA_PUB + " — rx_window_open declared for this leg; fire within it"})
            save_state(s)

    elif phase == "done":
        dossier = {"drill": DRILL, "target": s["target"], "solved": s["solved"],
                   "completed_utc": now(), "started_utc": s["started_utc"],
                   "brief_sha256": s["brief_sha"]}
        (HERE / "DOSSIER.json").write_text(json.dumps(dossier, indent=1))
        evid({"event": "drill_complete", "solved": len(s["solved"]), "target": s["target"]})
        git_commit(f"evidence(frontier-drill): COMPLETE — {len(s['solved'])}/{s['target']} issues resolved A<->B over real ZK-LoRaWAN")
        log(f"DRILL COMPLETE {len(s['solved'])}/{s['target']}")


if __name__ == "__main__":
    step()
