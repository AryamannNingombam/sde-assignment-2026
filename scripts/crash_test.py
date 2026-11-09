"""Crash-recovery demonstration (C13): kill -9 the controller at random moments of a real run, restart it, and
check the invariants that matter to Platform/SRE: it finishes, never double-applies, never loses a proposal, and
its own store agrees with what the simulator recorded.

    python scripts/crash_test.py --scenario public_02_incidents --kills 6 --seed 1
"""
import argparse
import json
import os
import random
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POINTS = ["after_approval_post", "after_apply_post", "after_auto_put"]
PY = str(ROOT / ".venv/bin/python") if (ROOT / ".venv/bin/python").exists() else sys.executable


def wait_health(url, timeout=120):
    import httpx
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if httpx.get(url + "/health", timeout=2).status_code == 200:
                return
        except Exception:
            time.sleep(0.5)
    raise SystemExit("simulator did not come up")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="public_02_incidents")
    ap.add_argument("--kills", type=int, default=6)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    rnd = random.Random(a.seed)
    tag = f"crash_{a.scenario}"
    run_dir, db = ROOT / "runs" / f"mine_{tag}", ROOT / "runs" / f"ctl_{tag}.db"
    base = ROOT / "runs" / f"base_{a.scenario}"
    url = "http://127.0.0.1:8700"
    subprocess.run("pkill -f 'sim serve' || true", shell=True)
    time.sleep(1)
    for f in (db, Path(str(db) + "-wal"), Path(str(db) + "-shm")) + tuple(Path(str(db) + "." + p) for p in POINTS):
        f.unlink(missing_ok=True)
    if not base.exists():
        subprocess.run([PY, "-m", "sim", "baseline", "--scenario", f"scenarios/{a.scenario}.yaml",
                        "--run-dir", str(base)], cwd=ROOT, check=True)
    sim = subprocess.Popen([PY, "-m", "sim", "serve", "--scenario", f"scenarios/{a.scenario}.yaml", "--run-dir",
                            str(run_dir), "--force"], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log = open(ROOT / "runs" / f"{tag}.log", "w")
    try:
        wait_health(url)
        kills = 0
        for attempt in range(a.kills + 12):
            env = dict(os.environ)
            mode = "none"
            env["CTL_CRASH_FLAG"] = str(db)
            if attempt < len(POINTS):                      # deterministic: die inside the dangerous windows
                env["CTL_CRASH_POINT"] = POINTS[attempt]
                mode = "point"
            elif kills < a.kills:
                mode = rnd.choice(["sigkill", "sigkill", "exit_mid_loop"])
                if mode == "exit_mid_loop":
                    env["CRASH_AT_TICK"] = str(rnd.randint(5, 150))
            p = subprocess.Popen([PY, "-m", "controller", "run", "--url", url, "--db", str(db)], cwd=ROOT, env=env,
                                 stdout=log, stderr=subprocess.STDOUT)
            if mode == "sigkill":
                time.sleep(rnd.uniform(1.5, 3.5))
                if p.poll() is None:
                    p.send_signal(signal.SIGKILL)
                    p.wait()
                    kills += 1
                    print(f"attempt {attempt}: SIGKILL after run start", flush=True)
                    continue
            rc = p.wait()
            if mode == "point":
                kills += 1
                print(f"attempt {attempt}: died at crash point '{env['CTL_CRASH_POINT']}' (rc={rc})", flush=True)
                continue
            if mode == "exit_mid_loop" and rc == 137:
                kills += 1
                print(f"attempt {attempt}: hard exit at tick {env['CRASH_AT_TICK']}", flush=True)
                continue
            if rc == 0:
                print(f"attempt {attempt}: controller finished cleanly after {kills} kills", flush=True)
                break
            print(f"attempt {attempt}: unexpected exit {rc}", flush=True)
        else:
            raise SystemExit("controller never finished")
        verify(url, db, run_dir, base, kills)
    finally:
        sim.terminate()


def verify(url, db, run_dir, base, kills):
    import httpx
    c = httpx.Client(base_url=url, timeout=60)
    st = c.get("/sim/state").json()
    assert st["finished"], "scenario did not finish"
    con = sqlite3.connect(db)
    problems = []
    sim_approvals = c.get("/approvals").json()
    ours = {r[0]: r for r in con.execute("SELECT proposal_id, kind, state, approval_id, applied_version FROM proposal")}
    # 1. no approval was lost or invented
    for ap in sim_approvals:
        if ap["proposal_id"] not in ours:
            problems.append(f"sim approval {ap['approval_id']} has no proposal row in our store (LOST)")
        elif ours[ap["proposal_id"]][3] != ap["approval_id"]:
            problems.append(f"approval id mismatch for {ap['proposal_id']}")
    # 2. no proposal id used twice / no double apply: each approved-and-applied approval maps to exactly one version
    versions = {}
    for wf in {a["workflow_id"] for a in sim_approvals} | {r[0] for r in con.execute("SELECT DISTINCT wf FROM proposal")}:
        for v in c.get(f"/workflows/{wf}/config/history").json():
            if v["approval_id"]:
                versions.setdefault(v["approval_id"], []).append((wf, v["version"]))
            if v["proposal_id"] and v["actor"] == "controller_auto":
                versions.setdefault("auto:" + v["proposal_id"], []).append((wf, v["version"]))
    for k, v in versions.items():
        if len(v) != 1:
            problems.append(f"{k} applied {len(v)} times: {v}")
    # 3. our store agrees with the simulator about what was applied
    for pid, kind, state, aid, av in ours.values():
        if state == "applied":
            key = aid if kind == "approval" else "auto:" + pid
            if key not in versions:
                problems.append(f"{pid} is 'applied' in our store but the simulator never applied it")
    for aid, v in versions.items():
        if aid.startswith("apr_"):
            if not any(r[3] == aid and r[2] == "applied" for r in ours.values()):
                problems.append(f"{aid} applied in the simulator but not recorded as applied by us")
    # 4. no proposal stuck non-terminal
    stuck = con.execute("SELECT proposal_id,state FROM proposal WHERE state IN ('intent','pending','approved')").fetchall()
    # (pending/approved at the very end of the scenario is fine only if the sim agrees)
    for pid, state in stuck:
        aid = ours[pid][3]
        s = c.get(f"/approvals/{aid}").json()["status"] if aid else None
        if s in ("rejected", "expired", "applied", "lapsed"):
            problems.append(f"{pid} stuck as {state} but simulator says {s}")
    simlog = [json.loads(l) for l in (run_dir / "sim_log.jsonl").read_text().splitlines() if l.strip()]
    from collections import Counter
    k = Counter(r["kind"] for r in simlog)
    cred_ours = con.execute("SELECT COALESCE(SUM(credits),0) FROM credit_log").fetchone()[0]
    spent = st["credits_remaining"]
    print(json.dumps({"kills": kills, "sim_finished": st["finished"], "approval_requests_in_sim": k["approval_requested"],
                      "our_approval_proposals": sum(1 for r in ours.values() if r[1] == "approval"),
                      "apply_conflicts": k["apply_conflict"], "approvals_lapsed": k["approval_lapsed"],
                      "auto_applied": k["auto_applied"], "credits_remaining_in_sim": spent,
                      "credits_logged_by_controller": cred_ours,
                      "problems": problems}, indent=1))
    if problems:
        raise SystemExit("INVARIANT VIOLATIONS: " + "; ".join(problems))
    print("OK: all invariants hold after", kills, "crashes")
    subprocess.run([PY, "-m", "sim", "grade", "--run", str(run_dir), "--baseline", str(base), "--out",
                    str(ROOT / "reports" / "crash_recovery_grade.md")], cwd=ROOT, stdout=subprocess.DEVNULL)


if __name__ == "__main__":
    main()
