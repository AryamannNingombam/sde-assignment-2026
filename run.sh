#!/usr/bin/env bash
# Contract: ./run.sh <SIM_URL> starts the controller and runs until the scenario finishes. No manual steps.
# Needs: python3.10+ and `pip install -r requirements.txt` (one-time). No Docker, no external services:
# state lives in a SQLite file (CTL_DB, default runs/controller.db). Re-running resumes from that file; set
# CTL_FRESH=1 to start from scratch (use it when the simulator world was also restarted).
set -euo pipefail
SIM_URL="${1:?usage: ./run.sh <SIM_URL>}"
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"
[ -x .venv/bin/python ] && PY=.venv/bin/python
DB="${CTL_DB:-runs/controller.db}"
mkdir -p "$(dirname "$DB")"
[ "${CTL_FRESH:-0}" = "1" ] && rm -f "$DB" "$DB-wal" "$DB-shm"
exec "$PY" -m controller run --url "$SIM_URL" --db "$DB" ${CTL_SERVE:+--serve}
