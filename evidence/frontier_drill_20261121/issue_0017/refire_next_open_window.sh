#!/bin/bash
# No-LLM hot path: wait for a fresh Alpha window with adequate airtime, then fire once.
set -u
EV=/home/researcher-bravo/fleet/evidence/frontier_drill_20261121/issue_0017
for attempt in $(seq 1 480); do
  echo "WATCH_ATTEMPT=$attempt $(date -u +%FT%TZ)"
  bash "$EV/fire_solution_0017.sh"
  rc=$?
  if [ "$rc" -eq 0 ]; then
    echo "REFIRE_WATCHER_DONE=YES rc=0 $(date -u +%FT%TZ)"
    exit 0
  fi
  if [ "$rc" -ne 36 ]; then
    echo "REFIRE_WATCHER_ABORT rc=$rc $(date -u +%FT%TZ)"
    exit "$rc"
  fi
  sleep 5
done
echo 'REFIRE_WATCHER_DONE=NO reason=deadline'
exit 36
