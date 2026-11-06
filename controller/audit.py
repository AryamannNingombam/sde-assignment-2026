"""Audit stub: ``python -m controller why --state-dir state --workflow W --at "Day 3 14:00"``.

Answers from OUR store only (R7): the active config version, its proposal/approval lifecycle
and the decision rows behind it. The full version (lead join, monitoring, superseding
chains) comes with the later phases.
"""
from __future__ import annotations

import json
import re
from typing import Any

from . import settings
from .store import Store

_AT = re.compile(r"^\s*(?:Day|D)\s*(-?\d+)\s+(\d{1,2}):(\d{2})\s*$", re.IGNORECASE)


def parse_at(text: str) -> int:
    """``"Day 3 14:00"`` (or ``"D3 14:00"``) -> sim minute (IST, Day 0 = minute 0)."""
    m = _AT.match(text)
    if not m:
        raise ValueError(f"cannot parse {text!r}; expected like 'Day 3 14:00'")
    day, hour, minute = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if not (0 <= hour < 24 and 0 <= minute < 60):
        raise ValueError(f"bad time in {text!r}")
    return day * settings.MINUTES_PER_DAY + hour * 60 + minute


def fmt_minute(minute: int | None) -> str:
    if minute is None:
        return "-"
    day, rem = divmod(minute, settings.MINUTES_PER_DAY)
    return f"Day {day} {rem // 60:02d}:{rem % 60:02d}"


def _rows(store: Store, sql: str, args: tuple = ()) -> list[dict]:
    cur = store.conn.execute(sql, args)
    names = [d[0] for d in cur.description]
    return [dict(zip(names, r)) for r in cur.fetchall()]


def why(store: Store, workflow: str, at_minute: int) -> dict[str, Any]:
    versions = _rows(
        store, "SELECT version, actor, ts_minute, changed_dims, proposal_id, approval_id"
        " FROM config_versions WHERE workflow_id=? AND ts_minute IS NOT NULL AND ts_minute<=?"
        " ORDER BY version DESC LIMIT 1", (workflow, at_minute))
    if not versions:  # no change observed yet: the initial version
        versions = _rows(store, "SELECT version, actor, ts_minute, changed_dims, proposal_id,"
                         " approval_id FROM config_versions WHERE workflow_id=? ORDER BY version"
                         " LIMIT 1", (workflow,))
    out: dict[str, Any] = {"workflow": workflow, "at": fmt_minute(at_minute), "version": None,
                           "proposal": None, "lifecycle": [], "decisions": [], "superseded_by": []}
    if not versions:
        return out
    ver = versions[0]
    out["version"] = ver
    prop = None
    if ver["proposal_id"]:
        prop = _rows(store, "SELECT proposal_id, kind, state, route, approval_id, base_version,"
                     " created_minute, filed_minute, applied_version, applied_minute, supersedes,"
                     " body FROM proposals WHERE proposal_id=?", (ver["proposal_id"],))
    if prop:
        p = prop[0]
        body = json.loads(p.pop("body") or "{}")
        p.update(summary=body.get("summary"), dims=body.get("dims"), tv=body.get("tv"),
                 impact_score=body.get("impact_score"), affected_leads=body.get("affected_leads"),
                 rationale=body.get("request", {}).get("rationale"))
        out["proposal"] = p
        out["lifecycle"] = _rows(store, "SELECT ts_minute, event, payload FROM proposal_events"
                                 " WHERE proposal_id=? ORDER BY id", (p["proposal_id"],))
        out["decisions"] = _rows(
            store, "SELECT sim_minute, kind, summary FROM decisions WHERE"
            " json_extract(inputs, '$.proposal_id')=? ORDER BY id", (p["proposal_id"],))
        out["superseded_by"] = _rows(store, "SELECT proposal_id, state FROM proposals WHERE"
                                     " supersedes=? OR proposal_id=?", (p["proposal_id"], p["supersedes"]))
    else:
        out["decisions"] = _rows(
            store, "SELECT sim_minute, kind, summary FROM decisions WHERE workflow_id=? AND"
            " kind='config_observed' AND summary LIKE ? ORDER BY id", (workflow, f"v{ver['version']} %"))
    return out


def render(report: dict[str, Any]) -> str:
    lines = [f"why {report['workflow']} at {report['at']}"]
    v = report["version"]
    if v is None:
        return "\n".join(lines + ["  no config version recorded"])
    lines.append(f"  active version v{v['version']} by {v['actor'] or 'initial'}"
                 f" (observed {fmt_minute(v['ts_minute'])}, dims {v['changed_dims']})")
    p = report["proposal"]
    if p:
        lines.append(f"  proposal {p['proposal_id']} [{p['route']}] state={p['state']}"
                     f" approval={p['approval_id']} base=v{p['base_version']}")
        lines.append(f"    summary: {p['summary']}")
        lines.append(f"    rationale: {p['rationale']}")
        lines.append(f"    impact={p['impact_score']} affected_leads={p['affected_leads']} tv={p['tv']}")
        lines.append("  lifecycle:")
        lines += [f"    {fmt_minute(t)} {e} {pl}" for t, e, pl in
                  [(r["ts_minute"], r["event"], r["payload"]) for r in report["lifecycle"]]]
    elif v["proposal_id"] is None and v["actor"] == "supervisor":
        lines.append("  made by the client's supervisor (bypasses governance; never silently overwritten)")
    lines.append("  decisions:")
    lines += [f"    {fmt_minute(d['sim_minute'])} {d['kind']}: {d['summary']}" for d in report["decisions"]]
    for other in report["superseded_by"]:
        lines.append(f"  related: {other['proposal_id']} ({other['state']})")
    return "\n".join(lines)
