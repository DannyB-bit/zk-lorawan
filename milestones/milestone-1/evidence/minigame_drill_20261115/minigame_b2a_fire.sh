#!/bin/bash
# minigame_b2a_fire.sh — B-side fire for the minigame drill leg 2 (B_to_A).
#
# Fleet law (rak-miner-v2-radio skill):
#   1. fail-closed: verify the staged sealed-frame SHA256 set BEFORE touching the radio
#   2. stop the RX chain-guard + kill any live listener (chip cannot RX+TX simultaneously)
#   3. fire via cd-first law (HAL tools call ./reset_lgw.sh by RELATIVE path)
#   4. re-certify with RECOVERY_LOG=<this run's log> (gate reads ONLY this run)
#   5. ALWAYS restart fleet-rx-standby.service on every exit path, or RX stays dark
#
# Usage: minigame_b2a_fire.sh <frames_dir> <reps> <gap_s> <run_tag>
set -u

FRAMES_DIR="$1"
REPS="${2:-2}"
GAP_S="${3:-2}"
TAG="${4:-run}"
EV=/home/researcher-bravo/fleet/evidence/minigame_drill_20261115
HAL=/home/researcher-bravo/sx1302_hal/libloragw
TXBIN="$EV/chirp_frames_tx"
TXLOG="$EV/leg2_tx_${TAG}.log"
RECOVERY_LOG="$EV/recovery_${TAG}.log"
MANIFEST="$FRAMES_DIR/manifest.json"

echo "=== [1/5] fail-closed staged-SHA verification ==="
python3 "$EV/staged_sha_gate.py" "$FRAMES_DIR" "$MANIFEST" || { echo "ABORT 10: staged SHA gate failed"; exit 10; }

echo "=== [2/5] stop RX chain-guard + kill listener ==="
systemctl --user stop fleet-rx-standby.service
PIDS=$(pgrep -x test_loragw_hal || true)
if [ -n "$PIDS" ]; then
  echo "killing HAL listeners: $PIDS"
  for p in $PIDS; do kill -9 "$p" 2>/dev/null || true; done
  sleep 2
fi
pgrep -x test_loragw_hal && { echo "ABORT: listener still alive"; }
echo "RX guard stopped; listeners remaining: $(pgrep -x test_loragw_hal | wc -l)"

echo "=== [3/5] FIRE (14 frames x ${REPS} reps @903.9 SF9 125kHz) ==="
cd "$HAL" || { echo "ABORT: no HAL dir"; exit 11; }
sudo timeout 600 ./chirp_frames_tx -d "$FRAMES_DIR" -f 903.9 -s 9 -b 125 -p 14 -n "$REPS" -g "$GAP_S" -c /dev/spidev0.0 2>&1 | tee "$TXLOG"
TX_RC=${PIPESTATUS[0]}
echo "TX_RC=$TX_RC"

echo "=== [4/5] re-certify chain (this run's recovery log only) ==="
cd /home/researcher-bravo/fleet-repos/zk-lora-milestone-1/tools || true
RECOVERY_LOG="$RECOVERY_LOG" bash ./lora_chirp_recovery.sh 2>&1 | tail -20
GATE_RC=${PIPESTATUS[0]}
echo "RECOVERY_RC=$GATE_RC"

echo "=== [5/5] re-arm RX standby ==="
systemctl --user start fleet-rx-standby.service
sleep 3
systemctl --user is-active fleet-rx-standby.service
echo "TXLOG=$TXLOG"
echo "RECOVERY_LOG=$RECOVERY_LOG"
echo "FIRE_DONE tx_rc=$TX_RC recovery_rc=$GATE_RC"
exit $TX_RC
