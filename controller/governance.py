"""Governance client (C9): the only code path that changes a client's config.

Proposal state machine (persisted; every outward call is preceded by a durable `intent` row):

    intent --POST ok--> pending --approved--> approved --apply ok--> applied
       |                   |  \\--rejected--> rejected                  \\-- 409 stale --> stale
       |                   \\--expired--> expired                        \\-- 410 --------> lapsed
       \\-- 409/422/other --> void/failed

* an expired/rejected/stale/lapsed proposal is NEVER re-sent: the planner re-plans from fresh data and the
  new proposal gets a new id (Product memo: "an expired proposal is a rejection").
* at most one outstanding approval per workflow, so our own writes can never make an approval stale.
* every state change is also written to the decision log so "why" can be answered from our own store.
"""
from __future__ import annotations

import hashlib
import json
import os

from .common import MIN_PER_DAY, minute_of
from .simclient import ApiError, Sim
from .store import Store

OPEN_STATES = ("intent", "pending", "approved")

# Client-stated preferences (stakeholder memos), applied on top of the simulator's policy, never against it.
TENANT_PREFS = {
    "kestrel_finance": {"min_send_hour": 11, "max_requests_per_day": 2},   # memo 04 (Anita Desai)
}


def crash_point(name: str):
    """Test hook for scripts/crash_test.py: die exactly once at a named point between an outward call and the
    bookkeeping that records it. A flag file next to the DB makes it fire once per point."""
    if os.environ.get("CTL_CRASH_POINT") != name:
        return
    flag = os.environ.get("CTL_CRASH_FLAG", "") + "." + name
    if flag and not os.path.exists(flag):
        open(flag, "w").close()
        os._exit(137)


def cfg_hash(cfg: dict) -> str:
    return hashlib.sha1(json.dumps(cfg, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:10]


class Gov:
    def __init__(self, store: Store, sim: Sim, on_applied=None):
        self.s, self.sim, self.on_applied = store, sim, on_applied

    # ------------------------------------------------------------------ policy helpers
    @staticmethod
    def prefs(spec: dict) -> dict:
        return TENANT_PREFS.get(spec["tenant_id"], {})

    def window_ok(self, spec: dict, now: int) -> bool:
        lo, hi = spec["governance"]["approver_hours"]
        lo = max(lo, self.prefs(spec).get("min_send_hour", lo))
        hour = (now % MIN_PER_DAY) // 60
        return lo <= hour < hi

    def requests_last_24h(self, wf: str, now: int) -> int:
        return self.s.q1("SELECT COUNT(*) FROM proposal WHERE wf=? AND kind='approval' AND sent_min IS NOT NULL "
                         "AND sent_min>?", (wf, now - MIN_PER_DAY))[0]

    def request_budget(self, spec: dict, now: int, urgent: bool = False) -> int:
        """Requests we may still send. Routine plans keep one slot in reserve for incidents; the client's own
        cap (e.g. Kestrel: 2/day) applies to routine plans, the policy cap to everything."""
        policy = spec["governance"].get("max_requests_per_24h", 3)
        used = self.requests_last_24h(spec["workflow_id"], now)
        if urgent:
            return policy - used
        client = min(policy, self.prefs(spec).get("max_requests_per_day", policy))
        return (client - 1 if client > 1 else client) - used

    def outstanding(self, wf: str):
        return self.s.q("SELECT proposal_id, state, kind FROM proposal WHERE wf=? AND state IN ('intent','pending','approved')",
                        (wf,))

    # ------------------------------------------------------------------ submit
    def _new_id(self, wf: str, base: int, h: str) -> str:
        n = self.s.q1("SELECT COUNT(*) FROM proposal WHERE wf=? AND base_version=? AND cfg_hash=?", (wf, base, h))[0]
        return f"{wf}.v{base}.{h}.a{n}"

    def submit_approval(self, spec, now, cfg, base_version, *, summary, diff, affected, dry_run, impact, rationale,
                        evidence=None, state_patch=None, decision_id=None, dims=()):
        wf = spec["workflow_id"]
        h = cfg_hash(cfg)
        pid = self._new_id(wf, base_version, h)
        body = {"proposal_id": pid, "workflow_id": wf, "base_version": base_version, "proposed_config": cfg,
                "change_summary": summary, "diff": diff, "affected_leads": int(affected), "dry_run": dry_run,
                "impact_score": round(float(max(0.0, min(1.0, impact))), 3), "rationale": rationale}
        if evidence:
            body["evidence"] = evidence
        # the request must be durable before it leaves the process
        self.s.x("INSERT INTO proposal(proposal_id,wf,kind,state,base_version,config,body,state_patch,decision_id,"
                 "created_min,dims,cfg_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                 (pid, wf, "approval", "intent", base_version, json.dumps(cfg), json.dumps(body),
                  json.dumps(state_patch or {}), decision_id, now, json.dumps(list(dims)), h))
        self._send(wf, pid, now)
        return pid

    def _send(self, wf: str, pid: str, now: int):
        row = self.s.q1("SELECT body FROM proposal WHERE proposal_id=?", (pid,))
        body = json.loads(row[0])
        try:
            r = self.sim.post("/approvals", body)
        except ApiError as e:
            if e.code == "duplicate_proposal_id":      # we crashed after the POST: adopt the existing approval
                for a in self.sim.approvals(wf):
                    if a["proposal_id"] == pid:
                        self._mark_sent(pid, a, now)
                        return
                self._set(pid, "failed", reasons=["duplicate id but approval not found"])
            elif e.code == "stale_base_version":
                self._set(pid, "stale", reasons=["stale at send"])
            elif e.code == "no_change":
                self._set(pid, "void", reasons=["no change"])
            else:
                self._set(pid, "failed", reasons=[str(e)])
                self.s.alert(now, wf, "warn", "approval_request_failed", f"{pid}: {e}")
            return
        crash_point("after_approval_post")
        self._mark_sent(pid, r, now)

    def _mark_sent(self, pid, a, now):
        self.s.x("UPDATE proposal SET state='pending', approval_id=?, sent_min=? WHERE proposal_id=?",
                 (a["approval_id"], now, pid))

    def _set(self, pid, state, **kw):
        sets, args = ["state=?"], [state]
        for k, v in kw.items():
            sets.append(f"{k}=?")
            args.append(json.dumps(v) if k == "reasons" else v)
        args.append(pid)
        self.s.x(f"UPDATE proposal SET {', '.join(sets)} WHERE proposal_id=?", args)

    # ------------------------------------------------------------------ auto-apply (policy-permitted only)
    def submit_auto(self, spec, now, cfg, base_version, *, rationale, evidence=None, state_patch=None,
                    decision_id=None, dims=()):
        wf = spec["workflow_id"]
        h = cfg_hash(cfg)
        pid = self._new_id(wf, base_version, h)
        body = {"proposal_id": pid, "base_version": base_version, "proposed_config": cfg, "rationale": rationale}
        if evidence:
            body["evidence"] = evidence
        self.s.x("INSERT INTO proposal(proposal_id,wf,kind,state,base_version,config,body,state_patch,decision_id,"
                 "created_min,dims,cfg_hash) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                 (pid, wf, "auto", "intent", base_version, json.dumps(cfg), json.dumps(body),
                  json.dumps(state_patch or {}), decision_id, now, json.dumps(list(dims)), h))
        return self._put(wf, pid, now)

    def _put(self, wf: str, pid: str, now: int):
        body = json.loads(self.s.q1("SELECT body FROM proposal WHERE proposal_id=?", (pid,))[0])
        try:
            r = self.sim.put(f"/workflows/{wf}/config", body)
        except ApiError as e:
            if e.code == "duplicate_proposal_id":
                v = next((x for x in self.sim.config_history(wf) if x.get("proposal_id") == pid), None)
                if v:
                    self._applied(pid, wf, v["version"], now)
                    return True
                self._set(pid, "failed", reasons=["duplicate id but no matching version"])
            elif e.status == 403:
                self._set(pid, "failed", reasons=e.body.get("detail") if isinstance(e.body, dict) else [str(e)])
                self.s.alert(now, wf, "warn", "auto_apply_refused", f"{pid}: {e.body}")
            elif e.code == "stale_base_version":
                self._set(pid, "stale", reasons=["stale at send"])
            else:
                self._set(pid, "failed", reasons=[str(e)])
            return False
        crash_point("after_auto_put")
        self._applied(pid, wf, r["version"], now)
        return True

    def _applied(self, pid, wf, version, now):
        self.s.x("UPDATE proposal SET state='applied', applied_version=?, applied_min=? WHERE proposal_id=?",
                 (version, now, pid))
        if self.on_applied:
            self.on_applied(wf, pid, now)

    # ------------------------------------------------------------------ reconcile (every tick, and at startup)
    def reconcile(self, spec: dict, now: int):
        wf = spec["workflow_id"]
        for pid, state, kind in self.outstanding(wf):
            if state == "intent":
                self._recover_intent(wf, pid, kind, now)
        rows = self.s.q("SELECT proposal_id, approval_id FROM proposal WHERE wf=? AND state='pending'", (wf,))
        for pid, aid in rows:
            a = self.sim.get(f"/approvals/{aid}")
            st = a["status"]
            if st == "pending":
                continue
            dec_min = minute_of(a["decided_at"]) if a.get("decided_at") else now
            if st == "approved":
                self.s.x("UPDATE proposal SET state='approved', decided_min=?, reasons=? WHERE proposal_id=?",
                         (dec_min, json.dumps(a.get("reasons") or []), pid))
            elif st in ("rejected", "expired"):
                self.s.x("UPDATE proposal SET state=?, decided_min=?, reasons=? WHERE proposal_id=?",
                         (st, dec_min, json.dumps(a.get("reasons") or []), pid))
                self.s.decision(now, wf, f"proposal_{st}", f"{pid} {st}: {a.get('reasons')}",
                                outputs={"approval_id": aid}, proposal_id=pid)
            elif st == "applied":     # crashed between apply and bookkeeping
                self._adopt_applied(wf, pid, aid, now)
            elif st == "lapsed":
                self._set(pid, "lapsed")
        for pid, aid in self.s.q("SELECT proposal_id, approval_id FROM proposal WHERE wf=? AND state='approved'", (wf,)):
            self._apply(wf, pid, aid, now)

    def _recover_intent(self, wf, pid, kind, now):
        """We died between writing the intent row and learning the outcome. Ask the simulator what happened."""
        base, body = self.s.q1("SELECT base_version, body FROM proposal WHERE proposal_id=?", (pid,))
        if kind == "approval":
            for a in self.sim.approvals(wf):
                if a["proposal_id"] == pid:           # the POST landed: adopt it, never re-send
                    self._mark_sent(pid, a, now)
                    return
        else:
            v = next((x for x in self.sim.config_history(wf) if x.get("proposal_id") == pid), None)
            if v:                                      # the PUT landed
                self._applied(pid, wf, v["version"], now)
                return
        # it never reached the simulator: send only if the base version is still current, else it is stale
        if self.sim.config(wf)["version"] != base:
            self._set(pid, "stale", reasons=["config moved while we were down"])
            return
        if kind == "approval":
            self._send(wf, pid, now)
        else:
            self._put(wf, pid, now)

    def _adopt_applied(self, wf, pid, aid, now):
        v = next((x for x in self.sim.config_history(wf) if x.get("approval_id") == aid), None)
        self._applied(pid, wf, v["version"] if v else -1, now)

    def _apply(self, wf, pid, aid, now):
        try:
            r = self.sim.post(f"/workflows/{wf}/apply", {"approval_id": aid})
        except ApiError as e:
            if e.code == "stale_base_version":
                self._set(pid, "stale", reasons=["config changed after the proposal (supervisor edit or other write)"])
                self.s.decision(now, wf, "proposal_stale", f"{pid} went stale before apply: re-plan from fresh data",
                                proposal_id=pid)
                self.s.alert(now, wf, "info", "stale_base", f"{pid} stale; will re-propose")
            elif e.status == 410:
                self._set(pid, "lapsed", reasons=["not applied inside apply window"])
                self.s.alert(now, wf, "warn", "approval_lapsed", f"{pid} lapsed: apply window missed")
            elif e.code == "not_approved":
                a = self.sim.get(f"/approvals/{aid}")
                if a["status"] == "applied":
                    self._adopt_applied(wf, pid, aid, now)
            else:
                self.s.alert(now, wf, "warn", "apply_failed", f"{pid}: {e}")
            return
        crash_point("after_apply_post")
        self._applied(pid, wf, r["version"], now)
