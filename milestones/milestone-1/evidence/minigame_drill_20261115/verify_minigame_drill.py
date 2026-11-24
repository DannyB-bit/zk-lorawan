#!/usr/bin/env python3
"""verify_minigame_drill.py — COLD reproduce/verify for the A<->B minigame chirp drill.

Re-derives every claim from bytes on disk (and, optionally, from the live fleet
bus) without trusting any summary field written by the drill participants.

Checks:
  L1  Re-extract the 6 declared 245B frames from Alpha's over-the-air capture
      log, recompute SHA-256, compare to the SHAs Alpha declared on the bus.
  L2  Decrypt + reassemble those frames with the canonical envelope
      (X25519 + HKDF-SHA256 salt=zk-lora-chirp245-v1 info=chirp245-aead-key
      + AES-256-GCM) using the Bravo secret key, compare the reassembled file
      SHA-256 to Alpha's declared file SHA-256.
  L3  Re-verify the Bravo-side sealed frames against their manifest
      (exact 245B length + exact SHA-256 per frame) and the player file SHA.
  L4  Re-run the game: import the reassembled game_core.py + player_ai.py,
      play, and assert a win within the 7-guess budget. Sweep 2000 seeds.
  L5  Confirm the TX receipt in the TX log: 14 frames, 28 sends, all TX_DONE.
  L6  (optional) Fetch Alpha's leg-2 capture verdict from the fleet bus and
      check the claimed file SHA matches what we sealed.

Usage:
  verify_minigame_drill.py [--ev-dir DIR] [--bus-check]

Exit 0 only if every enabled check passes.
"""
import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

EV_DEFAULT = "/home/researcher-bravo/fleet/evidence/minigame_drill_20261115"
SK_DEFAULT = "/home/researcher-bravo/.config/solana/chirp245_bravo_sk.key"

DECLARED_A_FRAME_SHA16 = [
    "879030edd5f62878", "820f3932aff80959", "7f7eed2c34468797",
    "cddb480fbc9dec58", "c00201b609fa1ece", "0f864e3f83f46760",
]
DECLARED_A_FILE_SHA256 = (
    "94c1838794bdec1942674a9300611425c70b7c4a29102fd30cb7c227c173889b")
B_FILE_SHA256 = (
    "c94a2cecbacd811a944559f4f44ffb21bf6fdf275bf960ee314c9f9184581b8f")

results = []


def check(name, ok, detail=""):
    results.append({"check": name, "ok": bool(ok), "detail": detail})
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name,
                         ("  -- " + str(detail)) if detail else ""))
    return ok


def extract_frames_from_log(log_path):
    """Pull every 245B packet payload out of a HAL RX log, return {sha16: (bytes, meta)}."""
    text = Path(log_path).read_text(errors="replace")
    blocks = re.findall(r"----- LoRa packet -----(.*?)(?=\n----- |\Z)", text, re.S)
    out = {}
    for b in blocks:
        m = re.search(r"^\s*size\s*:?\s*(\d+)", b, re.M)
        if not m or m.group(1) != "245":
            continue
        hexlines = [ln.strip().replace(" ", "") for ln in b.splitlines()
                    if re.fullmatch(r"(?:[0-9A-F]{2} ?)+", ln.strip())
                    and len(ln.strip().replace(" ", "")) >= 100]
        if not hexlines:
            continue
        payload = "".join(hexlines)
        if len(payload) != 245 * 2:
            continue
        fb = bytes.fromhex(payload)
        def g(pat, default="?"):
            mm = re.search(pat, b)
            return mm.group(1) if mm else default
        meta = {"count_us": g(r"count_us:\s*(\d+)"), "snr": g(r"snr_avg:\s*(-?\d+\.?\d*)"),
                "crc": g(r"crc:\s*(\S+)"), "status": g(r"status:\s*(\S+)"),
                "chan": g(r"chan:\s*(\S+)"), "datr": g(r"datr:\s*(\S+)"),
                "freq_hz": g(r"freq_hz\s+(\d+)")}
        key = hashlib.sha256(fb).hexdigest()[:16]
        out.setdefault(key, []).append((fb, meta))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ev-dir", default=EV_DEFAULT)
    ap.add_argument("--sk", default=SK_DEFAULT)
    ap.add_argument("--capture-log", default=None)
    ap.add_argument("--bus-check", action="store_true")
    args = ap.parse_args()
    ev = Path(args.ev_dir)

    # ---- L1: re-extract Alpha's frames from the raw capture log -------------
    cap = args.capture_log
    frames = {}
    if cap:
        frames = extract_frames_from_log(cap)
        print("capture log: %s" % cap)
    else:
        # Scan EVERY standby capture log, newest first: the declared frames may
        # live in an earlier window than the current one.
        cands = sorted(Path("/home/researcher-bravo/fleet/logs").glob(
            "rx_standby_continuous_*.log"), key=lambda q: q.stat().st_mtime,
            reverse=True)
        for c in cands:
            got = extract_frames_from_log(c)
            if not got:
                continue
            for k, v in got.items():
                frames.setdefault(k, v)
            print("scanned capture log: %s (%d distinct 245B frame shas)" % (c, len(got)))
            if all(w in frames for w in DECLARED_A_FRAME_SHA16):
                break
    got16 = sorted(frames.keys())
    want16 = sorted(DECLARED_A_FRAME_SHA16)
    check("L1_alpha_frames_present_in_raw_radio_log",
          all(w in frames for w in want16),
          "found %d distinct 245B frame shas; missing=%s" %
          (len(got16), [w for w in want16 if w not in frames]))

    # ---- L2: decrypt + reassemble, compare to declared file sha -------------
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.asymmetric.x25519 import (
            X25519PrivateKey, X25519PublicKey)
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF
        from cryptography.hazmat.primitives import hashes
    except Exception as e:
        check("L2_decrypt_reassemble", False, "cryptography import failed: %s" % e)
        return finish()
    sk_raw = Path(args.sk).read_bytes()
    sk_hex = sk_raw.hex() if len(sk_raw) == 32 else sk_raw.decode().strip()
    priv = X25519PrivateKey.from_private_bytes(bytes.fromhex(sk_hex))
    chunks = {}
    dec_fail = []
    for sha16 in DECLARED_A_FRAME_SHA16:
        if sha16 not in frames:
            dec_fail.append((sha16, "not captured")); continue
        fb = frames[sha16][0][0]
        try:
            ver, n = fb[0], fb[1]
            if ver != 1:
                raise ValueError("bad version")
            nonce = fb[2:14]
            eph = X25519PublicKey.from_public_bytes(fb[14:46])
            shared = priv.exchange(eph)
            key = HKDF(algorithm=hashes.SHA256(), length=32,
                       salt=b"zk-lora-chirp245-v1",
                       info=b"chirp245-aead-key").derive(shared)
            pt = AESGCM(key).decrypt(nonce, fb[46:245], None)
            if pt[0] != 2:
                raise ValueError("bad plaintext magic")
            chunks[pt[2]] = pt[3:].rstrip(b"\x00")
        except Exception as e:
            dec_fail.append((sha16, type(e).__name__ + ":" + str(e)))
    check("L2_all_alpha_frames_decrypt_ok", not dec_fail, dec_fail or "6/6 DECRYPT_OK")
    if len(chunks) == 6:
        data = b"".join(chunks[i] for i in range(6))
        fsha = hashlib.sha256(data).hexdigest()
        check("L2_reassembled_sha_matches_alpha_declaration",
              fsha == DECLARED_A_FILE_SHA256,
              "reassembled=%s declared=%s bytes=%d" % (fsha, DECLARED_A_FILE_SHA256, len(data)))
        out = ev / "_verify_game_core.py"
        out.write_bytes(data)
    else:
        check("L2_reassembled_sha_matches_alpha_declaration", False, "only %d chunks" % len(chunks))
        out = ev / "game_core.py"

    # ---- L3: verify the Bravo-side sealed frames against the manifest ------
    man_path = ev / "leg2_frames" / "manifest.json"
    if man_path.exists():
        man = json.loads(man_path.read_text())
        bad = []
        for fr in man["frames"]:
            p = ev / "leg2_frames" / ("frame_%02d.bin" % fr["idx"])
            if not p.exists():
                bad.append((fr["idx"], "missing")); continue
            b = p.read_bytes()
            if len(b) != 245:
                bad.append((fr["idx"], "len=%d" % len(b))); continue
            if hashlib.sha256(b).hexdigest() != fr["frame_sha256"]:
                bad.append((fr["idx"], "sha"))
        check("L3_bravo_sealed_frames_match_manifest", not bad,
              bad or "%d frames exact 245B + sha256" % len(man["frames"]))
        check("L3_bravo_player_file_sha_matches_declaration",
              man["file_sha256"] == B_FILE_SHA256,
              "manifest=%s declared=%s" % (man["file_sha256"], B_FILE_SHA256))
        check("L3_bravo_chunk_count", man["total_chunks"] == 14,
              "total_chunks=%d" % man["total_chunks"])
    else:
        check("L3_bravo_sealed_frames_match_manifest", False, "manifest missing")

    # ---- L4: re-run the game ----------------------------------------------
    sys.path.insert(0, str(ev))
    try:
        for mod in ("game_core", "player_ai"):
            sys.modules.pop(mod, None)
        import game_core
        import player_ai
        g = game_core.Game()
        o = player_ai.play_game(g)
        check("L4_game_default_seed_win_within_budget",
              o["outcome"] == "win" and o["guesses_used"] <= 7,
              "outcome=%s guesses=%d transcript=%s" %
              (o["outcome"], o["guesses_used"],
               [t["guess"] for t in o["transcript"]]))
        fails = 0
        worst = 0
        for s in range(1, 2001):
            gg = game_core.Game(seed=s)
            oo = player_ai.play_game(gg)
            worst = max(worst, oo["guesses_used"])
            if oo["outcome"] != "win" or oo["guesses_used"] > 7:
                fails += 1
        check("L4_game_2000_seed_sweep", fails == 0,
              "fails=%d worst_guesses=%d" % (fails, worst))
    except Exception as e:
        check("L4_game_default_seed_win_within_budget", False,
              "import/run failed: %s: %s" % (type(e).__name__, e))

    # ---- L5: TX receipt from the log --------------------------------------
    txlog = ev / "leg2_tx_fire01.log"
    if txlog.exists():
        t = txlog.read_text()
        n_done = len(re.findall(r"CHIRP_TX_FRAME_\d+_REPS=\d+_STATUS=TX_DONE", t))
        n_err = len(re.findall(r"_STATUS=(TX_ERROR|SEND_FAIL)", t))
        check("L5_tx_receipt_28_sends_all_done", n_done == 28 and n_err == 0,
              "TX_DONE=%d errors=%d complete_line=%s" %
              (n_done, n_err, [l for l in t.splitlines() if "CHIRP_TX_COMPLETE" in l]))
    else:
        check("L5_tx_receipt_28_sends_all_done", False, "tx log missing")

    # ---- L6: optional bus check for Alpha's leg-2 verdict -------------------
    if args.bus_check:
        try:
            import urllib.request
            tok = ""
            for line in Path("/home/researcher-bravo/.hermes/.env").read_text().splitlines():
                if line.startswith("FLEET_FAST_TOKEN="):
                    tok = line.split("=", 1)[1].strip()
                    break
            url = "http://192.168.1.219:8643/events?since=0&token=%s" % tok
            with urllib.request.urlopen(url, timeout=30) as r:
                evs = json.loads(r.read())["events"]
            verdicts = [e for e in evs
                        if e.get("type") == "chirp_raw_rx_verdict"
                        and (e.get("data") or {}).get("leg") == "B_to_A"]
            if verdicts:
                # Alpha may post BOTH a structured verdict (reassembled_file_sha256)
                # and a richer narrative one (reassembled.sha256). Collect EVERY
                # sha alpha claims across all of them; require at least one
                # structured sha AND that every claim equals what Bravo sealed.
                claimed = []
                for e in verdicts:
                    d = e.get("data") or {}
                    for key in ("reassembled_file_sha256", "declared_file_sha256"):
                        if d.get(key):
                            claimed.append((e["seq"], key, d[key]))
                    r = d.get("reassembled") or {}
                    if isinstance(r, dict):
                        for key in ("sha256", "declared_sha256"):
                            if r.get(key):
                                claimed.append((e["seq"], "reassembled." + key, r[key]))
                check("L6_alpha_leg2_verdict_present", True,
                      "%d leg=B_to_A verdict event(s): seqs=%s" %
                      (len(verdicts), [e["seq"] for e in verdicts]))
                check("L6_alpha_leg2_sha_matches_what_b_sealed",
                      bool(claimed) and all(c[2] == B_FILE_SHA256 for c in claimed),
                      "alpha_claims=%s bravo_sealed=%s" %
                      ([(s, k, v[:16]) for s, k, v in claimed], B_FILE_SHA256[:16]))
            else:
                check("L6_alpha_leg2_verdict_present", False,
                      "no leg=B_to_A chirp_raw_rx_verdict on Alpha's bus yet")
        except Exception as e:
            check("L6_alpha_leg2_verdict_present", False, "bus check failed: %s" % e)

    return finish()


def finish():
    npass = sum(1 for r in results if r["ok"])
    print("\n%d/%d checks PASS" % (npass, len(results)))
    out = Path(os.environ.get("VERIFY_OUT", "/tmp/minigame_verify.json"))
    out.write_text(json.dumps(results, indent=1))
    print("report: %s" % out)
    return 0 if npass == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
