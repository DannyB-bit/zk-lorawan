#!/usr/bin/env bash
# Arm RakMiner-A RX window to capture B->A chirps (same params proven in minigame/essay drills).
# Usage: arm_rx.sh <timeout_s> <log_file>
set -u
T="$1"; LOG="$2"
cd /home/researcher-alpha/sx1302_hal/libloragw || exit 1
echo "RX_ARM $(date -u +%Y-%m-%dT%H:%M:%SZ) timeout_s=$T" >> "$LOG"
timeout "$T" sudo -n stdbuf -oL -eL ./test_loragw_hal_rx -d /dev/spidev0.0 -r 1250 -a 904.3 -b 905.0 -k 0 -m 0 -j -z 255 -n 0 >> "$LOG" 2>&1
echo "RX_EXIT=$? $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$LOG"
