#!/usr/bin/env bash
# Fire all sealed 245B frames over real LoRa 903.9 MHz BW125.
# Tunables (Dan 2026-11-24 speed/ADR calibration): SF (7-12, default 9), GAP (default 3), POW (default 14).
# FCC GUARDRAIL: power hard-capped at 20 dBm (we run 14 dBm = 25 mW, US915 902-928 MHz ISM).
# Every burst logs estimated on-air time + duty cycle (see RF_COMPLIANCE.md).
# Usage: fire_frames.sh <frames_dir> <log_file> [label]
set -u
FRAMES="$1"; LOG="$2"; LABEL="${3:-frontier}"
SF="${SF:-9}"; POW="${POW:-14}"
if [ "$POW" -gt 20 ]; then echo "FCC_GUARD: POW=$POW exceeds 20dBm cap, refusing" >> "$LOG"; exit 2; fi
case "$SF" in 7|8|9|10|11|12) ;; *) echo "FCC_GUARD: invalid SF=$SF" >> "$LOG"; exit 2;; esac
# measured LoRa airtime for 245B, BW125, CR4/5, explicit hdr, CRC (RF_COMPLIANCE.md)
case "$SF" in
  7) AIR=0.384;; 8) AIR=0.676;; 9) AIR=1.209;; 10) AIR=2.214;; 11) AIR=4.837;; 12) AIR=8.856;;
esac
TXAPP=/home/researcher-alpha/fleet-repos/zk-lora-milestone-1/tools/zk_lora_tx_app
cd /home/researcher-alpha/sx1302_hal/libloragw || exit 1
echo "FIRE_START $(date -u +%Y-%m-%dT%H:%M:%SZ) label=$LABEL frames=$FRAMES sf=$SF pow_dbm=$POW bw_khz=125 freq_mhz=903.9" >> "$LOG"
n=0; ok=0
for f in "$FRAMES"/frame_*.bin; do
  idx=$(basename "$f" .bin)
  sha=$(sha256sum "$f" | cut -d' ' -f1)
  t0=$(date -u +%s.%N)
  out=$(timeout 25 sudo -n "$TXAPP" -i "$f" -n 1 -f 903.9 -s "$SF" -b 125 -p "$POW" 2>&1)
  t1=$(date -u +%s.%N)
  status=$(echo "$out" | grep -o "A_LORA_TX_FILE_SEND_COMPLETE=[A-Z]*" | tail -1)
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $idx sha=${sha:0:16} t=${t0}->${t1} $status" >> "$LOG"
  n=$((n+1)); [ -n "$status" ] && ok=$((ok+1))
  sleep "${GAP:-3}"
done
AIRTIME=$(awk -v n="$n" -v a="$AIR" 'BEGIN{printf "%.2f", n*a}')
DUTY=$(awk -v at="$AIRTIME" 'BEGIN{printf "%.4f", 100*at/3600}')
echo "FIRE_DONE $(date -u +%Y-%m-%dT%H:%M:%SZ) label=$LABEL frames_fired=$n tx_done=$ok sf=$SF pow_dbm=$POW burst_airtime_s=$AIRTIME hourly_duty_pct_if_one_burst=$DUTY" >> "$LOG"
echo "fired=$n tx_done=$ok sf=$SF airtime_s=$AIRTIME"
