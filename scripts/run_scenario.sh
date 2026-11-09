#!/usr/bin/env bash
# Run one scenario end to end: sim server + controller + grade.  usage: scripts/run_scenario.sh public_01_dev [tag]
set -euo pipefail
cd "$(dirname "$0")/.."
SC="$1"; TAG="${2:-$SC}"
PY=python; [ -x .venv/bin/python ] && PY=.venv/bin/python
[ -d runs/base_$SC ] || $PY -m sim baseline --scenario scenarios/$SC.yaml --run-dir runs/base_$SC
pkill -f "sim serve" 2>/dev/null || true
sleep 1
$PY -m sim serve --scenario scenarios/$SC.yaml --run-dir runs/mine_$TAG --force > runs/sim_$TAG.log 2>&1 &
SIMPID=$!
for i in $(seq 1 120); do curl -sf localhost:8700/health >/dev/null && break; sleep 1; done
CTL_FRESH=1 CTL_DB=runs/ctl_$TAG.db ./run.sh http://127.0.0.1:8700 2>&1 | tee runs/ctl_$TAG.log
kill $SIMPID 2>/dev/null || true
mkdir -p reports
$PY -m sim grade --run runs/mine_$TAG --baseline runs/base_$SC --out reports/$TAG.md > /dev/null
cat reports/$TAG.md
