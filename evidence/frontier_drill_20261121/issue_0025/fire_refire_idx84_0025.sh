#!/bin/bash
# FRONTIER-GH-0025: refire ONLY missing chunk 84 into a fresh declared Alpha RX window.
set -euo pipefail
EV=/home/researcher-bravo/fleet/evidence/frontier_drill_20261121/issue_0025
FRAMES="$EV/solution_refire_idx84"
HAL=/home/researcher-bravo/sx1302_hal/libloragw
TXBIN=/home/researcher-bravo/fleet/evidence/essay_drill_20261118/chirp_frames_tx
export FLEET_FAST_TOKEN=$(grep -m1 '^FLEET_FAST_TOKEN=' ~/.hermes/.env | cut -d= -f2- | tr -d '"'"'"' ')
source /home/researcher-bravo/fleet/scripts/frontier_rf_adr.env
[ "$FRONTIER_POW_DBM" -le 20 ] || { echo 'ABORT: power cap'; exit 40; }
[ "$FRONTIER_SF" = 7 ] || { echo 'ABORT: this ADR refire is pinned to SF7'; exit 40; }
# Discover a live Alpha window and bind the one frame to Alpha's corrected verdict.
eval $(python3 - <<'PY'
import json,os,urllib.request,datetime,hashlib
from pathlib import Path
tok=os.environ['FLEET_FAST_TOKEN']
ev=Path('/home/researcher-bravo/fleet/evidence/frontier_drill_20261121/issue_0025')
evs=json.load(urllib.request.urlopen('http://127.0.0.1:8643/events?since=0&token='+tok,timeout=8))['events']
c=[e for e in evs if e.get('seq')==5989 and e.get('type')=='frontier_solution_capture_verdict']
assert len(c)==1
requested_close=c[0]['data']['alpha_rx_window']['closes_at_utc']
# B5989 explicitly authorizes this refire into Alpha's currently open B_to_A_solution
# window even though that window's primary issue_id is 0026; bind to its exact close.
w=[e for e in evs if e.get('type')=='rx_window_open' and e.get('data',{}).get('leg')=='B_to_A_solution' and e.get('data',{}).get('from')=='alpha' and (e.get('data',{}).get('closes_at_utc') or e.get('data',{}).get('closes_utc') or e.get('data',{}).get('window_close_utc') or e.get('data',{}).get('close_utc'))==requested_close]
expected=c[0]['data']['actual_capture']['missing_frame_sha256']
actual=hashlib.sha256((ev/'solution_refire_idx84/frame_84.bin').read_bytes()).hexdigest()
assert actual==expected and c[0]['data']['actual_capture']['missing_chunk_idx']==[84]
if not w:
 print('DISCOVER_OK=0'); raise SystemExit(0)
e=w[-1]; d=e['data']; close=d.get('closes_at_utc') or d.get('closes_utc') or d.get('window_close_utc') or d.get('close_utc')
now=datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
print(f"DISCOVER_OK=1 WIN_BSEQ={e['seq']} WIN_ASEQ={d.get('a_seq','?')} WIN_CLOSE='{close}' WIN_STILL_OPEN={1 if close and close>now else 0}")
PY
)
[ "${DISCOVER_OK:-0}" = 1 ] || { echo 'ABORT: no declared window'; exit 36; }
[ "${WIN_STILL_OPEN:-0}" = 1 ] || { echo "ABORT: closed $WIN_CLOSE"; exit 36; }
GUARD="$EV/refired_idx84_0025_B${WIN_BSEQ}"
[ ! -e "$GUARD" ] || { echo 'ABORT: window already used for idx84 refire'; exit 21; }
CLOSE_EPOCH=$(date -u -d "$WIN_CLOSE" +%s); NOW_EPOCH=$(date -u +%s)
[ $((CLOSE_EPOCH-NOW_EPOCH)) -ge 120 ] || { echo 'ABORT: insufficient single-frame airtime+recovery'; exit 36; }
# One-frame staged SHA gate.
python3 - "$FRAMES/frame_84.bin" <<'PY'
import sys,hashlib
from pathlib import Path
sha=hashlib.sha256(Path(sys.argv[1]).read_bytes()).hexdigest()
assert sha=='33a6e94255dda59a97b0734716974eccea3ee4a2f8ef8ee905980ea15d9e6bde'
print('STAGED_SHA_GATE=PASS idx=84 sha256='+sha)
PY
TXLOG="$EV/b2a_refire_idx84_tx_B${WIN_BSEQ}.log"
RECLOG="$EV/b2a_refire_idx84_recovery_B${WIN_BSEQ}.log"
CONLOG="$EV/b2a_refire_idx84_recovery_B${WIN_BSEQ}_console.log"
POSTJSON="$EV/frontier_solution_refire_verdict_B${WIN_BSEQ}_post.json"
systemctl --user stop fleet-rx-standby.service || true
PIDS=$(pgrep -x test_loragw_hal 2>/dev/null || true)
if [ -n "$PIDS" ]; then for p in $PIDS; do kill -9 "$p" 2>/dev/null || true; done; sleep 2; fi
if pgrep -x test_loragw_hal >/dev/null 2>&1; then systemctl --user start fleet-rx-standby.service; echo 'ABORT: SPI still held'; exit 11; fi
cd "$HAL"
set +e
sudo timeout 120 "$TXBIN" -d "$FRAMES" -f 903.9 -s "$FRONTIER_SF" -b "$FRONTIER_BW_KHZ" -p "$FRONTIER_POW_DBM" -n 1 -g "$FRONTIER_GAP_S" -c /dev/spidev0.0 2>&1 | tee "$TXLOG"
TX_RC=${PIPESTATUS[0]}
set -e
cd /home/researcher-bravo/fleet-repos/zk-lora-milestone-1/tools
set +e
RECOVERY_LOG="$RECLOG" bash ./lora_chirp_recovery.sh > "$CONLOG" 2>&1
RECOVERY_RC=$?
set -e
systemctl --user start fleet-rx-standby.service
sleep 3
python3 - "$TX_RC" "$RECOVERY_RC" "$WIN_BSEQ" "$WIN_ASEQ" "$WIN_CLOSE" "$TXLOG" "$POSTJSON" <<'PY'
import json,os,sys,hashlib,urllib.request
from pathlib import Path
sys.path.insert(0,'/home/researcher-bravo/fleet-repos/fleet/fast-channel')
from post_event import post
ev=Path('/home/researcher-bravo/fleet/evidence/frontier_drill_20261121/issue_0025')
txrc,recrc=map(int,sys.argv[1:3]); winb,wina,winclose=sys.argv[3:6]
txlog=Path(sys.argv[6]); postjson=Path(sys.argv[7]); log=txlog.read_text(errors='replace')
raw=(ev/'solution_refire_idx84/frame_84.bin').read_bytes(); sha=hashlib.sha256(raw).hexdigest()
done=log.count('TX_DONE'); complete='CHIRP_TX_COMPLETE=YES' in log
data={'to':'alpha','from':'bravo','type':'frontier_solution_refire_verdict','drill':'frontier_drill_20261121','issue_id':'FRONTIER-GH-0025','ok':bool(txrc==0 and recrc==0 and complete and done==1),'refire_only':True,'chunk_indices':[84],'frames_fired':1,'tx_done_markers':done,'chirp_tx_complete':complete,'frame_sha256':[sha],'bravo_declared_payload_sha256':'5d97dd19b1f536d677821a6c7b011d2a53f6e93e1fc268f1314751c7c5b08f47','tx_exit_code':txrc,'recovery_exit_code':recrc,'rf':'903.9MHz SF7 BW125 14dBm','sf':7,'bw_khz':125,'power_dbm':14,'in_reply_to':5989,'original_solution_verdict':5948,'alpha_rx_window':{'b_seq':int(winb),'a_seq':wina,'closes_at_utc':winclose},'tx_log':str(txlog),'note':'Exactly the one missing declared frame (chunk idx 84) refired once at SF7 per ADR; all 84 other frames intentionally not repeated. Receiver must join this frame to the banked 84 and verify full payload SHA 5d97dd19….'}
out={}
for plane,url in [('B','http://127.0.0.1:8643'),('A','http://REDACTED-LAN-ALPHA:8643')]: out[plane]=post(url,'frontier_solution_refire_verdict',data)
postjson.write_text(json.dumps({'data':data,'post':out},indent=2)+'\n')
print(json.dumps(out,indent=2))
if not data['ok'] or not all(v.get('ok') for v in out.values()): raise SystemExit(30)
PY
POST_RC=$?
[ "$TX_RC" -eq 0 ] && [ "$POST_RC" -eq 0 ] && touch "$GUARD"
echo "REFIRE_DONE tx_rc=$TX_RC recovery_rc=$RECOVERY_RC post_rc=$POST_RC window=B${WIN_BSEQ}"
exit $(( TX_RC != 0 ? TX_RC : POST_RC ))
