"""Proposal lifecycle. Everything that changes a client's config passes through this file.

State machine for a proposal:

    drafted -> pending -> approved -> applying -> applied
       |          |          |            |
       |          |          |            +-> stale | lapsed
       |          +-> rejected | expired
       +-> stale | invalid

Crash rule: the row recording what we are about to do commits BEFORE the HTTP call. On restart
poll() resumes each row from its status, asking the simulator what really happened. A proposal id
is never reused for different content, so a replay can only ever be the same proposal.
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Callable

from . import config as cfg
from . import configops as co
from . import evidence as ev
from .client import SimError
from .store import Store

log = logging.getLogger("controller.governance")

OPEN = ("drafted", "pending", "approved", "applying")


class Governance:
    def __init__(self, store: Store, client, specs: dict[str, dict], segments: dict[int, dict]):
        self.store, self.client, self.specs, self.segments = store, client, specs, segments
        self.on_applied: dict[str, Callable] = {}
        self.on_dropped: dict[str, Callable] = {}
        # Kinds whose claim can go out of date. These are re-decided rather than re-sent.
        self.on_released: dict[str, Callable] = {}

    # --- intents ------------------------------------------------------------------------------
    def enqueue(self, wid: str, kind: str, priority: int, ops: list[dict], evidence: dict, now: int, key: str) -> str:
        intent_id = f"{wid}:{kind}:{key}"
        self.store.x("INSERT OR IGNORE INTO intents(intent_id,workflow_id,kind,priority,ops,evidence,status,created_minute)"
                     " VALUES(?,?,?,?,?,?, 'queued', ?)", intent_id, wid, kind, priority, json.dumps(ops),
                     json.dumps(evidence, default=str), now)
        return intent_id

    def cancel_intents(self, wid: str, predicate: Callable[[dict], bool], now: int, reason: str) -> int:
        """Stops intents that no longer make sense, even if they sit in a proposal already sent."""
        cancelled = 0
        for r in self.store.q("SELECT * FROM intents WHERE workflow_id=? AND status IN ('queued','in_proposal')", wid):
            if predicate(json.loads(r["evidence"])):
                self.store.x("UPDATE intents SET status='cancelled' WHERE intent_id=?", r["intent_id"])
                self.store.audit(now, wid, "intent_cancelled", f"{r['kind']} cancelled: {reason}",
                                 {"intent_id": r["intent_id"]})
                cancelled += 1
        return cancelled

    def _release(self, proposal_id: str, now: int, reason: str, penalise: bool) -> None:
        """Returns a failed proposal's intents to the queue, to be rebuilt with fresh data."""
        for r in self.store.q("SELECT * FROM intents WHERE proposal_id=? AND status='in_proposal'", proposal_id):
            redecide = self.on_released.get(r["kind"])
            if redecide:
                self.store.x("UPDATE intents SET status='superseded' WHERE intent_id=?", r["intent_id"])
                redecide(dict(r), now, reason)
                continue
            attempts = r["attempts"] + (1 if penalise else 0)
            if attempts >= cfg.MAX_PROPOSAL_ATTEMPTS:
                self.store.x("UPDATE intents SET status='dropped', attempts=? WHERE intent_id=?", attempts, r["intent_id"])
                self.store.audit(now, r["workflow_id"], "intent_dropped",
                                 f"{r['kind']} dropped after {attempts} failed proposals ({reason})",
                                 {"intent_id": r["intent_id"]}, proposal_id)
                handler = self.on_dropped.get(r["kind"])
                if handler:
                    handler(dict(r), now)
            else:
                backoff = cfg.INCIDENT_RETRY_MINUTES if r["kind"] == "incident_fix" else cfg.RETRY_BACKOFF_MINUTES
                not_before = now + (backoff if penalise else 0)
                self.store.x("UPDATE intents SET status='queued', attempts=?, not_before=?, proposal_id=NULL "
                             "WHERE intent_id=?", attempts, not_before, r["intent_id"])

    # --- timing and budget --------------------------------------------------------------------
    def requests_in_24h(self, wid: str, now: int) -> int:
        return self.store.one("SELECT COUNT(*) n FROM proposals WHERE workflow_id=? AND route='approval' "
                              "AND created_minute>?", wid, now - 1440)["n"]

    def request_limit(self, spec: dict) -> int:
        return min(spec["governance"]["max_requests_per_24h"],
                   cfg.prefs_for(spec).get("max_requests_per_24h", 10 ** 6))

    def send_window(self, spec: dict) -> tuple[int, int]:
        """Earliest and latest routine send time, in minutes of the day.

        Latest leaves time for an average-latency decision before approvers leave, so a request
        does not sit overnight in a queue (memo 02).
        """
        gov = spec["governance"]
        start, end = gov["approver_hours"][0] * 60, gov["approver_hours"][1] * 60
        earliest = max(start, cfg.prefs_for(spec).get("earliest_hour", 0) * 60)
        latency = sum(gov["approver_latency_minutes"]) / 2
        return earliest, int(max(earliest, end - latency))

    def can_send(self, spec: dict, now: int, urgent: bool) -> bool:
        minute_of_day = now % 1440
        hours = spec["governance"]["approver_hours"]
        if not hours[0] * 60 <= minute_of_day < hours[1] * 60:
            return False
        if urgent:
            return True
        earliest, latest = self.send_window(spec)
        return earliest <= minute_of_day <= latest

    def auto_allowed(self, spec: dict, dim: str) -> bool:
        auto = spec["governance"]["auto_apply"]
        return bool(auto["enabled"]) and dim in auto["allowed_dims"] and dim in cfg.AUTO_APPLY_DIMS_WE_USE

    # --- composing and sending ----------------------------------------------------------------
    def flush(self, wid: str, now: int) -> None:
        spec = self.specs[wid]
        queued = self.store.q("SELECT * FROM intents WHERE workflow_id=? AND status='queued' AND not_before<=? "
                              "ORDER BY priority DESC, created_minute, intent_id", wid, now)
        if not queued:
            return
        queued = [dict(r) for r in queued]
        self._auto_apply_did(spec, queued, now)
        queued = [q for q in queued if q["status"] == "queued"]
        if not queued:
            return
        urgent = any(q["kind"] == "incident_fix" for q in queued)
        open_rows = self.store.q(f"SELECT status FROM proposals WHERE workflow_id=? AND route='approval' "
                                 f"AND status IN {OPEN}", wid)
        if open_rows and not urgent:
            return
        if urgent:
            queued = [q for q in queued if q["kind"] == "incident_fix"] if open_rows else queued
        if not self.can_send(spec, now, urgent):
            return
        used, limit = self.requests_in_24h(wid, now), self.request_limit(spec)
        allowed = limit if urgent else limit - cfg.INCIDENT_RESERVED_REQUESTS
        if used >= allowed:
            self.store.set_meta(f"budget_blocked:{wid}", now)
            return
        self._send_batch(spec, queued, now)

    def _send_batch(self, spec: dict, intents: list[dict], now: int) -> None:
        wid = spec["workflow_id"]
        current = self.client.config(wid)
        old = current["config"]
        ops = [op for i in intents for op in json.loads(i["ops"])]
        new = co.apply_ops(old, ops)
        ids = [i["intent_id"] for i in intents]
        if new == old:
            with self.store.tx():
                self.store.x(f"UPDATE intents SET status='noop' WHERE intent_id IN ({','.join('?' * len(ids))})", *ids)
                self.store.audit(now, wid, "intent_noop", "queued changes already match the live config", {"intents": ids})
            return
        evs = [json.loads(i["evidence"]) for i in intents]
        affected, by_cohort = ev.affected_leads(self.store, self.segments, spec, old, new, now)
        dry = ev.dry_run(self.store, self.segments, spec, old, new, now)
        value = sum(e.get("value_per_day", 0) for e in evs)
        confidence = max(e.get("confidence", 0.2) for e in evs)
        impact = ev.impact_score(value, confidence, ev.daily_connected(self.store, wid, now))
        validation = next((e["validation_run_id"] for e in evs if e.get("validation_run_id")), None)
        pid = self._proposal_id(wid, ids, now, intents)
        summary = "; ".join(e["summary"] for e in evs)
        body = {
            "proposal_id": pid, "workflow_id": wid, "base_version": current["version"], "proposed_config": new,
            "change_summary": summary[:400], "diff": co.diff(old, new), "affected_leads": affected,
            "dry_run": {**dry, "affected_by_cohort": by_cohort}, "impact_score": impact,
            "rationale": " | ".join(e["rationale"] for e in evs),
            "evidence": {"intents": ids, **({"validation_run_id": validation} if validation else {})},
        }
        with self.store.tx():
            self.store.x("INSERT INTO proposals(proposal_id,workflow_id,route,status,base_version,priority,impact,summary,"
                         "body,created_minute) VALUES(?,?, 'approval','drafted',?,?,?,?,?,?)", pid, wid, current["version"],
                         max(i["priority"] for i in intents), impact, summary, json.dumps(body), now)
            self.store.x(f"UPDATE intents SET status='in_proposal', proposal_id=? WHERE intent_id IN "
                         f"({','.join('?' * len(ids))})", pid, *ids)
            self.store.audit(now, wid, "proposal_drafted", summary,
                             {"impact": impact, "affected_leads": affected, "rationale": body["rationale"],
                              "diff": body["diff"], "dry_run": body["dry_run"], "intents": ids}, pid)
        self._submit(pid, now)

    @staticmethod
    def _proposal_id(wid: str, ids: list[str], now: int, intents: list[dict]) -> str:
        attempt = max(i["attempts"] for i in intents)
        digest = hashlib.sha1("|".join(sorted(ids)).encode()).hexdigest()[:10]
        return f"{wid}-{now}-{digest}-a{attempt}"

    def _submit(self, pid: str, now: int) -> None:
        row = self.store.one("SELECT * FROM proposals WHERE proposal_id=?", pid)
        wid = row["workflow_id"]
        try:
            resp = self.client.request_approval(json.loads(row["body"]))
        except SimError as e:
            if e.code == "duplicate_proposal_id":
                match = next((a for a in self.client.approvals(wid) if a["proposal_id"] == pid), None)
                if match:
                    self._mark_sent(pid, match, now, "recovered")
                return
            if e.code == "stale_base_version":
                self._close(pid, "stale", now, str(e), penalise=False)
                return
            self._close(pid, "invalid", now, str(e), penalise=True)
            return
        self._mark_sent(pid, resp, now, "submitted")

    def _mark_sent(self, pid: str, resp: dict, now: int, how: str) -> None:
        with self.store.tx():
            self.store.x("UPDATE proposals SET status='pending', approval_id=? WHERE proposal_id=? AND status='drafted'",
                         resp["approval_id"], pid)
            row = self.store.one("SELECT workflow_id FROM proposals WHERE proposal_id=?", pid)
            self.store.audit(now, row["workflow_id"], "proposal_sent", f"approval request {how}",
                             {"expires_at": resp.get("expires_at")}, pid, resp["approval_id"])

    def _close(self, pid: str, status: str, now: int, reason, penalise: bool) -> None:
        with self.store.tx():
            row = self.store.one("SELECT workflow_id, approval_id FROM proposals WHERE proposal_id=?", pid)
            self.store.x("UPDATE proposals SET status=?, reasons=?, decided_minute=? WHERE proposal_id=?", status,
                         json.dumps(reason, default=str), now, pid)
            self.store.audit(now, row["workflow_id"], f"proposal_{status}", f"proposal {status}: {reason}", {"reason": reason},
                             pid, row["approval_id"])
            self._release(pid, now, status, penalise)

    # --- progressing open proposals -----------------------------------------------------------
    def poll(self, wid: str, now: int) -> None:
        rows = self.store.q(f"SELECT * FROM proposals WHERE workflow_id=? AND status IN {OPEN} "
                            "ORDER BY priority DESC, created_minute", wid)
        for row in rows:
            status, pid = row["status"], row["proposal_id"]
            if row["route"] == "auto":
                self._resume_auto(row, now)
            elif status == "drafted":
                self._submit(pid, now)
            elif status == "pending":
                self._check_pending(row, now)
            elif status in ("approved", "applying"):
                self._apply(pid, now)

    def _check_pending(self, row, now: int) -> None:
        pid = row["proposal_id"]
        approval = self.client.approval(row["approval_id"])
        status = approval["status"]
        if status == "pending":
            return
        if status == "approved":
            with self.store.tx():
                self.store.x("UPDATE proposals SET status='approved', decided_minute=? WHERE proposal_id=?", now, pid)
                self.store.audit(now, row["workflow_id"], "proposal_approved", "approver said yes",
                                 {"decided_at": approval.get("decided_at"), "apply_by": approval.get("apply_by")},
                                 pid, row["approval_id"])
            self._apply(pid, now)
        elif status == "applied":
            self._finish_apply(pid, now, None)
        elif status in ("rejected", "expired", "lapsed"):
            # Memo 05: an expired proposal is a rejection, so it costs an attempt and is rebuilt.
            self._close(pid, status, now, approval.get("reasons") or status, penalise=True)

    def _apply(self, pid: str, now: int) -> None:
        row = self.store.one("SELECT * FROM proposals WHERE proposal_id=?", pid)
        wid = row["workflow_id"]
        if row["priority"] < 100 and self._incident_proposal_open(wid, pid):
            return  # the incident fix goes first, because applying this would make it stale
        if not self.store.q("SELECT 1 FROM intents WHERE proposal_id=? AND status='in_proposal'", pid):
            self._close(pid, "abandoned", now, "every change in this proposal was cancelled before apply", penalise=False)
            return
        self.store.x("UPDATE proposals SET status='applying' WHERE proposal_id=?", pid)
        try:
            resp = self.client.apply(wid, row["approval_id"])
        except SimError as e:
            if e.code == "not_approved" and isinstance(e.detail, dict) and e.detail.get("status") == "applied":
                self._finish_apply(pid, now, None)  # the earlier attempt landed before a crash
            elif e.code == "stale_base_version":
                self._close(pid, "stale", now, "config changed after proposing", penalise=False)
            elif e.status == 410 or e.code == "not_approved":
                self._close(pid, "lapsed", now, str(e), penalise=True)
            else:
                self._close(pid, "invalid", now, str(e), penalise=True)
            return
        self._finish_apply(pid, now, resp["version"])

    def _incident_proposal_open(self, wid: str, pid: str) -> bool:
        return bool(self.store.q(f"SELECT 1 FROM proposals WHERE workflow_id=? AND priority>=100 AND proposal_id<>? "
                                 f"AND status IN {OPEN}", wid, pid))

    def _finish_apply(self, pid: str, now: int, version: int | None) -> None:
        row = self.store.one("SELECT * FROM proposals WHERE proposal_id=?", pid)
        wid = row["workflow_id"]
        if version is None:
            version = next(h["version"] for h in self.client.config_history(wid) if h["proposal_id"] == pid)
        with self.store.tx():
            self.store.x("UPDATE proposals SET status='applied', applied_minute=?, applied_version=? WHERE proposal_id=?",
                         now, version, pid)
            self._record_config(wid, version, row, now)
            self.store.audit(now, wid, "proposal_applied", f"now live as config v{version}: {row['summary']}",
                             {"version": version}, pid, row["approval_id"])
            for intent in self.store.q("SELECT * FROM intents WHERE proposal_id=? AND status='in_proposal'", pid):
                self.store.x("UPDATE intents SET status='applied' WHERE intent_id=?", intent["intent_id"])
                handler = self.on_applied.get(intent["kind"])
                if handler:
                    handler(dict(intent), version, now)
                # In this transaction, so a crash cannot lose the follow-up request.
                if json.loads(row["body"]).get("_partial"):
                    self._requeue_remainder(dict(intent), now)

    def _record_config(self, wid: str, version: int, row, now: int) -> None:
        body = json.loads(row["body"])
        self.store.x("INSERT INTO config_versions(workflow_id,version,actor,changed_dims,applied_minute,proposal_id,approval_id,"
                     "config) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT DO UPDATE SET config=excluded.config",
                     wid, version, "controller_auto" if row["route"] == "auto" else "controller_approved", json.dumps([]), now,
                     row["proposal_id"], row["approval_id"], json.dumps(body["proposed_config"]))

    # --- auto-apply (operational caller-ID changes only) --------------------------------------
    def _auto_apply_did(self, spec: dict, queued: list[dict], now: int) -> None:
        wid = spec["workflow_id"]
        for intent in queued:
            if intent["kind"] not in ("did_quarantine", "did_explore", "did_promote"):
                continue
            evidence = json.loads(intent["evidence"])
            if evidence.get("approval_only") or not self.auto_allowed(spec, "caller_id"):
                continue
            current = self.client.config(wid)
            old = current["config"]
            target = co.apply_ops(old, json.loads(intent["ops"]))
            limit = spec["governance"]["auto_apply"]["max_shift"]
            partial = co.max_shift(old, target) > limit
            if target == old:
                self.store.x("UPDATE intents SET status='noop' WHERE intent_id=?", intent["intent_id"])
                intent["status"] = "noop"
                continue
            if partial and intent["kind"] != "did_quarantine":
                continue  # exploration that needs more than one step belongs with a human
            new = co.capped_step(old, target, limit) if partial else target
            if set(co.changed_dims(old, new)) - {"caller_id"} or not co.survives_normalisation(new):
                # Auto-apply must only ever touch caller ID. If a write could report anything
                # else as changed, the decision belongs to a person.
                self.store.audit(now, wid, "auto_apply_declined", "write would not be caller-ID only, routing to approval",
                                 {"intent_id": intent["intent_id"], "dims": co.changed_dims(old, new)})
                continue
            pid = self._proposal_id(wid, [intent["intent_id"]], now, [intent]) + "-auto"
            body = {"proposal_id": pid, "base_version": current["version"], "proposed_config": new,
                    "rationale": evidence["rationale"], "_partial": partial}
            with self.store.tx():
                self.store.x("INSERT OR IGNORE INTO proposals(proposal_id,workflow_id,route,status,base_version,priority,impact,"
                             "summary,body,created_minute) VALUES(?,?, 'auto','drafted',?,?,?,?,?,?)", pid, wid, current["version"],
                             intent["priority"], 0.0, evidence["summary"], json.dumps(body), now)
                self.store.x("UPDATE intents SET status='in_proposal', proposal_id=? WHERE intent_id=?", pid, intent["intent_id"])
                self.store.audit(now, wid, "auto_apply_drafted", evidence["summary"],
                                 {"diff": co.diff(old, new), "partial_step": partial, "rationale": evidence["rationale"],
                                  "policy_max_shift": limit}, pid)
            intent["status"] = "in_proposal"
            self._send_auto(pid, now)

    def _send_auto(self, pid: str, now: int) -> None:
        row = self.store.one("SELECT * FROM proposals WHERE proposal_id=?", pid)
        wid = row["workflow_id"]
        request = {k: v for k, v in json.loads(row["body"]).items() if not k.startswith("_")}
        try:
            resp = self.client.auto_apply(wid, request)
        except SimError as e:
            if e.code == "duplicate_proposal_id":
                self._resume_auto(row, now, already_sent=True)
            elif e.code == "stale_base_version":
                self._close(pid, "stale", now, str(e), penalise=False)
            else:
                self._close(pid, "rejected", now, str(e), penalise=True)
            return
        self._finish_apply(pid, now, resp["version"])

    def _requeue_remainder(self, intent: dict, now: int) -> None:
        """The rest of a capped move needs a human. Chaining auto-applies would evade max_shift."""
        evidence = json.loads(intent["evidence"])
        evidence["approval_only"] = True
        evidence["summary"] = "finish moving traffic off a caller ID (first step was auto-applied within policy limits)"
        self.enqueue(intent["workflow_id"], intent["kind"], intent["priority"], json.loads(intent["ops"]), evidence, now,
                     f"remainder-{now}")

    def _resume_auto(self, row, now: int, already_sent: bool = False) -> None:
        pid = row["proposal_id"]
        hist = next((h for h in self.client.config_history(row["workflow_id"]) if h["proposal_id"] == pid), None)
        if hist:
            self._finish_apply(pid, now, hist["version"])
        elif not already_sent:
            self._send_auto(pid, now)
