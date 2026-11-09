"""Proposal state machine (SUBMISSION §6). Every state change is committed, with its audit row, *before* the HTTP
call it leads to. After a crash or an unknown outcome the row is still in its intent state (SUBMITTING,
APPLYING, AUTO_APPLYING) and the next step reconciles it against the authoritative endpoint before retrying.

    DRAFT ─► SUBMITTING ─► PENDING ─► APPROVED ─► APPLYING ─► APPLIED
      │                       ├─► REJECTED            ├─► LAPSED
      │                       └─► EXPIRED             └─► STALE ─► new DRAFT on the current base
      └─► AUTO_APPLYING ─► APPLIED | STALE | NOT_PERMITTED (─► approval DRAFT)
    DRAFT ─► DROPPED (re-check before submission failed)

Owners (experiments, detectors, incidents) create drafts as *patches*, not full configs, so a stale draft can be
rebased mechanically. Owners hear back through `on_applied` / `on_terminal` and re-check through `revalidate`.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Protocol

from . import configs, impact, policy, store
from .clock import Clock
from .sim_client import SimClient

IN_FLIGHT = ("SUBMITTING", "PENDING", "APPROVED", "APPLYING", "AUTO_APPLYING")
TERMINAL = ("APPLIED", "REJECTED", "EXPIRED", "LAPSED", "STALE", "NOT_PERMITTED", "DROPPED")


class Owner(Protocol):
    def revalidate(self, conn: sqlite3.Connection, p: sqlite3.Row, minute: int) -> tuple[bool, str]: ...
    def on_applied(self, conn: sqlite3.Connection, p: sqlite3.Row, version: int, minute: int) -> None: ...
    def on_terminal(self, conn: sqlite3.Connection, p: sqlite3.Row, state: str, minute: int) -> None: ...


# ---------------------------------------------------------------------------- drafting
def draft(conn: sqlite3.Connection, minute: int, wf: str, kind: str, patch: dict, payload: dict, *,
          owner: str, refs: dict, decision_id: int, path: str = "approval", urgent: bool = False,
          parent: str | None = None) -> str:
    """payload: change_summary, rationale, impact_score, optional evidence / dry_run_extra. Returns proposal_id."""
    attempt = conn.execute("SELECT COUNT(*) FROM proposals WHERE decision_id=?", (decision_id,)).fetchone()[0] + 1
    pid = f"{wf}:{decision_id}:{attempt}"
    conn.execute("INSERT INTO proposals(proposal_id, wf, kind, path, state, urgent, patch_json, payload_json,"
                 " refs_json, created_minute, decision_id, parent_proposal_id, updated_minute)"
                 " VALUES(?,?,?,?, 'DRAFT', ?,?,?,?,?,?,?,?)",
                 (pid, wf, kind, path, int(urgent), json.dumps(patch), json.dumps(payload),
                  json.dumps({"owner": owner, **refs}), minute, decision_id, parent, minute))
    return pid


# ---------------------------------------------------------------------------- the step
class Governance:
    def __init__(self, conn: sqlite3.Connection, client: SimClient, clock: Clock, specs: dict[str, dict],
                 owners: dict[str, Owner]):
        self.conn, self.client, self.clock, self.specs, self.owners = conn, client, clock, specs, owners
        self.after_commit = lambda state: None      # test hook: the crash test kills the process here

    def step(self, minute: int) -> None:
        for wf in self.specs:
            self.reconcile(wf, minute)
            self._submit_drafts(wf, minute)

    # -------------------------------------------------------------- reconcile in-flight rows
    def reconcile(self, wf: str, minute: int) -> None:
        rows = self.conn.execute(f"SELECT * FROM proposals WHERE wf=? AND state IN ({_q(IN_FLIGHT)})"
                                 " ORDER BY created_minute", (wf,)).fetchall()
        if not rows:
            return
        history = None
        approvals = None
        for p in rows:
            state = p["state"]
            if state == "SUBMITTING":
                approvals = approvals if approvals is not None else self.client.approvals(wf)
                landed = next((a for a in approvals if a["proposal_id"] == p["proposal_id"]), None)
                if landed:
                    self._set(p, "PENDING", minute, "reconcile: request found by proposal_id",
                              approval_id=landed["approval_id"])
                    p = self._row(p["proposal_id"])
                    state = "PENDING"
                else:
                    self._post_approval(p, minute)         # never landed: safe to send again, same id
                    continue
            if state == "PENDING":
                a = self.client.approval(p["approval_id"])
                if a["status"] == "approved":
                    self._set(p, "APPROVED", minute, "approver approved",
                              apply_by_minute=self.clock.minute(a["apply_by"]),
                              decided_minute=self.clock.minute(a["decided_at"]))
                    p, state = self._row(p["proposal_id"]), "APPROVED"
                elif a["status"] in ("rejected", "expired"):
                    self._finish(p, a["status"].upper(), minute, f"approver: {a['status']}",
                                 reasons=json.dumps(a.get("reasons") or []),
                                 decided_minute=self.clock.minute(a["decided_at"]) if a.get("decided_at") else minute)
                    continue
                else:
                    continue
            if state in ("APPROVED", "APPLYING"):
                history = history if history is not None else self.client.config_history(wf)
                done = next((h for h in history if h["approval_id"] == p["approval_id"]), None)
                if done:
                    self._applied(p, done["version"], minute, "reconcile: approval found in config history")
                elif p["apply_by_minute"] is not None and minute > p["apply_by_minute"]:
                    self._finish(p, "LAPSED", minute, "missed apply_by")
                else:
                    self._apply_approved(p, minute)
                    history = None                          # the config may have moved: re-read for the next row
            elif state == "AUTO_APPLYING":
                history = history if history is not None else self.client.config_history(wf)
                done = next((h for h in history if h["proposal_id"] == p["proposal_id"]), None)
                if done:
                    self._applied(p, done["version"], minute, "reconcile: proposal found in config history")
                else:
                    self._put_auto(p, minute)
                    history = None

    # -------------------------------------------------------------- submit drafts
    def _submit_drafts(self, wf: str, minute: int) -> None:
        drafts = self.conn.execute("SELECT * FROM proposals WHERE wf=? AND state='DRAFT'"
                                   " ORDER BY urgent DESC, created_minute, proposal_id", (wf,)).fetchall()
        spec = self.specs[wf]
        for p in drafts:
            touched = self._supervisor_dims_since(wf, p["created_minute"]) & configs.patch_dims(json.loads(p["patch_json"]))
            if touched:
                self._finish(p, "DROPPED", minute, f"supervisor edited {sorted(touched)} after drafting: their change stands")
                continue
            owner = self.owners[json.loads(p["refs_json"])["owner"]]
            ok, why = owner.revalidate(self.conn, p, minute)
            if not ok:
                self._finish(p, "DROPPED", minute, f"re-check before submission failed: {why}")
                continue
            base, cur = configs.current(self.conn, wf)
            new = configs.apply_patch(cur, json.loads(p["patch_json"]))
            if not configs.changed_dims(cur, new):
                self._finish(p, "DROPPED", minute, "patch is already live")
                continue
            if p["path"] == "auto":
                ok, reasons = policy.auto_apply_eligible(spec, cur, new)
                if not ok:              # the world moved since drafting: go through approval instead
                    self._fallback_to_approval(p, minute, reasons, page=False)
                    continue
                self._set(p, "AUTO_APPLYING", minute, "auto-apply eligible locally", base_version=base,
                          config_json=json.dumps(new))
                self._put_auto(self._row(p["proposal_id"]), minute)
                continue
            urgent = bool(p["urgent"])
            if not urgent and self._routine_in_flight(wf):
                continue                # one routine request at a time per workflow; it batches every change
            can, why = policy.can_submit_now(spec, minute, urgent)
            if not can:
                continue
            if policy.quota_left(self.conn, spec, wf, minute, urgent,
                                 safety_incident=p["kind"] == "incident_fix") <= 0:
                continue
            payload = json.loads(p["payload_json"])
            body = {
                "proposal_id": p["proposal_id"], "workflow_id": wf, "base_version": base, "proposed_config": new,
                "change_summary": payload["change_summary"], "rationale": payload["rationale"],
                "diff": impact.diff(cur, new),
                "affected_leads": impact.affected_leads(self.conn, spec, cur, new, minute),
                "dry_run": impact.dry_run(self.conn, wf, cur, new, minute, payload.get("dry_run_extra")),
                "impact_score": round(float(payload["impact_score"]), 4),
                "expires_in_hours": policy.expires_in_hours(spec, minute, urgent),
            }
            if payload.get("evidence"):
                body["evidence"] = payload["evidence"]
            self._set(p, "SUBMITTING", minute, f"submitting: {why}", base_version=base, config_json=json.dumps(new),
                      payload_json=json.dumps({**payload, "body": {k: v for k, v in body.items()
                                                                   if k != "proposed_config"}}),
                      submitted_minute=minute)
            self._post_approval(self._row(p["proposal_id"]), minute)

    def _supervisor_dims_since(self, wf: str, minute: int) -> set[str]:
        rows = self.conn.execute("SELECT changed_dims FROM config_versions WHERE wf=? AND actor='supervisor'"
                                 " AND minute>=?", (wf, minute)).fetchall()
        return {d for r in rows for d in json.loads(r[0])}

    def _routine_in_flight(self, wf: str) -> bool:
        return self.conn.execute(f"SELECT 1 FROM proposals WHERE wf=? AND urgent=0 AND path='approval'"
                                 f" AND state IN ({_q(IN_FLIGHT)})", (wf,)).fetchone() is not None

    # -------------------------------------------------------------- HTTP calls (intent already committed)
    def _post_approval(self, p: sqlite3.Row, minute: int) -> None:
        payload = json.loads(p["payload_json"])
        body = {**payload["body"], "proposed_config": json.loads(p["config_json"])}
        r = self.client.submit_approval(body)
        if r.status is None:
            return                                          # unknown: reconcile next step
        if r.ok:
            self._set(p, "PENDING", minute, "request accepted", approval_id=r.json["approval_id"])
        elif r.code == "duplicate_proposal_id":
            return                                          # it landed earlier; reconcile picks it up
        elif r.code == "stale_base_version":
            self._set(p, "DRAFT", minute, "stale base at submit: will rebuild on the current base",
                      submitted_minute=None)
        else:
            self._finish(p, "DROPPED", minute, f"request refused: {r.status} {r.json}")

    def _apply_approved(self, p: sqlite3.Row, minute: int) -> None:
        if p["state"] != "APPLYING":
            self._set(p, "APPLYING", minute, "applying approved change")
        r = self.client.apply(p["wf"], p["approval_id"])
        if r.status is None:
            return
        if r.ok:
            self._applied(p, r.json["version"], minute, "applied")
        elif r.status == 410:
            self._finish(p, "LAPSED", minute, "approval lapsed before apply")
        elif r.code == "stale_base_version":
            self._stale(p, minute)
        elif r.code == "not_approved":
            status = (r.json.get("detail") or {}).get("status")
            final = {"lapsed": "LAPSED", "rejected": "REJECTED", "expired": "EXPIRED"}
            if status in final:
                self._finish(p, final[status], minute, f"apply refused: {r.json}")
            # applied: config history shows it on the next reconcile; anything else: not final, reconcile again
        else:
            self._finish(p, "DROPPED", minute, f"apply refused: {r.status} {r.json}")

    def _put_auto(self, p: sqlite3.Row, minute: int) -> None:
        r = self.client.auto_apply(p["wf"], {
            "proposal_id": p["proposal_id"], "base_version": p["base_version"],
            "proposed_config": json.loads(p["config_json"]),
            "rationale": json.loads(p["payload_json"])["rationale"],
            "evidence": json.loads(p["payload_json"]).get("evidence") or {}})
        if r.status is None or r.code == "duplicate_proposal_id":
            return
        if r.ok:
            self._applied(p, r.json["version"], minute, "auto-applied within policy")
        elif r.code == "stale_base_version":
            self._stale(p, minute)
        elif r.status == 403:
            self._fallback_to_approval(p, minute, r.json.get("detail"), page=True)
        else:
            self._finish(p, "DROPPED", minute, f"auto-apply refused: {r.status} {r.json}")

    # -------------------------------------------------------------- transitions
    def _applied(self, p: sqlite3.Row, version: int, minute: int, rule: str) -> None:
        with store.tx(self.conn):
            self._set(p, "APPLIED", minute, rule, applied_version=version)
            configs.sync(self.conn, self.client, self.clock, p["wf"])
            self._owner(p).on_applied(self.conn, self._row(p["proposal_id"]), version, minute)

    def _finish(self, p: sqlite3.Row, state: str, minute: int, rule: str, **cols) -> None:
        with store.tx(self.conn):
            self._set(p, state, minute, rule, **cols)
            self._owner(p).on_terminal(self.conn, self._row(p["proposal_id"]), state, minute)

    def _stale(self, p: sqlite3.Row, minute: int) -> None:
        """409 stale_base_version: classify by who changed the config after our base (SUBMISSION §6)."""
        with store.tx(self.conn):
            configs.sync(self.conn, self.client, self.clock, p["wf"])
            later = self.conn.execute("SELECT actor, changed_dims FROM config_versions WHERE wf=? AND version>?",
                                      (p["wf"], p["base_version"])).fetchall()
            sup_dims = {d for r in later if r["actor"] == "supervisor" for d in json.loads(r["changed_dims"])}
            ours = configs.patch_dims(json.loads(p["patch_json"]))
            if sup_dims & ours or "cohorts" in sup_dims:
                self._finish(p, "STALE", minute, f"supervisor changed {sorted(sup_dims)}: preserved, not re-proposed")
                return
            self._set(p, "STALE", minute, f"base moved ({[r['actor'] for r in later]}): rebasing the same patch")
            draft(self.conn, minute, p["wf"], p["kind"], json.loads(p["patch_json"]), json.loads(p["payload_json"]),
                  owner=json.loads(p["refs_json"])["owner"], refs=_refs(p), decision_id=p["decision_id"],
                  path=p["path"], urgent=bool(p["urgent"]), parent=p["proposal_id"])

    def _fallback_to_approval(self, p: sqlite3.Row, minute: int, reasons, page: bool) -> None:
        with store.tx(self.conn):
            self._set(p, "NOT_PERMITTED", minute, f"auto-apply not permitted ({reasons}): falling back to approval")
            if page:
                store.raise_alert(self.conn, minute, "page", p["wf"],
                                  f"auto-apply 403 on {p['proposal_id']} although the local check passed: {reasons}")
            draft(self.conn, minute, p["wf"], p["kind"], json.loads(p["patch_json"]), json.loads(p["payload_json"]),
                  owner=json.loads(p["refs_json"])["owner"], refs=_refs(p), decision_id=p["decision_id"],
                  path="approval", urgent=bool(p["urgent"]), parent=p["proposal_id"])

    def _set(self, p: sqlite3.Row, state: str, minute: int, rule: str, **cols) -> None:
        """State change + its audit row, in one transaction."""
        cols = {"state": state, "updated_minute": minute, **cols}
        with store.tx(self.conn):
            self.conn.execute(f"UPDATE proposals SET {', '.join(f'{k}=?' for k in cols)} WHERE proposal_id=?",
                              (*cols.values(), p["proposal_id"]))
            store.record_decision(self.conn, minute, p["wf"], "governance", rule,
                                  {"from": p["state"], "to": state, "kind": p["kind"],
                                   **{k: v for k, v in cols.items() if k in ("approval_id", "applied_version",
                                                                              "reasons", "base_version")}},
                                  state, proposal_id=p["proposal_id"])
        if not self.conn.in_transaction:
            self.after_commit(state)

    def _row(self, pid: str) -> sqlite3.Row:
        return self.conn.execute("SELECT * FROM proposals WHERE proposal_id=?", (pid,)).fetchone()

    def _owner(self, p: sqlite3.Row) -> Owner:
        return self.owners[json.loads(p["refs_json"])["owner"]]


def _refs(p: sqlite3.Row) -> dict:
    return {k: v for k, v in json.loads(p["refs_json"]).items() if k != "owner"}


def _q(states: tuple[str, ...]) -> str:
    return ",".join(f"'{s}'" for s in states)
