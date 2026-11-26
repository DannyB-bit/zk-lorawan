#!/usr/bin/env bash
# Frontier drill loop driver (system cron). flock prevents concurrent senders.
# PUBLIC-SAFE version: no LAN addresses. Set FRONTIER_BUS to your twin's fast-channel
# events endpoint (e.g. http://<twin-host>:8643) in the cron environment.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
: "${FRONTIER_BUS:?set FRONTIER_BUS to the twin fast-channel base URL}"
export FRONTIER_BUS
# token from a chmod-600 file outside the repo, never committed
TOKEN_FILE="$HOME/.config/fleet/fast_token"
[ -f "$TOKEN_FILE" ] && export FLEET_FAST_TOKEN="$(cat "$TOKEN_FILE")"
cd "$HERE" || exit 1
exec flock -n /tmp/frontier_loop.lock timeout 300 python3 frontier_loop.py >> logs/cron.log 2>&1
