#!/usr/bin/env python
"""Selection-effect analysis: why can engaged/connected fall with no harmful change?

    python scripts/guardrail_analysis.py <mine_run_dir> <baseline_run_dir>

Reads the simulator event files (calls only). Stats per workflow: pickup, engaged/connected overall, engagement by
caller_id within our run, engagement on the FIRST connect per lead (mine vs baseline), connects per lead,
engagement by connect ordinal, and a pickup-matched re-weighting of the baseline.
"""
from __future__ import annotations

import glob
import json
import sys
from collections import defaultdict
from pathlib import Path


def load(run: str):
    calls = []
    for f in sorted(glob.glob(str(Path(run) / "events" / "*.jsonl"))):
        for line in open(f, encoding="utf-8"):
            e = json.loads(line)
            if e.get("type") == "call":
                calls.append(e)
    return calls


def summarise(calls):
    out = {}
    by_wf = defaultdict(list)
    for e in calls:
        by_wf[e["workflow_id"]].append(e)
    for wid, es in by_wf.items():
        es.sort(key=lambda e: e["event_id"])
        n, conn = len(es), sum(e["connected"] for e in es)
        eng = sum(e["engaged"] for e in es)
        first, seen, ordinal = {}, defaultdict(int), defaultdict(lambda: [0, 0])
        prev_eng: dict = {}
        after = defaultdict(lambda: [0, 0])  # (previous connect engaged?) -> [connects, engaged]
        att = defaultdict(lambda: [0, 0, 0])  # attempt_no -> [dials, connected, engaged]
        per_lead_conn = defaultdict(int)
        per_lead_dials = defaultdict(int)
        by_did = defaultdict(lambda: [0, 0, 0])
        for e in es:
            lid = e["lead_id"]
            per_lead_dials[lid] += 1
            a = att[min(e["attempt_no"], 4)]
            a[0] += 1
            a[1] += e["connected"]
            a[2] += e["engaged"]
            d = by_did[e["variant"]["caller_id"]]
            d[0] += 1
            d[1] += e["connected"]
            d[2] += e["engaged"]
            if e["connected"]:
                per_lead_conn[lid] += 1
                k = min(seen[lid], 3)
                seen[lid] += 1
                ordinal[k][0] += 1
                ordinal[k][1] += e["engaged"]
                if lid in prev_eng:
                    t = after[prev_eng[lid]]
                    t[0] += 1
                    t[1] += e["engaged"]
                prev_eng[lid] = e["engaged"]
                if lid not in first:
                    first[lid] = e["engaged"]
        leads = len(per_lead_dials)
        out[wid] = {
            "dials": n, "pickup": conn / n, "engaged_per_connected": eng / conn, "leads": leads,
            "leads_connected": len(per_lead_conn), "connects_per_connected_lead": conn / max(1, len(per_lead_conn)),
            "dials_per_lead": n / leads,
            "first_connect_engaged": sum(first.values()) / max(1, len(first)), "first_n": len(first),
            "after": {k: (v[1] / max(1, v[0]), v[0]) for k, v in sorted(after.items())},
            "att": {k: (v[1] / v[0], v[2] / max(1, v[1]), v[0]) for k, v in sorted(att.items())},
            "ordinal": {k: (v[1] / v[0], v[0]) for k, v in sorted(ordinal.items())},
            "by_did": {k: (v[1] / v[0], v[2] / max(1, v[1]), v[0]) for k, v in sorted(by_did.items())},
        }
    return out


def main() -> int:
    mine, base = summarise(load(sys.argv[1])), summarise(load(sys.argv[2]))
    for wid in sorted(mine):
        m, b = mine[wid], base[wid]
        print(f"\n## {wid}")
        print("| metric | baseline | ours |\n|---|---|---|")
        for k, label in (("dials", "dials"), ("pickup", "pickup"), ("engaged_per_connected", "engaged / connected"),
                         ("leads", "distinct leads dialled"), ("leads_connected", "leads connected at least once"),
                         ("dials_per_lead", "dials per lead"),
                         ("connects_per_connected_lead", "connects per connected lead"),
                         ("first_connect_engaged", "engaged on FIRST connect per lead")):
            fmt = (lambda x: f"{x:.4f}") if isinstance(m[k], float) else (lambda x: f"{x:,}")
            print(f"| {label} | {fmt(b[k])} | {fmt(m[k])} |")
        print("\nEngagement by connect ordinal (rate, n)  baseline | ours")
        for k in sorted(set(m["ordinal"]) | set(b["ordinal"])):
            bo, mo = b["ordinal"].get(k, (0, 0)), m["ordinal"].get(k, (0, 0))
            print(f"  connect #{k + 1}{'+' if k == 3 else ''}: {bo[0]:.4f} ({bo[1]}) | {mo[0]:.4f} ({mo[1]})")
        print("Repeat connects: engaged rate given the lead's previous connect was (not) engaged (rate, n)")
        for k in (False, True):
            if k in m["after"] or k in b["after"]:
                bo, mo = b["after"].get(k, (0, 0)), m["after"].get(k, (0, 0))
                print(f"  previous {'engaged' if k else 'not engaged'}: {bo[0]:.4f} ({bo[1]}) | {mo[0]:.4f} ({mo[1]})")
        print("By attempt_no (pickup, engaged/connected, dials)  baseline | ours")
        for k in sorted(set(m["att"]) | set(b["att"])):
            bo, mo = b["att"].get(k, (0, 0, 0)), m["att"].get(k, (0, 0, 0))
            print(f"  attempt {k}{'+' if k == 4 else ''}: {bo[0]:.3f} {bo[1]:.4f} {bo[2]} | {mo[0]:.3f} {mo[1]:.4f} {mo[2]}")
        print("Our run by caller_id (pickup, engaged/connected, dials)")
        for k, (p, e, nn) in m["by_did"].items():
            print(f"  {k}: pickup {p:.3f}  engaged/connected {e:.4f}  dials {nn}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
