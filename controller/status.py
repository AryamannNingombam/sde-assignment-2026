"""Loop health (for on-call) and the one-screen supervisor summary.

    python -m controller.status                    # loop health from state/status.json + the store
    python -m controller.status --supervisor ks_cancel
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys

from . import settings, store
from .clock import MIN_PER_DAY, fmt

log = logging.getLogger("controller.status")


def peak_rss_mb() -> float | None:
    try:
        import resource                                   # Linux / macOS
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return rss / 1024 if sys.platform != "darwin" else rss / 2**20
    except ImportError:
        pass
    try:                                                  # Windows
        import ctypes
        from ctypes import wintypes

        class PMC(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
        c = PMC()
        c.cb = ctypes.sizeof(PMC)
        current = ctypes.windll.kernel32.GetCurrentProcess
        current.restype = wintypes.HANDLE            # otherwise the 64-bit pseudo-handle is truncated
        ctypes.windll.psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
        ctypes.windll.psapi.GetProcessMemoryInfo(current(), ctypes.byref(c), c.cb)
        return c.PeakWorkingSetSize / 2**20
    except Exception:
        return None


def snapshot(conn: sqlite3.Connection, minute: int, loop: dict) -> dict:
    """Everything an on-call engineer needs on one page."""
    day_ago = minute - MIN_PER_DAY
    proposals = dict(conn.execute("SELECT state, COUNT(*) FROM proposals GROUP BY state").fetchall())
    quota = {wf: n for wf, n in conn.execute("SELECT wf, COUNT(*) FROM proposals WHERE path='approval' AND"
                                             " submitted_minute > ? GROUP BY wf", (day_ago,))}
    decisions_h = conn.execute("SELECT COUNT(*) FROM decisions WHERE minute > ?", (minute - 60,)).fetchone()[0]
    start = store.get_meta(conn, "credits_start", 0)
    remaining = store.get_meta(conn, "credits_remaining", 0)
    return {
        "sim_time": fmt(minute), "sim_minute": minute,
        "ingest": {"last_chunk": store.get_meta(conn, "last_chunk", -1), **loop.get("ingest", {})},
        "loop": {k: v for k, v in loop.items() if k != "ingest"},
        "peak_rss_mb": round(peak_rss_mb() or 0, 1),
        "decisions_last_hour": decisions_h,
        "proposals_by_state": proposals,
        "approval_requests_last_24h": quota,
        "credits": {"start": start, "remaining": remaining,
                    "incident_reserve": round(start * settings.CREDIT_RESERVE_FRAC, 1),
                    "below_reserve": remaining < start * settings.CREDIT_RESERVE_FRAC},
        "experiments": [dict(r) for r in conn.execute(
            "SELECT id, wf, dim, stage, state, control, arms_json AS arms FROM experiments"
            " WHERE state NOT IN ('KEPT_CONTROL','ROLLED_BACK','INVALIDATED','REJECTED','EXHAUSTED')")],
        # MONITORING_SPLIT = an inconclusive test whose split was kept: monitored, never approved as a promotion
        "incidents": [dict(r) for r in conn.execute("SELECT id, wf, kind, state, credits_spent FROM incidents"
                                                    " WHERE state IN ('OPEN','PROPOSED','VERIFYING')")],
        "open_alerts": [dict(r) for r in conn.execute("SELECT minute, severity, wf, message FROM alerts"
                                                      " WHERE resolved=0 ORDER BY severity, minute DESC LIMIT 20")],
    }


def path_for(db_path: str) -> str:
    """state/controller.db -> state/controller.status.json (one status file per store)."""
    return os.path.splitext(db_path)[0] + ".status.json"


def write(conn: sqlite3.Connection, minute: int, loop: dict, path: str) -> dict:
    """Best effort: a status file someone has open (Windows locks it) must never stop the loop."""
    snap = snapshot(conn, minute, loop)
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(snap, f, indent=2)
        os.replace(tmp, path)
    except OSError as e:
        log.warning("status file not written (%s); the store is unaffected", e)
    return snap


def supervisor_view(conn: sqlite3.Connection, wf: str) -> str:
    """What's being tested, what's winning, what we need from you, what changed today (memo 04)."""
    now = store.get_meta(conn, "sim_minute", 0)
    L = [f"== {wf} @ {fmt(now)} =="]
    L.append("\nBeing tested / live results:")
    for e in conn.execute("SELECT * FROM experiments WHERE wf=? ORDER BY id", (wf,)):
        res = json.loads(e["result_json"] or "{}")
        last = conn.execute("SELECT rule, inputs_json FROM decisions WHERE experiment_id=? ORDER BY id DESC LIMIT 1",
                            (e["id"],)).fetchone()
        line = f"  - {e['dim']}: {e['state']} (control {e['control']}, challengers {json.loads(e['arms_json'] or '[]')})"
        if last:
            line += f" — last: {last['rule']}"
        if res.get("client_kept"):
            line += " — CLIENT KEPT DESPITE DECAY"
        L.append(line)
    L.append("\nWaiting on you:")
    rows = conn.execute("SELECT proposal_id, kind, state, payload_json FROM proposals WHERE wf=? AND state IN"
                        " ('PENDING','APPROVED')", (wf,)).fetchall()
    for p in rows:
        L.append(f"  - [{p['state']}] {json.loads(p['payload_json'])['change_summary']} ({p['proposal_id']})")
    if not rows:
        L.append("  - nothing")
    L.append("\nChanged in the last 24h:")
    rows = conn.execute("SELECT version, actor, changed_dims, proposal_id, minute FROM config_versions WHERE wf=?"
                        " AND minute > ? ORDER BY version", (wf, now - MIN_PER_DAY)).fetchall()
    for v in rows:
        L.append(f"  - v{v['version']} {fmt(v['minute'])} by {v['actor']}: {json.loads(v['changed_dims'])}"
                 + (f" ({v['proposal_id']})" if v["proposal_id"] else ""))
    if not rows:
        L.append("  - nothing")
    L.append("\nAlerts (last 24h):")
    for a in conn.execute("SELECT minute, severity, message FROM alerts WHERE wf=? AND resolved=0 AND minute>?"
                          " ORDER BY minute", (wf, now - MIN_PER_DAY)):
        L.append(f"  - {fmt(a['minute'])} [{a['severity']}] {a['message']}")
    return "\n".join(L)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=settings.DB_PATH)
    ap.add_argument("--supervisor", metavar="WF")
    a = ap.parse_args(argv)
    conn = store.connect(a.db)
    if a.supervisor:
        print(supervisor_view(conn, a.supervisor))
        return
    if os.path.exists(path_for(a.db)):
        with open(path_for(a.db)) as f:
            print(f.read())
    else:
        print(json.dumps(snapshot(conn, store.get_meta(conn, "sim_minute", 0), {}), indent=2))


if __name__ == "__main__":
    main()
