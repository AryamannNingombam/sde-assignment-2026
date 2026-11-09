"""python -m controller --url http://127.0.0.1:8700          run the loop until the scenario finishes
   python -m controller why --wf nw_renewal --at "D3 14:00"  answer "why did X change around then?" from the audit store
"""
import argparse
import json
import os
import sqlite3
import sys

from .core.engine import Controller
from .core.timeutil import label


def parse_at(s: str) -> int:
    d, hm = s.upper().lstrip("D").split()
    h, m = hm.split(":")
    return int(d) * 1440 + int(h) * 60 + int(m)


def why(state_dir, wf, at, window):
    db = sqlite3.connect(os.path.join(state_dir, "controller.db"))
    lo, hi = at - window, at + window
    print(f"Audit trail for {wf} between {label(lo)} and {label(hi)}:\n")
    for sim_ts, mn, kind, summary, details in db.execute(
            "SELECT sim_ts, sim_min, kind, summary, details FROM audit WHERE wf=? AND sim_min BETWEEN ? AND ? ORDER BY id", (wf, lo, hi)):
        print(f"[{label(mn)}] {kind:<18} {summary}")
        d = json.loads(details) if details else {}
        for k in ("rationale", "evidence", "proposal_id", "dry_run"):
            if d.get(k):
                print(f"      {k}: {json.dumps(d[k])[:300]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="run", choices=["run", "why"])
    ap.add_argument("--url", default=os.environ.get("SIM_URL", "http://127.0.0.1:8700"))
    ap.add_argument("--state-dir", default=os.environ.get("CTRL_STATE_DIR", ".ctrl_state"))
    ap.add_argument("--wf")
    ap.add_argument("--at")
    ap.add_argument("--window", type=int, default=240, help="minutes either side")
    a = ap.parse_args()
    if a.cmd == "why":
        if not (a.wf and a.at):
            sys.exit("--wf and --at required, e.g. --at 'D3 14:00'")
        return why(a.state_dir, a.wf, parse_at(a.at), a.window)
    Controller(a.url, a.state_dir).run()


if __name__ == "__main__":
    main()
