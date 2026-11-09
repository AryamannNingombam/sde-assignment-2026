#!/usr/bin/env bash
# Reproduce the grade reports entirely inside Docker: per scenario a fresh compose project (own simulator, own THROWAWAY
# `ctrl_state` volume), the controller runs in a one-off container, then `sim grade` vs a no-op baseline.
# Nothing is written to the host except runs/ (simulator run dirs, logs) and $REPORT_DIR (default: reports/).
# usage: scripts/eval.sh [01 02 03]        (needs port 8700 free; Docker Desktop running)
set -euo pipefail
cd "$(dirname "$0")/.."
source scripts/free_port.sh
REPORT_DIR=${REPORT_DIR:-reports}; mkdir -p "$REPORT_DIR" runs
scen() { case $1 in 01) echo public_01_dev;; 02) echo public_02_incidents;; 03) echo public_03_load;; esac; }
docker compose build -q
for n in ${@:-01 02 03}; do
  sc=$(scen $n); short=public_$n; proj=ctrl_$short
  export SCENARIO=$sc RUN_NAME=mine_$short
  dc() { docker compose -p $proj "$@"; }
  [ -d runs/base_$short ] || dc run --rm --no-deps sim python -m sim baseline --scenario scenarios/$sc.yaml --run-dir /runs/base_$short
  dc down -v --remove-orphans >/dev/null 2>&1 || true        # fresh simulator world AND fresh controller store
  free_port 8700
  dc up -d --wait sim
  t0=$(date +%s)
  dc run --rm --no-deps -T controller python -c "
import resource, subprocess, sys
rc = subprocess.call(['./run.sh', 'http://sim:8700'])
print('PEAK_RSS_KB=%d' % resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss, file=sys.stderr)
sys.exit(rc)" > runs/ctrl_$short.log 2> runs/ctrl_$short.err
  rss=$(sed -n 's/^PEAK_RSS_KB=//p' runs/ctrl_$short.err | tail -1)
  echo "$short wall_s=$(( $(date +%s) - t0 )) peak_rss_kb=$rss" | tee -a "$REPORT_DIR/walltime.txt"
  dc run --rm --no-deps sim python -m sim grade --run /runs/mine_$short --baseline /runs/base_$short --out /runs/grade_$short.md
  cp runs/grade_$short.md "$REPORT_DIR/$short.md"
  dc down -v --remove-orphans                                  # throw the controller store away
done
