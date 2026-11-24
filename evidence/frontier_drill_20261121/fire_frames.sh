#!/usr/bin/env bash
# Fire all sealed 245B frames over real LoRa 903.9 MHz SF9 BW125 14dBm.
# Usage: fire_frames.sh <frames_dir> <log_file> [label]
set -u
FRAMES="$1"; LOG="$2"; LABEL="${3:-frontier}"
TXAPP=/home/researcher-alpha/fleet-repos/zk-lora-milestone-1/tools/zk_lora_tx_app
cd /home/researcher-alpha/sx1302_hal/libloragw || exit 1
echo "FIRE_START $(date -u +%Y-%m-%dT%H:%M:%SZ) label=$LABEL frames=$FRAMES" >> "$LOG"
n=0; ok=0
for f in "$FRAMES"/frame_*.bin; do
  idx=$(basename "$f" .bin)
  sha=$(sha256sum "$f" | cut -d' ' -f1)
  t0=$(date -u +%s.%N)
  out=$(timeout 25 sudo -n "$TXAPP" -i "$f" -n 1 -f 903.9 -s 9 -b 125 -p 14 2>&1)
  t1=$(date -u +%s.%N)
  status=$(echo "$out" | grep -o "A_LORA_TX_FILE_SEND_COMPLETE=[A-Z]*" | tail -1)
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $idx sha=${sha:0:16} t=${t0}->${t1} $status" >> "$LOG"
  n=$((n+1)); [ -n "$status" ] && ok=$((ok+1))
  sleep "${GAP:-3}"
done
echo "FIRE_DONE $(date -u +%Y-%m-%dT%H:%M:%SZ) label=$LABEL frames_fired=$n tx_done=$ok" >> "$LOG"
echo "fired=$n tx_done=$ok"
