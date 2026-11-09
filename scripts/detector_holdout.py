"""Detector false-positive rates on history windows never used for tuning (SUBMISSION §7).

    python scripts/detector_holdout.py state/public_01_dev.db [state/public_02_incidents.db ...]

History (14 days before D0, business default config) is split into:
  dev        days -14..-9   baselines come from here; thresholds were fixed here (settings.py)
  holdout A  days  -8..-5   the shipped detectors are replayed ONCE; observed alarm rate reported as is
  holdout B  days  -4..-1   untouched unless A exceeds 1 alarm / 10 workflow-days (then a retuned detector is
                            measured once on B; not needed if A passes)
Replays the same pure verdict functions the controller uses, hourly, with the same persistence rule.
Caveat: history may contain real incidents, so these are upper bounds on the false-positive rate.
Writes reports/detector_fp.md.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from controller import metrics, settings  # noqa: E402
from controller.detectors import cid_verdict, cid_window, hallu_verdict  # noqa: E402

DEV, A, B = (-14, -8), (-8, -4), (-4, 0)            # [start_day, end_day)
CALL_HOURS = range(9, 22)


def replay(conn: sqlite3.Connection, wf: str, window: tuple[int, int]) -> dict:
    base = (DEV[0] * 24, DEV[1] * 24)
    streak_cid: dict[str, int] = {}
    streak_h = 0
    alarms = {"caller_id": 0, "hallucination": 0}
    evaluated = {"caller_id": 0, "hallucination": 0}
    flagged: set[str] = set()
    hallu_open = False
    dev = metrics.total(conn, wf, since_hour=base[0], until_hour=base[1])
    h_base = dev.halluc / dev.connected
    for day in range(*window):
        for hod in CALL_HOURS:
            h = day * 24 + hod
            for did, (w, matched, peers) in cid_window(conn, wf, h, baseline=base).items():
                v = cid_verdict(w, matched, peers)
                if not v["eligible"]:
                    continue
                evaluated["caller_id"] += 1
                streak_cid[did] = streak_cid.get(did, 0) + 1 if v["fire"] else 0
                if streak_cid[did] >= settings.CID_PERSIST and did not in flagged:
                    alarms["caller_id"] += 1
                    flagged.add(did)
                elif streak_cid[did] == 0:
                    flagged.discard(did)
            c = metrics.total(conn, wf, since_hour=h - settings.HALLU_WINDOW_MIN // 60, until_hour=h)
            v = hallu_verdict(c.halluc, c.connected, h_base, settings.HALLU_MIN_CONNECTED)
            if v["eligible"]:
                evaluated["hallucination"] += 1
                streak_h = streak_h + 1 if v["fire"] else 0
                if streak_h >= settings.HALLU_PERSIST and not hallu_open:
                    alarms["hallucination"] += 1
                    hallu_open = True
                elif streak_h == 0:
                    hallu_open = False
    return {"alarms": alarms, "evaluated": evaluated, "days": window[1] - window[0]}


def main(paths: list[str]) -> None:
    rows, totals = [], {"A": {"caller_id": 0, "hallucination": 0, "wf_days": 0},
                        "dev": {"caller_id": 0, "hallucination": 0, "wf_days": 0}}
    for p in paths:
        conn = sqlite3.connect(p)
        scenario = conn.execute("SELECT value FROM meta WHERE key='scenario'").fetchone()[0].strip('"')
        for (wf,) in conn.execute("SELECT wf FROM workflows ORDER BY wf").fetchall():
            for name, window in (("dev", DEV), ("A", A)):
                r = replay(conn, wf, window)
                rows.append((scenario, wf, name, r))
                totals[name]["wf_days"] += r["days"]
                for k in ("caller_id", "hallucination"):
                    totals[name][k] += r["alarms"][k]
    L = ["# Detector false-positive replay on history", "",
         "Baselines from the dev window (days -14..-9); shipped thresholds from `controller/settings.py`; the same",
         "verdict functions and persistence rule the controller runs. History may hold real incidents, so these are",
         "upper bounds on the false-positive rate.", "",
         "| scenario | workflow | window | caller-ID alarms | (windows evaluated) | hallucination alarms | (windows evaluated) |",
         "|---|---|---|---|---|---|---|"]
    for scenario, wf, name, r in rows:
        L.append(f"| {scenario} | {wf} | {name} | {r['alarms']['caller_id']} | {r['evaluated']['caller_id']} | "
                 f"{r['alarms']['hallucination']} | {r['evaluated']['hallucination']} |")
    L.append("")
    for name in ("dev", "A"):
        t = totals[name]
        L.append(f"- **{name}**: caller-ID {t['caller_id']} alarms / {t['wf_days']} workflow-days "
                 f"= {t['caller_id'] / max(t['wf_days'], 1):.3f} per workflow-day; hallucination {t['hallucination']}"
                 f" / {t['wf_days']} = {t['hallucination'] / max(t['wf_days'], 1):.3f} per workflow-day")
    a = totals["A"]
    ok = max(a["caller_id"], a["hallucination"]) / max(a["wf_days"], 1) <= 0.1
    L += ["", f"Holdout A {'passes' if ok else 'FAILS'} the bar of at most 1 alarm per 10 workflow-days. "
              + ("Holdout B stays untouched (no retuning happened)." if ok else
                 "Retune on dev + A and measure the candidate once on B.")]
    out = ROOT / "reports" / "detector_fp.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main(sys.argv[1:] or ["state/public_01_dev.db", "state/public_02_incidents.db"])
