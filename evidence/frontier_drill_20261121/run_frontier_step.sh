#!/usr/bin/env bash
# Frontier drill loop driver (system cron). flock prevents concurrent senders.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
export FRONTIER_BUS=http://192.168.1.220:8643
# token from the user crontab environment file (chmod 600), never committed
TOKEN_FILE="$HOME/.config/fleet/fast_token"
[ -f "$TOKEN_FILE" ] && export FLEET_FAST_TOKEN="$(cat "$TOKEN_FILE")"
cd "$HERE" || exit 1
exec flock -n /tmp/frontier_loop.lock timeout 300 python3 frontier_loop.py >> logs/cron.log 2>&1
