#!/bin/bash
set -u
EV=/home/researcher-bravo/fleet/evidence/frontier_drill_20261121/issue_0001
FRAMES="$EV/solution_frames"
HAL=/home/researcher-bravo/sx1302_hal/libloragw
TXBIN=/home/researcher-bravo/fleet/evidence/essay_drill_20261118/chirp_frames_tx
TXLOG="$EV/b2a_solution_tx.log"
RECLOG="$EV/b2a_solution_recovery.log"
CLOSE_EPOCH=$(date -u -d '2026-11-22T07:44:52Z' +%s)
NOW_EPOCH=$(date -u +%s)
if [ "$NOW_EPOCH" -ge "$CLOSE_EPOCH" ]; then echo 'ABORT: declared Alpha RX window closed'; exit 20; fi
if [ -e "$EV/fired_B4893_A1521" ]; then echo 'ABORT: window already fired'; exit 21; fi
python3 /home/researcher-bravo/fleet/evidence/essay_drill_20261118/staged_sha_gate.py "$FRAMES" "$FRAMES/manifest.json" || exit 10
systemctl --user stop fleet-rx-standby.service || true
PIDS=$(pgrep -x test_loragw_hal 2>/dev/null || true)
if [ -n "$PIDS" ]; then for p in $PIDS; do kill -9 "$p" 2>/dev/null || true; done; sleep 2; fi
if pgrep -x test_loragw_hal >/dev/null 2>&1; then systemctl --user start fleet-rx-standby.service; echo 'ABORT: SPI still held'; exit 11; fi
cd "$HAL" || { systemctl --user start fleet-rx-standby.service; exit 12; }
sudo timeout 900 "$TXBIN" -d "$FRAMES" -f 903.9 -s 9 -b 125 -p 14 -n 1 -g 3 -c /dev/spidev0.0 2>&1 | tee "$TXLOG"
TX_RC=${PIPESTATUS[0]}
cd /home/researcher-bravo/fleet-repos/zk-lora-milestone-1/tools || true
RECOVERY_LOG="$RECLOG" bash ./lora_chirp_recovery.sh > "$EV/b2a_solution_recovery_console.log" 2>&1
RECOVERY_RC=$?
systemctl --user start fleet-rx-standby.service
sleep 3
export FLEET_FAST_TOKEN=$(grep -m1 '^FLEET_FAST_TOKEN=' ~/.hermes/.env | cut -d= -f2- | tr -d '"'"'"' ')
python3 - "$TX_RC" "$RECOVERY_RC" <<'PY'
import json,os,sys,hashlib,datetime
from pathlib import Path
sys.path.insert(0,'/home/researcher-bravo/fleet-repos/fleet/fast-channel')
from post_event import post
ev=Path('/home/researcher-bravo/fleet/evidence/frontier_drill_20261121/issue_0001')
txrc,recrc=map(int,sys.argv[1:3]); log=(ev/'b2a_solution_tx.log').read_text(errors='replace'); man=json.load(open(ev/'solution_frames/manifest.json'))
done=log.count('TX_DONE'); complete='CHIRP_TX_COMPLETE=YES' in log
payload=(ev/'FRONTIER-GH-0001-solution.json').read_bytes(); sha=hashlib.sha256(payload).hexdigest()
data={'to':'alpha','from':'bravo','type':'frontier_solution_verdict','drill':'frontier_drill_20261121','issue_id':'FRONTIER-GH-0001','ok':bool(txrc==0 and recrc==0 and complete and done==35),'payload_sha256':sha,'payload_bytes':len(payload),'total_chunks':35,'frames_fired':35,'tx_done_markers':done,'chirp_tx_complete':complete,'tx_exit_code':txrc,'recovery_exit_code':recrc,'rf':'903.9MHz SF9 BW125 14dBm','gap_s':3,'reps':1,'alpha_rx_window':{'b_seq':4893,'a_seq':1521,'closes_at_utc':'2026-11-22T07:44:52Z'},'tx_log':str(ev/'b2a_solution_tx.log'),'frame_sha256':[f['frame_sha256'] for f in man['frames']],'note':'Sealed resolved payload fired to alpha_pub. ok=true is Bravo TX+staging verdict only; Alpha DECRYPT_OK+SHA readback remains required before issue completion/next issue.'}
out={}
for plane,url in [('B','http://127.0.0.1:8643'),('A','http://192.168.1.219:8643')]: out[plane]=post(url,'frontier_solution_verdict',data)
(ev/'frontier_solution_verdict_post.json').write_text(json.dumps({'data':data,'post':out},indent=1))
print(json.dumps(out,indent=1))
if not data['ok']: raise SystemExit(30)
PY
POST_RC=$?
if [ "$TX_RC" -eq 0 ]; then touch "$EV/fired_B4893_A1521"; fi
echo "FIRE_DONE tx_rc=$TX_RC recovery_rc=$RECOVERY_RC post_rc=$POST_RC"
exit $(( TX_RC != 0 ? TX_RC : POST_RC ))
