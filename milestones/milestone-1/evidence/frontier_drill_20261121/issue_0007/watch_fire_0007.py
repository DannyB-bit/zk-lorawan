#!/usr/bin/env python3
import json, os, subprocess, time, urllib.request, datetime
TOKEN=os.environ["FLEET_FAST_TOKEN"]
URL="http://127.0.0.1:8643"
FIRE="/home/researcher-bravo/fleet/evidence/frontier_drill_20261121/issue_0007/fire_solution_0007.sh"
seen=0
while True:
    try:
        evs=json.loads(urllib.request.urlopen(f"{URL}/events?since={seen}&token={TOKEN}",timeout=8).read()).get("events",[])
        for e in evs: seen=max(seen,e["seq"])
        candidates=[]
        for e in evs:
            d=e.get("data",{})
            if e.get("type")=="rx_window_open" and d.get("from")=="alpha" and d.get("issue_id")=="FRONTIER-GH-0007" and d.get("leg")=="B_to_A_solution":
                close=d.get("closes_at_utc") or d.get("closes_utc") or d.get("window_close_utc") or d.get("close_utc")
                now=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                if close and close>now: candidates.append((e["seq"],close))
        if candidates:
            seq,close=candidates[-1]
            print(f"WATCH_FIRE issue=0007 window=B{seq} close={close}",flush=True)
            p=subprocess.run(["bash",FIRE])
            print(f"WATCH_FIRE_EXIT={p.returncode}",flush=True)
            raise SystemExit(p.returncode)
    except Exception as e:
        print(f"WATCH_POLL_ERROR={type(e).__name__}:{e}",flush=True)
    time.sleep(2)
