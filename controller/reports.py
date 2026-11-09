"""Read-only answers from the controller's own store. Safe to run while the loop is writing."""
from __future__ import annotations

import glob
import gzip
import json
import os
import re

from .store import Store, ts_of


def parse_when(text: str) -> int:
    """Accepts 'D3 14:00' or an ISO timestamp."""
    m = re.fullmatch(r"D(\d+)(?:\s+(\d{1,2}):(\d{2}))?", text.strip())
    if m:
        return int(m[1]) * 1440 + int(m[2] or 0) * 60 + int(m[3] or 0)
    from .store import minute_of
    return minute_of(text if "+" in text else text + "+05:30")


def _kpis(store: Store, wid: str, version: int) -> dict | None:
    r = store.one("SELECT SUM(dials) d, SUM(connected) c, SUM(engaged) e, SUM(halluc) h FROM fact_arm WHERE workflow_id=? AND config_version=?", wid, version)
    if not r["d"]:
        return None
    return {"dials": r["d"], "pickup_rate": round(r["c"] / r["d"], 4), "engagement_rate": round(r["e"] / r["c"], 4) if r["c"] else None,
            "hallucination_flag_rate": round(r["h"] / r["c"], 4) if r["c"] else None}


def why(store: Store, wid: str, at: int, tolerance_minutes: int = 240) -> str:
    """Why did this workflow change around this time, who approved it, what happened next?"""
    rows = store.q("SELECT * FROM config_versions WHERE workflow_id=? AND applied_minute BETWEEN ? AND ? AND version>1 ORDER BY ABS(applied_minute-?)",
                   wid, at - tolerance_minutes, at + tolerance_minutes, at)
    if not rows:
        return f"No config change on {wid} within {tolerance_minutes} minutes of {ts_of(at)}."
    v = rows[0]
    out = [f"# {wid}: config v{v['version']} at {ts_of(v['applied_minute'])}", f"Changed by: {v['actor']}",
           f"Dimensions: {', '.join(json.loads(v['changed_dims'])) or 'see diff below'}"]
    if v["proposal_id"]:
        p = store.one("SELECT * FROM proposals WHERE proposal_id=?", v["proposal_id"])
        if p:
            body = json.loads(p["body"])
            out += ["", "## Why", p["summary"], "", f"Rationale: {body.get('rationale')}", f"Impact score: {p['impact']}  Affected leads: {body.get('affected_leads')}",
                    "", "## Who approved it"]
            if p["route"] == "auto":
                out.append("Nobody: auto-applied inside the workflow's signed policy.")
            else:
                out.append(f"Approval {p['approval_id']}, requested {ts_of(p['created_minute'])}, decided {ts_of(p['decided_minute'])}.")
                out.append("The simulator's API does not expose the approver's name, so the approval id is the identifier we hold.")
            out += ["", "## Diff", json.dumps(body.get("diff"), indent=2), "", "## Dry run shown to the approver", json.dumps(body.get("dry_run"), indent=2)]
    else:
        out += ["", "## Why", "A supervisor edited the config directly. Supervisor edits bypass governance, and the controller did not initiate this one."]
    out += ["", "## What happened next", f"KPIs before (v{v['version'] - 1}): {_kpis(store, wid, v['version'] - 1)}", f"KPIs after  (v{v['version']}): {_kpis(store, wid, v['version'])}", "",
            "Decisions in the following 24 hours:"]
    for d in store.q("SELECT ts, kind, summary FROM decisions WHERE workflow_id=? AND minute>=? AND minute<=? AND kind NOT IN ('decay_check','experiment_look') ORDER BY id LIMIT 40",
                     wid, v["applied_minute"], v["applied_minute"] + 1440):
        out.append(f"- {d['ts']}  {d['kind']}: {d['summary']}")
    return "\n".join(out)


def why_call(store: Store, archive_dir: str, lead_id: str, day: int | None = None) -> str:
    """Why did this person hear what they heard? Scans the raw event archive (memo 02, item 3)."""
    wid = lead_id.split(":")[0]
    out = [f"# Calls to {lead_id}"]
    found = 0
    for path in sorted(glob.glob(os.path.join(archive_dir, "*.ndjson.gz"))):
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                if lead_id not in line:
                    continue
                ev = json.loads(line)
                if ev.get("type") != "call" or ev.get("lead_id") != lead_id:
                    continue
                if day is not None and not ev["ts"].startswith(ts_of(day * 1440)[:10]):
                    continue
                found += 1
                version = ev["config_version"]
                cv = store.one("SELECT actor, proposal_id, approval_id FROM config_versions WHERE workflow_id=? AND version=?", wid, version)
                p = store.one("SELECT summary FROM proposals WHERE proposal_id=?", cv["proposal_id"]) if cv and cv["proposal_id"] else None
                out.append(f"- {ev['ts']} attempt {ev['attempt_no']}: {ev['variant']} cohort={ev['cohort_id']} config v{version}, connected={ev['connected']}, engaged={ev['engaged']}")
                reason = p["summary"] if p else ("business default" if version == 1 else "supervisor edit" if cv and cv["actor"] == "supervisor" else "unknown")
                out.append(f"  live because: {reason}" + (f" (approval {cv['approval_id']})" if cv and cv["approval_id"] else ""))
    return "\n".join(out) if found else f"No calls found for {lead_id}."


def supervisor_view(store: Store, wid: str, now: int | None = None) -> str:
    """One screen (memo 04): what is being tested, what is winning, what we need, what changed."""
    if now is None:
        now = store.get_meta("last_minute", 0)
    day = now // 1440
    out = [f"# {wid} at {ts_of(now)}", "", "## KPIs today (never blended)"]
    r = store.one("SELECT SUM(dials) d, SUM(connected) c, SUM(engaged) e FROM fact_arm WHERE workflow_id=? AND day=?", wid, day)
    if r["d"]:
        out.append(f"Pickup {r['c'] / r['d']:.1%} of {r['d']} dials.  Engagement {(r['e'] / r['c']) if r['c'] else 0:.1%} of {r['c']} connected.")
    o = store.one("SELECT SUM(cs.leads) l, SUM(cs.concluded) c FROM campaign_seg cs JOIN campaigns c ON c.campaign_id=cs.campaign_id WHERE c.workflow_id=? AND c.created_minute>=0", wid)
    if o["l"]:
        out.append(f"Leads concluded since D0: {o['c']} of {o['l']} ({o['c'] / o['l']:.1%}).")
    out += ["", "## Needs you"]
    pending = store.q("SELECT * FROM proposals WHERE workflow_id=? AND status IN ('pending','approved') ORDER BY impact DESC", wid)
    out += [f"- [impact {p['impact']:.2f}] {p['summary']} ({p['status']})" for p in pending] or ["Nothing."]
    out += ["", "## Being tested"]
    tests = store.q("SELECT e.*, (SELECT detail FROM decisions d WHERE d.workflow_id=e.workflow_id AND d.kind='experiment_look' AND d.detail LIKE '%' || e.exp_id || '%' ORDER BY d.id DESC LIMIT 1) last "
                    "FROM experiments e WHERE e.workflow_id=? AND e.status='running'", wid)
    for t in tests:
        line = f"- {t['dim']} for {t['cohort_id']}: {json.loads(t['arms'])} vs {json.loads(t['control'])}"
        if t["last"]:
            arms = json.loads(t["last"]).get("arms", {})
            line += "  " + ", ".join(f"{a} {s['lift']:+.1%}" for a, s in arms.items())
        out.append(line)
    if not tests:
        out.append("Nothing running.")
    out += ["", "## Winning"]
    promos = store.q("SELECT * FROM promotions WHERE workflow_id=? AND status='active'", wid)
    out += [f"- {p['dim']}={p['winner']} for {p['cohort_id']} (holdout {p['holdout']}, lift at promotion {p['lift_at_promotion']:+.3f})" for p in promos] or ["No promoted winners."]
    out += ["", "## Incidents"]
    inc = store.q("SELECT * FROM incidents WHERE workflow_id=? AND (status='open' OR closed_minute>=?)", wid, day * 1440)
    out += [f"- {i['kind']} on {i['subject']}: {i['status']}, phase {json.loads(i['detail']).get('phase')}" for i in inc] or ["None."]
    dids = store.q("SELECT did, since_minute FROM did_status WHERE workflow_id=?", wid)
    out += [f"- caller ID {d['did']} quarantined since {ts_of(d['since_minute'])}" for d in dids]
    out += ["", "## Changed today"]
    changes = store.q("SELECT * FROM config_versions WHERE workflow_id=? AND applied_minute>=? AND version>1 ORDER BY version", wid, day * 1440)
    for c in changes:
        p = store.one("SELECT summary FROM proposals WHERE proposal_id=?", c["proposal_id"]) if c["proposal_id"] else None
        out.append(f"- {ts_of(c['applied_minute'])[11:16]} v{c['version']} by {c['actor']}: {p['summary'] if p else 'supervisor edit'}")
    if not changes:
        out.append("No changes.")
    return "\n".join(out)


def health(store: Store) -> str:
    """The loop's own vital signs, without reading logs (memo 03)."""
    last = store.get_meta("last_minute")
    if last is None:
        return "Controller has not completed a tick yet."
    m = store.one("SELECT * FROM metrics ORDER BY minute DESC LIMIT 1")
    window = store.one("SELECT SUM(events) e, SUM(ingest_ms) i, SUM(decide_ms) d, MAX(decide_ms) md, COUNT(*) n, MAX(rss_mb) r FROM metrics WHERE minute>?", last - 1440)
    decisions = store.one("SELECT COUNT(*) n FROM decisions WHERE minute>?", last - 60)["n"]
    spend = store.q("SELECT purpose, SUM(cost) c FROM credit_ledger GROUP BY purpose")
    chunk = store.one("SELECT MAX(chunk) c, SUM(events) e FROM chunks")
    out = [f"sim time {ts_of(last)}", f"events ingested total {chunk['e']}, last chunk {chunk['c']}",
           f"ingest rate (last sim day) {window['e'] * 1000 / max(window['i'], 1):.0f} events/s", f"decide time per tick: avg {window['d'] / window['n']:.0f} ms, max {window['md']} ms",
           f"decisions in the last sim hour {decisions}", f"credits remaining {m['credits']:.0f}; spent: " + (", ".join(f"{s['purpose']} {s['c']:.0f}" for s in spend) or "none"),
           f"peak memory {window['r']:.0f} MB", "", "open alerts:"]
    alerts = store.q("SELECT * FROM alerts WHERE closed=0 ORDER BY severity, alert_key")
    out += [f"- [{a['severity'].upper()}] {a['message']}" for a in alerts] or ["- none"]
    return "\n".join(out)
