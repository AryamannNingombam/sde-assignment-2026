#!/usr/bin/env bash
# Starts the controller and runs until the scenario finishes. No Docker: Python 3.11+ and requirements.txt.
#   ./run.sh http://127.0.0.1:8700
# State lives in state/controller.db (override with CONTROLLER_DB). Re-running against the same simulator
# resumes from the checkpoint; a different scenario or a restarted simulator archives the old store first.
set -euo pipefail
SIM_URL="${1:?usage: ./run.sh <SIM_URL>}"
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"
command -v "$PY" >/dev/null 2>&1 || PY=python
# Install dependencies only if they are missing, and fail loudly if that doesn't work.
"$PY" -c "import httpx, numpy" 2>/dev/null || "$PY" -m pip install -q -r requirements.txt

# The controller exits 0 only when the scenario has finished. Anything else (an unexpected error, the simulator
# unreachable for longer than the GET retries) is survivable by design: state is checkpointed and every in-flight
# proposal is reconciled on startup. So restart it, a bounded number of times, rather than end the run early.
MAX_RESTARTS="${CONTROLLER_MAX_RESTARTS:-5}"
child=0
# Forward termination (e.g. a grader's timeout) to the controller, then stop: never restart after a TERM/INT.
# Exit with the conventional 128+signal code: 143 for TERM, 130 for INT.
stop() { if [ "$child" -ne 0 ]; then kill -TERM "$child" 2>/dev/null || true; wait "$child" || true; fi; exit "$1"; }
trap 'stop 143' TERM
trap 'stop 130' INT
for attempt in $(seq 0 "$MAX_RESTARTS"); do
  code=0
  "$PY" -m controller.main --url "$SIM_URL" --db "${CONTROLLER_DB:-state/controller.db}" &
  child=$!
  wait "$child" || code=$?
  [ "$code" -eq 0 ] && exit 0
  echo "controller exited with $code on attempt $((attempt + 1)) of $((MAX_RESTARTS + 1)); restarting from the checkpoint" >&2
  sleep 2
done
echo "controller failed $((MAX_RESTARTS + 1)) times; giving up" >&2
exit 1
