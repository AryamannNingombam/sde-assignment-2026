"""Load numbers on public_03 (12 workflows, ~850k events/day): writes reports/public_03_load.md.

    python scripts/load_test.py [--port 8731]

Runs the real controller (the same entry point as run.sh) against the load scenario and reports what it measured
about itself (status file) plus store size. Run on the target box (4 vCPU / 8 GB) for the submission numbers.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.run_scenario import serve, wait_ready  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="scenarios/public_03_load.yaml")
    ap.add_argument("--port", type=int, default=8731)
    a = ap.parse_args()
    url = f"http://127.0.0.1:{a.port}"
    db = ROOT / "state" / "load_test.db"
    for suffix in ("", "-wal", "-shm"):
        Path(str(db) + suffix).unlink(missing_ok=True)
    sim = serve(a.scenario, ROOT / "runs" / "load_test", a.port)
    try:
        wait_ready(url, timeout=300)
        t0 = time.time()
        env = {**os.environ, "CONTROLLER_STRICT": "1"}
        subprocess.run([sys.executable, "-m", "controller.main", "--url", url, "--db", str(db)], cwd=ROOT, check=True,
                       env=env)
        total = time.time() - t0
    finally:
        sim.terminate()
        sim.wait()
    status = json.loads((ROOT / "state" / "load_test.status.json").read_text())
    loop = status["loop"]
    conn = sqlite3.connect(db)
    q = lambda sql: conn.execute(sql).fetchone()[0]
    days = loop.get("wall_s_per_sim_day", {})
    live_events = q("SELECT SUM(dials) FROM agg WHERE hour >= 0")
    size_mb = sum(os.path.getsize(str(db) + s) for s in ("", "-wal") if os.path.exists(str(db) + s)) / 2**20
    rows = {t: q(f"SELECT COUNT(*) FROM {t}") for t in ("leads", "agg", "calls_log", "decisions", "proposals")}
    n_days = max(1, len(days))
    lines = [
        "# public_03 load numbers", "",
        f"Machine: {platform.platform()}, {os.cpu_count()} logical CPUs, Python {platform.python_version()}. "
        "Simulator and controller on the same machine.", "",
        "| metric | value |", "|---|---|",
        f"| total wall time (bootstrap + {len(days)} simulated days) | {total:.0f} s |",
        f"| history bootstrap (14 days, chunk 0) | {loop.get('startup_ingest_wall_s')} s |",
        f"| wall seconds per simulated day (advance + ingest + decide) | {', '.join(f'{k}: {v}' for k, v in days.items())} |",
        f"| mean wall per simulated day | {sum(days.values()) / n_days:.1f} s (target < 600 s) |",
        f"| ingest throughput (all chunks, parse + commit) | {loop['ingest_total']['events_per_s']:,} events/s over "
        f"{loop['ingest_total']['events']:,} events in {loop['ingest_total']['wall_s']:.0f} s |",
        f"| last decision pass | {loop.get('decision_pass_ms')} ms (12 workflows) |",
        f"| peak RSS (controller) | {status['peak_rss_mb']} MB |",
        f"| store size at end | {size_mb:.0f} MB ({size_mb / (n_days + 14):.1f} MB per simulated day incl. history) |",
        f"| calls dialled after D0 (aggregated) | {live_events:,} |",
        f"| rows | " + ", ".join(f"{k}={v:,}" for k, v in rows.items()) + " |",
        "", "The simulator's own advance time is included in the per-day wall time.",
    ]
    out = ROOT / "reports" / "public_03_load.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
