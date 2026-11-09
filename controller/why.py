"""Audit answers from our own store (never the simulator's logs).

    python -m controller.why nw_renewal --at "D3 14:00"       # why was the config what it was, who approved it,
                                                              # and what happened next
    python -m controller.why --lead nw_renewal:l00012345      # what did this person hear on each attempt, and why
    add --json for machine-readable output, --db to point at another store
"""
from __future__ import annotations

import argparse
import json
import sqlite3

from . import configs, settings, store
from .clock import fmt, parse

OUTCOMES = {0: "no_answer", 1: "voicemail", 2: "short_hangup", 3: "concluded_interested", 4: "concluded_not_interested"}


def explain_version(conn: sqlite3.Connection, wf: str, minute: int) -> dict:
    v = configs.version_at(conn, wf, minute)
    if v is None:
        return {"error": f"no config known for {wf} at {fmt(minute)}"}
    out: dict = {"workflow": wf, "at": fmt(minute), "version": v["version"], "actor": v["actor"],
                 "applied_at": fmt(v["minute"]) if v["minute"] is not None else "before D0 (business default)",
                 "changed_dims": json.loads(v["changed_dims"] or "[]"),
                 "config": json.loads(v["config_json"]) if v["config_json"] else None}
    if v["actor"] == "supervisor":
        out["note"] = "client supervisor edit: bypasses governance; recorded and preserved by the controller"
        out["our_response"] = _rows(conn, "SELECT minute, kind, rule, outcome FROM decisions WHERE wf=? AND minute>=?"
                                          " AND kind IN ('supervisor_edit','experiment','incident') ORDER BY id LIMIT 8",
                                    (wf, v["minute"]))
    if v["proposal_id"]:
        p = conn.execute("SELECT * FROM proposals WHERE proposal_id=?", (v["proposal_id"],)).fetchone()
        body = json.loads(p["payload_json"]).get("body", {}) if p else {}
        payload = json.loads(p["payload_json"]) if p else {}
        out["proposal"] = {
            "proposal_id": v["proposal_id"], "kind": p["kind"] if p else None,
            "path": "auto-apply within policy" if v["actor"] == "controller_auto" else "approval",
            "summary": payload.get("change_summary"), "rationale": payload.get("rationale"),
            "diff": body.get("diff"), "affected_leads": body.get("affected_leads"),
            "impact_score": body.get("impact_score", payload.get("impact_score")),
            "evidence": payload.get("evidence"), "dry_run": body.get("dry_run"),
            "submitted_at": _fmt(p["submitted_minute"]) if p else None,
        }
        if v["approval_id"]:
            out["approval"] = {"approval_id": v["approval_id"], "decided_at": _fmt(p["decided_minute"]) if p else None,
                               "approver": f"{_tenant(conn, wf)} approver (simulated)"}
        if p:
            out["triggered_by"] = _rows(conn, "SELECT id, minute, kind, rule, outcome, inputs_json FROM decisions"
                                              " WHERE id=?", (p["decision_id"],))
            out["lifecycle"] = _rows(conn, "SELECT minute, rule, outcome FROM decisions WHERE proposal_id IN"
                                           " (SELECT proposal_id FROM proposals WHERE decision_id=?) AND kind='governance'"
                                           " ORDER BY id", (p["decision_id"],))
            refs = json.loads(p["refs_json"])
            out["what_happened_next"] = _after(conn, wf, refs, v["minute"])
    nxt = conn.execute("SELECT version, actor, minute FROM config_versions WHERE wf=? AND version>? ORDER BY version"
                       " LIMIT 1", (wf, v["version"])).fetchone()
    out["superseded_by"] = (f"v{nxt['version']} ({nxt['actor']}) at {_fmt(nxt['minute'])}" if nxt else "still live")
    return out


def _after(conn: sqlite3.Connection, wf: str, refs: dict, since: int) -> list[dict]:
    """Decisions after the change about the same experiment(s) / incident: looks, decay checks, verification."""
    if "experiments" in refs:
        ids = [int(i) for i in refs["experiments"]]
        q = f"experiment_id IN ({','.join('?' * len(ids))})"
        args: list = ids
    elif "incident" in refs:
        q, args = "incident_id=?", [refs["incident"]]
    else:
        q, args = "kind='caller_id'", []
    return _rows(conn, f"SELECT minute, kind, rule, outcome FROM decisions WHERE wf=? AND minute>? AND {q}"
                       " AND kind!='governance' ORDER BY id LIMIT 12", (wf, since, *args))


def explain_lead(conn: sqlite3.Connection, lead_id: str) -> dict:
    lead = conn.execute("SELECT * FROM leads WHERE lead_id=?", (lead_id,)).fetchone()
    if lead is None:
        return {"error": f"unknown lead {lead_id}"}
    attempts = []
    for c in conn.execute("SELECT l.*, v.wm, v.voice, v.caller_id, v.prompt FROM calls_log l JOIN variant_codes v"
                          " ON v.code=l.variant_code WHERE l.lead_int=? ORDER BY minute", (lead["lead_int"],)):
        ver = conn.execute("SELECT actor, proposal_id, approval_id, minute FROM config_versions WHERE wf=? AND version=?",
                           (lead["wf"], c["config_version"])).fetchone()
        if ver is None or ver["actor"] == "business_default":
            why = "business default config (no change by the controller yet)"
        elif ver["actor"] == "supervisor":
            why = f"client supervisor edit (v{c['config_version']}, {_fmt(ver['minute'])})"
        else:
            p = conn.execute("SELECT payload_json, decided_minute FROM proposals WHERE proposal_id=?",
                             (ver["proposal_id"],)).fetchone()
            summary = json.loads(p["payload_json"])["change_summary"] if p else "?"
            how = (f"approved {ver['approval_id']} by the {_tenant(conn, lead['wf'])} approver at {_fmt(p['decided_minute'])}"
                   if ver["approval_id"] else "auto-applied within the workflow's policy")
            why = f"live because proposal {ver['proposal_id']} ({summary}); {how}"
        attempts.append({"attempt": c["attempt_no"], "at": fmt(c["minute"]), "config_version": c["config_version"],
                         "cohort": c["cohort_id"],
                         "heard": {"welcome_message": c["wm"], "voice": c["voice"], "caller_id": c["caller_id"],
                                   "prompt_version": c["prompt"]},
                         "outcome": OUTCOMES.get(c["outcome"], c["outcome"]), "why": why})
    return {"lead": lead_id, "person": lead["person_id"], "workflow": lead["wf"], "campaign": lead["campaign_id"],
            "segment": lead["segment"], "attempts": attempts,
            "note": None if attempts else "no attempts after D0 (history calls are aggregated, not logged per lead)"}


def render(d: dict, indent: int = 0) -> str:
    pad = "  " * indent
    lines = []
    for k, v in d.items():
        if isinstance(v, dict) and not v:
            lines.append(f"{pad}{k}: {{}}")
        elif isinstance(v, dict):
            lines.append(f"{pad}{k}:")
            lines.append(render(v, indent + 1))
        elif isinstance(v, list):
            lines.append(f"{pad}{k}:")
            for item in v:
                if isinstance(item, dict):
                    lines.append(f"{pad}  - " + "; ".join(f"{a}={b}" for a, b in item.items()))
                else:
                    lines.append(f"{pad}  - {item}")
        else:
            lines.append(f"{pad}{k}: {v}")
    return "\n".join(lines)


def _rows(conn, sql, args) -> list[dict]:
    out = []
    for r in conn.execute(sql, args):
        d = dict(r)
        if "minute" in d:
            d["minute"] = _fmt(d["minute"])
        if "inputs_json" in d:
            d["inputs"] = json.loads(d.pop("inputs_json"))
        out.append(d)
    return out


def _fmt(m) -> str | None:
    return None if m is None else fmt(m)


def _tenant(conn, wf) -> str:
    r = conn.execute("SELECT tenant FROM workflows WHERE wf=?", (wf,)).fetchone()
    return r[0] if r else "client"


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("workflow", nargs="?")
    ap.add_argument("--at", help="'D3 14:00'")
    ap.add_argument("--lead")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--db", default=settings.DB_PATH)
    a = ap.parse_args(argv)
    conn = store.connect(a.db)
    if a.lead:
        out = explain_lead(conn, a.lead)
    elif a.workflow and a.at:
        out = explain_version(conn, a.workflow, parse(a.at))
    else:
        ap.error("give WORKFLOW --at 'D3 14:00', or --lead LEAD_ID")
    print(json.dumps(out, indent=2, default=str) if a.json else render(out))


if __name__ == "__main__":
    main()
