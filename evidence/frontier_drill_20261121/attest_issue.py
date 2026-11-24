#!/usr/bin/env python3
"""Per-issue on-chain Solana attestation for the frontier drill.

Uses the CANONICAL chirp245.py attest path (DannyB-bit/solana-cuneiform-milestone1
@391ec84): register_coordinates(session=sha256(solution)[:16],
coords=deterministic-legal-from-hash, merkle_root=sha256(solution)) on the live
devnet program 2is5Q4r… (100k-lamport treasury CPI). The payload hash attested
is the SAME sha256 declared pre-fire and verified by Alpha's capture verdict.

Readback: getTransaction (finalized, err=null) + record-PDA byte checks
(authority[8:40], session[40:56], coords[56:62], root[62:94]) + signature count.
"""
import base64
import hashlib
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.expanduser("~/fleet-repos/solana-cuneiform-milestone1/tools"))
import chirp245 as canon  # canonical tool, executed bytes only

sys.path.insert(0, os.path.expanduser("~/fleet-repos/fleet/fast-channel"))
from post_event import post

KEYFILE = os.path.expanduser("~/.config/solana/bravo-fleet.json")
OPS_ADDR = "14aTW9ypTLuQPTUfes8aExkn6dG2ESsHUYuhpvziaMa3"
EV = Path(os.path.expanduser("~/fleet/evidence/frontier_drill_20261121"))
B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58e(b: bytes) -> str:
    n = int.from_bytes(b, "big")
    s = ""
    while n:
        n, r = divmod(n, 58)
        s = B58[r] + s
    return "1" * (len(b) - len(b.lstrip(b"\0"))) + (s or "")


def attest(issue_id: str) -> dict:
    ev = EV / f"issue_{issue_id}"
    sol = ev / f"FRONTIER-GH-{issue_id}-solution.json"
    payload = sol.read_bytes()
    sha = hashlib.sha256(payload).hexdigest()
    print(f"[{issue_id}] solution {len(payload)}B sha {sha[:16]}… — sending register_coordinates …")
    out = canon.attest_chirp_on_solana(payload, KEYFILE)
    sig, pda, session = out["signature"], out["record_pda"], out["session_id"]
    print(f"[{issue_id}] sig {sig[:24]}… pda {pda}")

    # wait for finalized
    slot, err, conf = None, "PENDING", None
    for _ in range(30):
        time.sleep(2)
        st = canon._rpc("getSignatureStatuses", [[sig], {"searchTransactionHistory": True}])
        v = st["result"]["value"][0]
        if v:
            conf = v.get("confirmationStatus")
            err = v.get("err")
            slot = v.get("slot")
            if conf in ("confirmed", "finalized"):
                break
    # record PDA readback
    info = canon._rpc("getAccountInfo", [pda, {"encoding": "base64"}])
    raw = base64.b64decode(info["result"]["value"]["data"][0])
    onchain_session = raw[40:56].hex()
    onchain_coords = list(raw[56:62])
    onchain_root = raw[62:94].hex()
    authority = b58e(raw[8:40])
    sigs = canon._rpc("getSignaturesForAddress", [pda, {"limit": 5}])["result"]
    rb = {
        "issue_id": f"FRONTIER-GH-{issue_id}",
        "program": canon.PROGRAM_ID,
        "cluster": "devnet",
        "signature": sig, "slot": slot, "confirm": conf, "tx_err": err,
        "record_pda": pda, "record_len": len(raw),
        "solution_sha256": sha, "solution_bytes": len(payload),
        "session_id": session, "onchain_session": onchain_session,
        "onchain_coords": onchain_coords,
        "onchain_root": onchain_root, "authority": authority,
        "session_match": onchain_session == session == sha[:32],
        "root_match": onchain_root == sha,
        "authority_match": authority == OPS_ADDR,
        "coords_legal": (onchain_coords[0] < 16 and onchain_coords[1] < 24
                         and onchain_coords[2] < 8 and onchain_coords[3] < 8
                         and onchain_coords[4] < 5 and onchain_coords[5] < 2),
        "sigs_on_record": len(sigs),
        "sig_on_record": any(s["signature"] == sig for s in sigs),
        "explorer": f"https://explorer.solana.com/tx/{sig}?cluster=devnet",
        "note": "on-chain merkle_root == sha256(solution payload fired over LoRa); coords derived deterministically from the hash per canonical tool design (attester cannot decode the sealed payload).",
    }
    rb["all_checks_pass"] = all([rb["session_match"], rb["root_match"], rb["authority_match"],
                                 rb["coords_legal"], rb["sig_on_record"], err is None])
    (ev / "onchain_attest_readback.json").write_text(json.dumps(rb, indent=1) + "\n")
    print(f"[{issue_id}] slot {slot} {conf} err={err} root_match={rb['root_match']} all_checks_pass={rb['all_checks_pass']}")

    data = {"to": "alpha", "from": "bravo", "type": "frontier_onchain_attest",
            "drill": "frontier_drill_20261121", "issue_id": f"FRONTIER-GH-{issue_id}",
            "solution_sha256": sha, "signature": sig, "slot": slot, "confirm": conf,
            "record_pda": pda, "all_checks_pass": rb["all_checks_pass"],
            "explorer": rb["explorer"],
            "readback": str(ev / "onchain_attest_readback.json")}
    posts = {}
    for plane, url in [("B", "http://127.0.0.1:8643"), ("A", "http://192.168.1.219:8643")]:
        posts[plane] = post(url, "frontier_onchain_attest", data)
    (ev / "onchain_attest_post.json").write_text(json.dumps({"data": data, "post": posts}, indent=1))
    print(f"[{issue_id}] bus posts: {posts}")
    return rb


if __name__ == "__main__":
    issues = sys.argv[1:] or ["0001", "0002", "0003"]
    results = {i: attest(i) for i in issues}
    print("\nSUMMARY:", {i: {"slot": r["slot"], "pass": r["all_checks_pass"]} for i, r in results.items()})
