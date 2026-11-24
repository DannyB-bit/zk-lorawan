#!/bin/bash
# FRONTIER-GH-0017 B->A solution fire — fail-closed, self-discovering Alpha window.
# Adapted from the proven issue_0002 fire_solution.sh (19/19 TX_DONE 2026-11-22).
set -u
EV=/home/researcher-bravo/fleet/evidence/frontier_drill_20261121/issue_0017
FRAMES="$EV/solution_frames"
HAL=/home/researcher-bravo/sx1302_hal/libloragw
TXBIN=/home/researcher-bravo/fleet/evidence/essay_drill_20261118/chirp_frames_tx
TXLOG=""
RECLOG=""
CONLOG=""
POSTJSON=""
export FLEET_FAST_TOKEN=$(grep -m1 '^FLEET_FAST_TOKEN=' ~/.hermes/.env | cut -d= -f2- | tr -d '"'"'"' ')

# --- discover Alpha's declared RX window for this issue/leg (fail-closed) ---
eval $(python3 - <<'PY'
import json, os, urllib.request, datetime
tok = os.environ["FLEET_FAST_TOKEN"]
req = urllib.request.Request(f"http://127.0.0.1:8643/events?token={tok}")
evs = json.loads(urllib.request.urlopen(req, timeout=8).read()).get("events", [])
w = [e for e in evs if e.get("type") == "rx_window_open"
     and e.get("data", {}).get("issue_id") == "FRONTIER-GH-0017"
     and e.get("data", {}).get("leg") == "B_to_A_solution"
     and e.get("data", {}).get("from") == "alpha"]
if not w:
    print("DISCOVER_OK=0"); raise SystemExit(0)
e = w[-1]; d = e["data"]
close = d.get("closes_at_utc") or d.get("closes_utc") or d.get("window_close_utc")
now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
print(f"DISCOVER_OK=1 WIN_BSEQ={e['seq']} WIN_ASEQ={d.get('a_seq','?')} WIN_CLOSE='{close}' WIN_STILL_OPEN={1 if close and close > now else 0}")
PY
)
if [ "${DISCOVER_OK:-0}" != "1" ]; then echo 'ABORT: no Alpha rx_window_open for FRONTIER-GH-0017 B_to_A_solution'; exit 36; fi
if [ "${WIN_STILL_OPEN:-0}" != "1" ]; then echo "ABORT: Alpha window closed at ${WIN_CLOSE}"; exit 36; fi
GUARD="$EV/fired_0017_B${WIN_BSEQ}"
if [ -e "$GUARD" ]; then echo 'ABORT: this window already fired'; exit 21; fi
TXLOG="$EV/b2a_solution_tx_B${WIN_BSEQ}.log"
RECLOG="$EV/b2a_solution_recovery_B${WIN_BSEQ}.log"
CONLOG="$EV/b2a_solution_recovery_B${WIN_BSEQ}_console.log"
POSTJSON="$EV/frontier_solution_verdict_B${WIN_BSEQ}_post.json"
CLOSE_EPOCH=$(date -u -d "$WIN_CLOSE" +%s); NOW_EPOCH=$(date -u +%s)
if [ "$NOW_EPOCH" -ge "$CLOSE_EPOCH" ]; then echo 'ABORT: declared Alpha RX window closed'; exit 36; fi
if [ $((CLOSE_EPOCH-NOW_EPOCH)) -lt 900 ]; then echo 'ABORT: insufficient time for 69-frame airtime+recovery'; exit 36; fi

python3 /home/researcher-bravo/fleet/evidence/essay_drill_20261118/staged_sha_gate.py "$FRAMES" "$FRAMES/manifest.json" || exit 10
systemctl --user stop fleet-rx-standby.service || true
PIDS=$(pgrep -x test_loragw_hal 2>/dev/null || true)
if [ -n "$PIDS" ]; then for p in $PIDS; do kill -9 "$p" 2>/dev/null || true; done; sleep 2; fi
if pgrep -x test_loragw_hal >/dev/null 2>&1; then systemctl --user start fleet-rx-standby.service; echo 'ABORT: SPI still held'; exit 11; fi
cd "$HAL" || { systemctl --user start fleet-rx-standby.service; exit 12; }
sudo timeout 1200 "$TXBIN" -d "$FRAMES" -f 903.9 -s 9 -b 125 -p 14 -n 1 -g 3 -c /dev/spidev0.0 2>&1 | tee "$TXLOG"
TX_RC=${PIPESTATUS[0]}
cd /home/researcher-bravo/fleet-repos/zk-lora-milestone-1/tools || true
RECOVERY_LOG="$RECLOG" bash ./lora_chirp_recovery.sh > "$CONLOG" 2>&1
RECOVERY_RC=$?
systemctl --user start fleet-rx-standby.service
sleep 3
python3 - "$TX_RC" "$RECOVERY_RC" "$WIN_BSEQ" "$WIN_ASEQ" "$WIN_CLOSE" "$TXLOG" "$POSTJSON" <<'PY'
import json,os,sys,hashlib
from pathlib import Path
sys.path.insert(0,'/home/researcher-bravo/fleet-repos/fleet/fast-channel')
from post_event import post
ev=Path('/home/researcher-bravo/fleet/evidence/frontier_drill_20261121/issue_0017')
txrc,recrc=map(int,sys.argv[1:3]); winb,wina,winclose=sys.argv[3],sys.argv[4],sys.argv[5]
txlog=Path(sys.argv[6]); postjson=Path(sys.argv[7])
log=txlog.read_text(errors='replace'); man=json.load(open(ev/'solution_frames/manifest.json'))
done=log.count('TX_DONE'); complete='CHIRP_TX_COMPLETE=YES' in log
payload=(ev/'FRONTIER-GH-0017-solution.json').read_bytes(); sha=hashlib.sha256(payload).hexdigest()
data={'to':'alpha','from':'bravo','type':'frontier_solution_verdict','drill':'frontier_drill_20261121','issue_id':'FRONTIER-GH-0017','ok':bool(txrc==0 and recrc==0 and complete and done==69),'payload_sha256':sha,'payload_bytes':len(payload),'total_chunks':69,'frames_fired':69,'tx_done_markers':done,'chirp_tx_complete':complete,'tx_exit_code':txrc,'recovery_exit_code':recrc,'rf':'903.9MHz SF9 BW125 14dBm','gap_s':3,'reps':1,'alpha_rx_window':{'b_seq':int(winb),'a_seq':wina,'closes_at_utc':winclose},'tx_log':str(txlog),'frame_sha256':[f['frame_sha256'] for f in man['frames']],'note':'Sealed resolved payload fired to alpha_pub. ok=true is Bravo TX+staging verdict only; Alpha DECRYPT_OK+SHA readback remains required before issue completion/next issue.'}
out={}
for plane,url in [('B','http://127.0.0.1:8643'),('A','http://192.168.1.219:8643')]: out[plane]=post(url,'frontier_solution_verdict',data)
postjson.write_text(json.dumps({'data':data,'post':out},indent=1))
print(json.dumps(out,indent=1))
if not data['ok']: raise SystemExit(30)
PY
POST_RC=$?
if [ "$TX_RC" -eq 0 ]; then touch "$GUARD"; fi
echo "FIRE_DONE tx_rc=$TX_RC recovery_rc=$RECOVERY_RC post_rc=$POST_RC window=B${WIN_BSEQ}"
exit $(( TX_RC != 0 ? TX_RC : POST_RC ))
