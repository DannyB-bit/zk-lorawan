#!/bin/bash
# Fail-closed hot-fire driver: no RF until fire_solution_0048.sh discovers a
# declared, open, unfired Alpha window with sufficient airtime+recovery.
set -u
EV=/home/researcher-bravo/fleet/evidence/frontier_drill_20261121/issue_0048
for ((attempt=1; attempt<=360; attempt++)); do
  printf '\nDRIVER_ATTEMPT=%d UTC=%s\n' "$attempt" "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  bash "$EV/fire_solution_0048.sh"
  rc=$?
  if [ "$rc" -eq 0 ]; then echo 'DRIVER_FIRE_COMPLETE=YES'; exit 0; fi
  if [ "$rc" -eq 21 ]; then echo 'DRIVER_ALREADY_FIRED=YES'; exit 0; fi
  echo "DRIVER_PRE_RF_ABORT rc=$rc; retrying without airtime"
  sleep 15
done
echo 'DRIVER_TIMEOUT_NO_FIRE=YES'
exit 1
