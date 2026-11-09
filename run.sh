#!/usr/bin/env bash
# Contract: ./run.sh <SIM_URL> starts the controller and runs until the scenario finishes (restart-safe).
# State lives in $CTRL_STATE_DIR (default .ctrl_state); a new simulator world is detected and state is reset automatically.
set -euo pipefail
SIM_URL="${1:?usage: ./run.sh <SIM_URL>}"
cd "$(dirname "$0")"
exec python -m controller --url "$SIM_URL" --state-dir "${CTRL_STATE_DIR:-.ctrl_state}"
