"""Audit queries (C12): answer "why did workflow X change at time T, who approved it, and what happened next?"
purely from the controller's own store.

    python -m controller why --db runs/ctl.db --wf nw_renewal --at "D3 14:00"
"""
from __future__ import annotations

import json
import re

from .common import MIN_PER_DAY, fmt_minute


def parse_at(s: str) -> int:
    m = re.match(r"D(\d+)\s+(\d+):(\d+)", s.strip())
    if m:
        return int(m.group(1)) * MIN_PER_DAY + int(m.group(2)) * 60 + int(m.group(3))
    from .common import minute_of
    return minute_of(s)


def why(store, wf: str, at_min: int) -> str:
    s = store
    L = []
    row = s.q1("SELECT event_id, minute, version, actor, dims, proposal_id, approval_id FROM cfgchg "
               "WHERE wf=? AND minute<=? ORDER BY minute DESC, event_id DESC LIMIT 1", (wf, at_min))
    if not row:
        return f"{wf}: no config change recorded at or before {fmt_minute(at_min)} (business default config in force)."
    eid, minute, ver, actor, dims, pid, aid = row
    L.append(f"{wf} config v{ver} was in force at {fmt_minute(at_min)}; it was set at {fmt_minute(minute)} by actor "
             f"'{actor}', changing {json.loads(dims)}.")
    prop = s.q1("SELECT proposal_id, kind, state, approval_id, sent_min, decided_min, applied_min, reasons, body, "
                "decision_id FROM proposal WHERE proposal_id=? OR approval_id=? LIMIT 1", (pid, aid)) if (pid or aid) else None
    if actor == "supervisor":
        L.append("  WHY: a client supervisor edited the config directly (bypasses governance). We did not revert it; "
                 "see the decision below for how the learning state adapted.")
    elif prop:
        ppid, kind, state, approval_id, sent, decided, applied, reasons, body, did = prop
        b = json.loads(body)
        L.append(f"  PROPOSAL {ppid} ({kind}): \"{b.get('change_summary') or b.get('rationale')}\"")
        L.append(f"  RATIONALE: {b.get('rationale')}")
        if kind == "approval":
            L.append(f"  GOVERNANCE: requested {fmt_minute(sent)}, approver decision {fmt_minute(decided) if decided else '?'}"
                     f" (approval {approval_id}), applied {fmt_minute(applied) if applied else 'n/a'}; "
                     f"impact_score={b.get('impact_score')}, affected_leads={b.get('affected_leads')}")
            L.append(f"  DRY RUN: {json.dumps(b.get('dry_run'), default=str)[:600]}")
            if b.get("evidence"):
                L.append(f"  EVIDENCE: {b['evidence']}")
        else:
            L.append(f"  GOVERNANCE: policy-permitted auto-apply at {fmt_minute(applied)} (no human in the loop, "
                     f"within allowed_dims and max_shift)")
        if did:
            d = s.q1("SELECT minute, kind, summary, inputs, outputs FROM decision WHERE id=?", (did,))
            L.append(f"  DECISION RECORD #{did} @ {fmt_minute(d[0])} [{d[1]}]: {d[2]}")
            L.append(f"    inputs: {d[3][:900]}")
    L.append("  WHAT HAPPENED NEXT:")
    for m, k, sm in s.q("SELECT minute, kind, summary FROM decision WHERE wf=? AND minute>=? AND id>COALESCE((SELECT MAX(id) FROM decision WHERE wf=? AND minute<?),0) ORDER BY id LIMIT 8",
                        (wf, minute, wf, minute)):
        L.append(f"    {fmt_minute(m)} [{k}] {sm[:200]}")
    day = minute // MIN_PER_DAY
    b = s.q1("SELECT SUM(dials),SUM(conn),SUM(eng) FROM agg_day WHERE wf=? AND day BETWEEN ? AND ?", (wf, day - 2, day - 1))
    a = s.q1("SELECT SUM(dials),SUM(conn),SUM(eng) FROM agg_day WHERE wf=? AND day BETWEEN ? AND ?", (wf, day + 1, day + 2))
    f = lambda x: (f"pickup {x[1] / x[0]:.3f}, engagement {x[2] / x[1]:.3f} (n={x[0]} dials)" if x and x[0] else "n/a")
    L.append(f"  KPIs 2 days before: {f(b)}")
    L.append(f"  KPIs 2 days after : {f(a)}")
    return "\n".join(L)
