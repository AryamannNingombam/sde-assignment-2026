#!/usr/bin/env bash
# Contract: ./run.sh <SIM_URL> runs the controller until the scenario finishes.
# Exits 0 only when the controller exits 0 (it does so only once /sim/state
# reports finished). Crashes are restarted; the controller resumes from SQLite.
set -u
SIM_URL="${1:?usage: ./run.sh <SIM_URL>}"
SIM_URL="${SIM_URL%/}"
cd "$(dirname "$0")"

MAX_RESTARTS="${MAX_RESTARTS:-20}"
WAIT_TIMEOUT_S="${WAIT_TIMEOUT_S:-300}"
STATE_DIR="${STATE_DIR:-state}"

pick_python() {
  if [ -n "${PYTHON:-}" ]; then
    echo "$PYTHON"
    return 0
  fi
  local cand
  for cand in python3 python; do
    if command -v "$cand" >/dev/null 2>&1 \
        && "$cand" -c "import httpx" >/dev/null 2>&1; then
      echo "$cand"
      return 0
    fi
  done
  return 1
}

PY="$(pick_python)" || { echo "run.sh: no python with httpx found" >&2; exit 2; }
echo "run.sh: using interpreter '$PY'" >&2

# The simulator builds its history before it opens the port, so wait generously.
deadline=$(( $(date +%s) + WAIT_TIMEOUT_S ))
until "$PY" - "$SIM_URL" <<'PYEOF' >/dev/null 2>&1
import sys, httpx
httpx.get(sys.argv[1] + "/health", timeout=5).raise_for_status()
PYEOF
do
  if [ "$(date +%s)" -ge "$deadline" ]; then
    echo "run.sh: $SIM_URL/health not up after ${WAIT_TIMEOUT_S}s" >&2
    exit 3
  fi
  sleep 2
done
echo "run.sh: simulator is up" >&2

restarts=0
MIN_HEALTHY_RUN_S="${MIN_HEALTHY_RUN_S:-120}"
while true; do
  started=$(date +%s)
  "$PY" -m controller run --url "$SIM_URL" --state-dir "$STATE_DIR"
  rc=$?
  if [ "$rc" -eq 0 ]; then
    echo "run.sh: controller finished cleanly" >&2
    exit 0
  fi
  # a run that lasted long was healthy: do not count its crash against the restart cap
  if [ $(( $(date +%s) - started )) -gt "$MIN_HEALTHY_RUN_S" ]; then
    restarts=0
  fi
  restarts=$(( restarts + 1 ))
  echo "run.sh: controller exited rc=$rc (restart $restarts/$MAX_RESTARTS)" >&2
  if [ "$restarts" -gt "$MAX_RESTARTS" ]; then
    echo "run.sh: restart cap reached" >&2
    exit 1
  fi
  sleep 2
done
