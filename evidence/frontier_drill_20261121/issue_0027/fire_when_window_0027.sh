#!/bin/bash
# No-LLM hot watcher: wait for a fresh declared Alpha window, then fire once.
set -u
EV="$HOME/fleet/evidence/frontier_drill_20261121/issue_0027"
for attempt in $(seq 1 1200); do
  OUT="$EV/.fire_attempt.log"
  bash "$EV/fire_solution_0027.sh" >"$OUT" 2>&1
  rc=$?
  cat "$OUT" >> "$EV/fire_solution_0027_watcher.log"
  if grep -qE 'no Alpha rx_window_open|insufficient time|window closed' "$OUT"; then
    sleep 5
    continue
  fi
  cp "$OUT" "$EV/fire_solution_0027_console.log"
  exit "$rc"
done
exit 36
