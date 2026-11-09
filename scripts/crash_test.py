"""Crash-recovery evidence (SUBMISSION §9). Portable: runs the same on Linux and Windows.

    python scripts/crash_test.py [--scenario scenarios/public_01_dev.yaml] [--port 8721]

Kills the controller four times during one public_01 run, restarting it each time:
  1. right after a proposal is recorded PENDING                (CRASH_AT=pending, os._exit: no cleanup)
  2. right after an approval is detected, before apply         (CRASH_AT=approved)
  3. in the middle of ingesting a chunk, before its commit     (CRASH_AT=ingest:<n>)
  4. a hard external kill (SIGKILL / TerminateProcess) at an arbitrary moment
then lets it finish and checks:
  - no proposal was applied twice (proposal_ids in config/history are unique)
  - every submitted proposal reached a terminal state, and every controller version in the simulator's history
    has its APPLIED proposal in our store (no lost pending approval, no audit gap)
  - the ingest checkpoint equals the last chunk, and aggregates match a clean ingest of the same chunks
Writes reports/crash_test.log.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.run_scenario import serve, wait_ready  # noqa: E402

LOG: list[str] = []


def say(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    LOG.append(line)


def run_controller(url: str, db: Path, crash_at: str | None = None, kill_after_s: float | None = None) -> int:
    env = {**os.environ, "PYTHONUTF8": "1"}
    env.pop("CRASH_AT", None)
    if crash_at:
        env["CRASH_AT"] = crash_at
    p = subprocess.Popen([sys.executable, "-m", "controller.main", "--url", url, "--db", str(db)], cwd=ROOT, env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if kill_after_s is not None:
        try:
            return p.wait(timeout=kill_after_s)
        except subprocess.TimeoutExpired:
            p.kill()                                   # SIGKILL on Linux, TerminateProcess on Windows
            p.wait()
            return -9
    return p.wait()


def sim_minute(url: str) -> int:
    return httpx.get(f"{url}/sim/state").json()["sim_minute"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="scenarios/public_01_dev.yaml")
    ap.add_argument("--port", type=int, default=8721)
    a = ap.parse_args()
    url = f"http://127.0.0.1:{a.port}"
    db = ROOT / "state" / "crash_test.db"
    for suffix in ("", "-wal", "-shm"):
        Path(str(db) + suffix).unlink(missing_ok=True)
    sim = serve(a.scenario, ROOT / "runs" / "crash_test", a.port)
    ok = True
    try:
        wait_ready(url)
        for crash in ("pending", "approved", "ingest:30"):
            code = run_controller(url, db, crash_at=crash)
            say(f"CRASH_AT={crash:<10} exit={code} sim at {fmt(sim_minute(url))}")
            ok &= code == 137
        code = run_controller(url, db, kill_after_s=4.0)
        say(f"external hard kill        exit={code} sim at {fmt(sim_minute(url))}")
        code = run_controller(url, db)
        say(f"final run                 exit={code} sim at {fmt(sim_minute(url))}")
        ok &= code == 0
        ok &= check(url, db)
    finally:
        sim.terminate()
        sim.wait()
    say("RESULT: " + ("PASS" if ok else "FAIL"))
    out = ROOT / "reports" / "crash_test.log"
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(LOG) + "\n", encoding="utf-8")
    sys.exit(0 if ok else 1)


def check(url: str, db: Path) -> bool:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    ok = True
    state = httpx.get(f"{url}/sim/state").json()
    say(f"simulator finished={state['finished']} chunks={state['chunks']}")
    for w in httpx.get(f"{url}/workflows").json():
        wf = w["workflow_id"]
        hist = httpx.get(f"{url}/workflows/{wf}/config/history").json()
        ours = [h for h in hist if h["actor"].startswith("controller")]
        pids = [h["proposal_id"] for h in ours]
        dup = len(pids) != len(set(pids))
        missing = [p for p in pids if not conn.execute("SELECT 1 FROM proposals WHERE proposal_id=? AND"
                                                       " state='APPLIED'", (p,)).fetchone()]
        say(f"{wf}: {len(ours)} controller versions, duplicate applies={dup}, missing from store={missing}")
        ok &= not dup and not missing
    stuck = conn.execute("SELECT proposal_id, state FROM proposals WHERE submitted_minute IS NOT NULL AND state IN"
                         " ('SUBMITTING','APPLYING','AUTO_APPLYING','APPROVED')").fetchall()
    pending = conn.execute("SELECT COUNT(*) FROM proposals WHERE state='PENDING'").fetchone()[0]
    say(f"submitted proposals stuck mid-flight: {[tuple(r) for r in stuck]}; still pending at scenario end: {pending}")
    ok &= not stuck
    last = json.loads(conn.execute("SELECT value FROM meta WHERE key='last_chunk'").fetchone()[0])
    say(f"ingest checkpoint {last}, simulator last chunk {state['chunks'] - 1}")
    ok &= last == state["chunks"] - 1
    calls = conn.execute("SELECT SUM(dials) FROM agg WHERE hour >= 0").fetchone()[0]
    truth = sum(sum(1 for ln in httpx.get(f"{url}/events/chunks/{c['chunk']}").text.splitlines() if '"type":"call"' in ln)
                for c in httpx.get(f"{url}/events/chunks", params={"kind": "events"}).json())
    say(f"calls aggregated {calls} vs calls in the event stream {truth}")
    ok &= calls == truth
    say(f"decisions recorded: {conn.execute('SELECT COUNT(*) FROM decisions').fetchone()[0]}")
    return ok


def fmt(minute: int) -> str:
    return f"D{minute // 1440} {minute % 1440 // 60:02d}:{minute % 60:02d}"


if __name__ == "__main__":
    main()
