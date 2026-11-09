#!/usr/bin/env bash
# Crash-recovery evidence, all inside Docker: SIGKILL the controller container twice mid-run on public_02, restart it on the same
# state volume, let it finish, then verify from the SIMULATOR's side that nothing was applied twice, nothing is stuck "sending",
# and the run completed. The state volume is thrown away at the end. usage: scripts/crash_test.sh   (needs port 8700 free)
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/free_port.sh
REPORT_DIR=${REPORT_DIR:-reports}; mkdir -p "$REPORT_DIR" runs
OUT="$REPORT_DIR/crash_recovery_public_02.log"; : > "$OUT"
export SCENARIO=public_02_incidents RUN_NAME=mine_crash
dc() { docker compose -p ctrl_crash "$@"; }
docker compose build -q
dc down -v --remove-orphans >/dev/null 2>&1 || true
free_port 8700
dc up -d --wait sim
trap 'dc down -v --remove-orphans >/dev/null 2>&1 || true' EXIT
for n in 1 2; do
  secs=$((n*4+2))
  echo "== run $n: SIGKILL after ${secs}s ==" | tee -a "$OUT"
  docker rm -f ctrl-crash-run >/dev/null 2>&1 || true
  dc run -d --no-deps --name ctrl-crash-run controller ./run.sh http://sim:8700 >/dev/null
  sleep $secs; docker kill ctrl-crash-run >/dev/null
  docker logs ctrl-crash-run 2>&1 | tail -3 | cut -c1-200 >> "$OUT"
  echo "sim state at kill: $(curl -s http://127.0.0.1:8700/sim/state | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d["ts"],"finished=",d["finished"])')" | tee -a "$OUT"
done
docker rm -f ctrl-crash-run >/dev/null 2>&1 || true
echo "== run 3: restart and finish ==" | tee -a "$OUT"
dc run --rm --no-deps -T controller ./run.sh http://sim:8700 2>&1 | tail -3 | cut -c1-200 >> "$OUT"
echo "== verification (from the simulator + controller store) ==" | tee -a "$OUT"
dc run --rm --no-deps -T controller python - <<'PY' 2>&1 | tee -a "$OUT"
import json, sqlite3, httpx
c = httpx.Client(base_url="http://sim:8700", timeout=60)
st = c.get("/sim/state").json(); print("finished:", st["finished"], "ts:", st["ts"]); assert st["finished"]
dup = total = 0
for w in c.get("/workflows").json():
    h = c.get(f"/workflows/{w['workflow_id']}/config/history").json()
    ids = [x["proposal_id"] for x in h if x.get("proposal_id")]
    total += len(ids); dup += len(ids) - len(set(ids))
print(f"controller-originated config versions: {total}, duplicated proposal_ids at the simulator: {dup}"); assert dup == 0
db = sqlite3.connect("/state/controller.db")
print("proposal status:", dict(db.execute("select status,count(*) from proposals group by 1").fetchall()))
stuck = db.execute("select count(*) from proposals where status='sending'").fetchone()[0]; print("stuck 'sending':", stuck); assert stuck == 0
print("recovered rows in audit:", db.execute("select count(*) from audit where kind='recovered'").fetchone()[0])
print("RESULT: PASS")
PY
