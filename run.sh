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
"$PY" -m pip install -q -r requirements.txt >/dev/null 2>&1 || true
exec "$PY" -m controller.main --url "$SIM_URL" --db "${CONTROLLER_DB:-state/controller.db}"
