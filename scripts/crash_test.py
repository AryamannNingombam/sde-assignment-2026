"""Kill the controller repeatedly mid-run, restart it, then prove the finish was correct.

    python scripts/crash_test.py --scenario scenarios/public_02_incidents.yaml --out reports/crash_recovery.log

Each kill is SIGKILL / TerminateProcess: no cleanup handler runs. Kill times come from a seeded
generator so a failing run can be repeated. Pass/fail is checked against the simulator's HTTP API,
which the controller cannot influence, and an independent recount of the event stream.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from collections import Counter

import httpx


def wait_ready(http: httpx.Client, proc: subprocess.Popen, limit: float = 900) -> None:
    start = time.time()
    while time.time() - start < limit:
        if proc.poll() is not None:
            raise SystemExit("simulator exited during startup")
        try:
            if http.get("/health").status_code == 200:
                return
        except httpx.TransportError:
            pass
        time.sleep(0.5)
    raise SystemExit("simulator did not become ready")


def recount(http: httpx.Client) -> tuple[Counter, int]:
    """Counts the event stream directly, independent of the controller's ingestion code."""
    counts: Counter = Counter()
    events = 0
    for kind in ("history", "events"):
        for chunk in http.get("/events/chunks", params={"kind": kind}).json():
            for line in http.get(f"/events/chunks/{chunk['chunk']}").text.splitlines():
                ev = json.loads(line)
                events += 1
                if ev["type"] == "call":
                    counts["dials"] += 1
                    counts["connected"] += int(ev["connected"])
                    counts["engaged"] += int(ev["engaged"])
    return counts, events


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="scenarios/public_02_incidents.yaml")
    ap.add_argument("--out", default="reports/crash_recovery.log")
    ap.add_argument("--port", type=int, default=8710)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--min-gap", type=float, default=8.0, help="shortest run between kills, seconds")
    ap.add_argument("--max-gap", type=float, default=30.0)
    ap.add_argument("--max-kills", type=int, default=12)
    a = ap.parse_args()

    work = tempfile.mkdtemp(prefix="crash_test_")
    db = os.path.join(work, "state", "controller.db")
    url = f"http://127.0.0.1:{a.port}"
    rng = random.Random(a.seed)
    lines: list[str] = []

    def say(msg: str) -> None:
        print(msg, flush=True)
        lines.append(msg)

    sim = subprocess.Popen([sys.executable, "-m", "sim", "serve", "--scenario", a.scenario, "--run-dir", os.path.join(work, "sim"), "--port", str(a.port), "--force"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    http = httpx.Client(base_url=url, timeout=600, trust_env=False)
    failures: list[str] = []
    try:
        wait_ready(http, sim)
        say(f"scenario={a.scenario} seed={a.seed} gaps={a.min_gap}-{a.max_gap}s max_kills={a.max_kills}")
        kills = restarts = 0
        cmd = [sys.executable, "-m", "controller", "--db", db, "run", "--sim-url", url]
        env = {**os.environ, "PYTHONUNBUFFERED": "1"}
        while True:
            log = open(os.path.join(work, "controller.log"), "ab")
            ctrl = subprocess.Popen(cmd, stdout=log, stderr=log, env=env)
            gap = rng.uniform(a.min_gap, a.max_gap)
            try:
                code = ctrl.wait(timeout=gap if kills < a.max_kills else None)
            except subprocess.TimeoutExpired:
                ctrl.kill()
                ctrl.wait()
                kills += 1
                state = http.get("/sim/state").json()
                say(f"kill {kills:2d}: after {gap:5.1f}s, sim at minute {state['sim_minute']} ({state['ts'][:16]})")
                restarts += 1
                continue
            finally:
                log.close()
            if code != 0:
                failures.append(f"controller exited with {code} (not killed by this test)")
                break
            say(f"controller finished normally after {kills} kills and {restarts} restarts")
            break

        state = http.get("/sim/state").json()
        store = sqlite3.connect(db)
        store.row_factory = sqlite3.Row

        def check(name: str, ok: bool, detail="") -> None:
            say(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f": {detail}" if detail != "" else ""))
            if not ok:
                failures.append(name)

        check("scenario ran to the end", bool(state["finished"]), f"minute {state['sim_minute']}")
        workflows = [w["workflow_id"] for w in http.get("/workflows").json()]
        applied_seen: Counter = Counter()
        sim_approvals = {}
        for wid in workflows:
            for h in http.get(f"/workflows/{wid}/config/history").json():
                if h["proposal_id"]:
                    applied_seen[h["proposal_id"]] += 1
            for ap_ in http.get("/approvals", params={"workflow_id": wid}).json():
                sim_approvals[ap_["proposal_id"]] = ap_
        dupes = [k for k, v in applied_seen.items() if v > 1]
        check("no proposal was applied twice", not dupes, f"{sum(applied_seen.values())} applied, duplicates: {dupes}")

        ours = {r["proposal_id"]: dict(r) for r in store.execute("SELECT * FROM proposals")}
        lost = [p for p in sim_approvals if p not in ours]
        check("no approval was lost: every approval in the simulator is in our store", not lost, f"{len(sim_approvals)} approvals, missing: {lost}")
        unrecorded = [p for p in applied_seen if p not in ours or ours[p]["status"] != "applied"]
        check("every applied change is recorded as applied in our store", not unrecorded, unrecorded or len(applied_seen))
        phantom = [p for p, r in ours.items() if r["status"] == "applied" and p not in applied_seen]
        check("nothing is recorded as applied that did not happen", not phantom, phantom or 0)
        stuck = [p for p, r in ours.items() if r["status"] in ("drafted", "applying")]
        check("no proposal is left half-done", not stuck, stuck or 0)

        counts, events = recount(http)
        ingested = store.execute("SELECT SUM(events) e FROM chunks").fetchone()["e"]
        check("every event ingested exactly once", ingested == events, f"stream {events}, store {ingested}")
        r = store.execute("SELECT SUM(dials) d, SUM(connected) c, SUM(engaged) e FROM fact_arm").fetchone()
        check("rollups match an independent recount", (r["d"], r["c"], r["e"]) == (counts["dials"], counts["connected"], counts["engaged"]), f"dials {r['d']}, connected {r['c']}, engaged {r['e']}")
        versions = {wid: http.get(f"/workflows/{wid}/config").json()["version"] for wid in workflows}
        versions_ok = all(store.execute("SELECT MAX(version) v FROM config_versions WHERE workflow_id=?", (w,)).fetchone()["v"] == v for w, v in versions.items())
        check("our store knows the final config version of every workflow", versions_ok, versions)
        learned = store.execute("SELECT status, COUNT(*) n FROM experiments GROUP BY status").fetchall()
        check("learning survived the restarts", bool(learned), {x["status"]: x["n"] for x in learned})
        decisions = store.execute("SELECT COUNT(*) n FROM decisions").fetchone()["n"]
        say(f"audit rows {decisions}; credits used {200 - state['credits_remaining'] if state['credits_remaining'] <= 200 else 'n/a'}")
        store.close()
    finally:
        sim.terminate()
        sim.wait(timeout=30)
    say("RESULT: " + ("PASS" if not failures else f"FAIL {failures}"))
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    shutil.rmtree(work, ignore_errors=True)
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
