"""Supervisor view (C11) and loop health (C14): one page, not fifty alerts.

Sections per workflow: what is being tested, what is winning, what we are asking the approver, what changed today,
what is wrong. `python -m controller view` prints it; `--serve` exposes it as JSON/HTML on :8800 while the loop runs.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from .common import MIN_PER_DAY, fmt_minute


def build_view(store, specs, ing=None, now=None):
    s = store
    if now is None:
        r = s.q1("SELECT MAX(minute) FROM metric")
        now = r[0] if r and r[0] is not None else 0
    today = now // MIN_PER_DAY
    out = {"as_of": fmt_minute(now), "workflows": {}, "loop_health": loop_health(s, now)}
    for wf, spec in specs.items():
        st = s.state(wf)
        base = s.q1("SELECT SUM(dials),SUM(conn),SUM(eng) FROM agg_day WHERE wf=? AND day<0", (wf,))
        rec = s.q1("SELECT SUM(dials),SUM(conn),SUM(eng) FROM agg_day WHERE wf=? AND day>=?", (wf, today - 1))
        r = lambda a, b: round(a / b, 4) if b else None
        exp = {}
        for dim, vs in (st.get("v") or {}).items():
            exp[dim] = {"control": st["control"][dim], "testing_since": (st["epoch"][dim] if st["epoch"][dim] < 10 ** 5 else None),
                        "winning": {f"{vs['feature']}={lvl}": opt for lvl, opt in vs["map"].items()},
                        "stopped_arms": vs["prunes"], "held_until_day": (st.get("hold") or {}).get(dim)}
        asks = [{"proposal": p, "state": state, "summary": summ, "sent": fmt_minute(sent) if sent is not None else None}
                for p, state, summ, sent in s.q(
                    "SELECT proposal_id, state, json_extract(body,'$.change_summary'), sent_min FROM proposal "
                    "WHERE wf=? AND state IN ('intent','pending','approved') ORDER BY created_min", (wf,))]
        changed = [{"at": fmt_minute(m), "kind": k, "what": sm} for m, k, sm in s.q(
            "SELECT minute, kind, summary FROM decision WHERE wf=? AND minute>=? AND kind IN "
            "('applied','supervisor_edit','incident_fix_applied','incident_detected','auto_apply_plan') ORDER BY id",
            (wf, today * MIN_PER_DAY))]
        alerts = [{"at": fmt_minute(m), "severity": sv, "code": c, "message": msg} for m, sv, c, msg in s.q(
            "SELECT minute, severity, code, message FROM alert WHERE wf=? AND minute>=? ORDER BY id DESC LIMIT 10",
            (wf, now - MIN_PER_DAY))]
        incidents = [{"state": stt, "opened": fmt_minute(o), "detail": json.loads(js).get("rate")} for stt, o, js in s.q(
            "SELECT state, opened_min, js FROM incident WHERE wf=? ORDER BY id DESC LIMIT 3", (wf,))]
        out["workflows"][wf] = {
            "primary_kpi": spec["objective"]["primary"], "guardrail": spec["objective"]["guardrail"],
            "kpis_last_2d": {"pickup_rate": r(rec[1], rec[0]) if rec else None,
                             "engagement_rate": r(rec[2], rec[1]) if rec else None},
            "kpis_history_baseline": {"pickup_rate": r(base[1], base[0]) if base else None,
                                      "engagement_rate": r(base[2], base[1]) if base else None},
            "experiments": exp, "waiting_on_approver": asks, "changed_today": changed, "alerts": alerts,
            "incidents": incidents}
    return out


def loop_health(s, now):
    def last(name):
        r = s.q1("SELECT v FROM metric WHERE name=? ORDER BY rowid DESC LIMIT 1", (name,))
        return r[0] if r else None
    dec_h = s.q1("SELECT COUNT(*) FROM decision WHERE minute>?", (now - 60,))[0]
    burn = s.q1("SELECT COALESCE(SUM(credits),0) FROM credit_log")[0]
    return {"ingest_lag_sim_minutes": last("ingest_lag_min"), "decide_seconds_last_tick": last("decide_secs"),
            "decisions_last_sim_hour": dec_h, "credits_remaining": last("credits"), "credits_spent_by_controller": burn,
            "open_proposals": s.q1("SELECT COUNT(*) FROM proposal WHERE state IN ('intent','pending','approved')")[0]}


def serve(store, specs, port=8800):
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            v = build_view(store, specs)
            if self.path.startswith("/health"):
                body, ctype = json.dumps(v["loop_health"]).encode(), "application/json"
            elif self.path.startswith("/view.json"):
                body, ctype = json.dumps(v, default=str, indent=1).encode(), "application/json"
            else:
                body = ("<pre style='font:13px monospace'>" + json.dumps(v, default=str, indent=1) + "</pre>").encode()
                ctype = "text/html"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass
    srv = HTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
