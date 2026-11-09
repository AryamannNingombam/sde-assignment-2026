#!/usr/bin/env bash
# Contract: ./run.sh <SIM_URL> runs the controller until the scenario finishes, with no manual steps.
# No Docker. Needs Python 3.11+ with requirements.txt installed. State goes to state/controller.db.
#
# The loop below is the process supervisor. The controller resumes from its database, so a crash
# only costs the restart. Exit 0 means the scenario finished. Any other exit is retried.
set -uo pipefail
SIM_URL="${1:?usage: ./run.sh <SIM_URL>}"
cd "$(dirname "$0")"

PYTHON="${PYTHON:-}"
if [ -z "$PYTHON" ]; then
  if [ -x .venv/bin/python ]; then PYTHON=.venv/bin/python
  elif [ -x .venv/Scripts/python.exe ]; then PYTHON=.venv/Scripts/python.exe
  elif command -v python3 >/dev/null && python3 -c 'import httpx' 2>/dev/null; then PYTHON=python3
  else PYTHON=python
  fi
fi

MAX_RESTARTS="${MAX_RESTARTS:-20}"
restarts=0
until "$PYTHON" -m controller run --sim-url "$SIM_URL"; do
  code=$?
  restarts=$((restarts + 1))
  if [ "$restarts" -ge "$MAX_RESTARTS" ]; then
    echo "controller exited with $code; giving up after $restarts restarts" >&2
    exit "$code"
  fi
  echo "controller exited with $code; restart $restarts of $MAX_RESTARTS" >&2
  sleep 2
done
