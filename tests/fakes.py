"""A small in-memory stand-in for the simulator's governance and event endpoints, for crash/idempotency tests.

`lose_response` makes the next call of a method happen server-side but return an unknown outcome (as a timeout
would), which is exactly the case the intent/reconcile design must survive.
"""
from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta

from controller.configs import changed_dims
from controller.sim_client import Resp

D0 = datetime.fromisoformat("2027-01-04T00:00:00+05:30")


def ts(minute: int) -> str:
    return (D0 + timedelta(minutes=minute)).isoformat()


BASE_CFG = {"cohorts": [], "allocations": {"default": {"welcome_message": {"W1": 1.0}, "voice": {"V1": 1.0},
                                                       "caller_id": {"D1": 0.5, "D2": 0.5}}},
            "prompt_version": "P1", "schedule": {"hour_weights": {}, "lead_preferred_hour": {}}}


class FakeSim:
    def __init__(self, auto_dims=("caller_id",), max_shift=0.5):
        self.now = 0
        self.versions = [{"version": 1, "actor": "business_default", "config": copy.deepcopy(BASE_CFG),
                          "proposal_id": None, "approval_id": None, "minute": None, "changed_dims": []}]
        self.store: dict[str, dict] = {}
        self.proposal_ids: set[str] = set()
        self.auto_dims, self.max_shift = auto_dims, max_shift
        self.lose_response: set[str] = set()
        self.calls: dict[str, int] = {}
        self.chunk_lines: dict[int, list[bytes]] = {}

    # ---------------------------------------------------------------- reads
    def state(self):
        return {"scenario": "fake", "sim_minute": self.now, "ts": ts(self.now), "end_minute": 14400,
                "finished": False, "credits_remaining": 200, "chunks": len(self.chunk_lines)}

    def config(self, wf):
        v = self.versions[-1]
        return {"workflow_id": wf, "version": v["version"], "actor": v["actor"], "config": copy.deepcopy(v["config"])}

    def config_history(self, wf):
        return [{k: v[k] for k in ("version", "actor", "changed_dims", "proposal_id", "approval_id")}
                | {"applied_at": ts(v["minute"]) if v["minute"] is not None else None} for v in self.versions]

    def approvals(self, workflow_id, status=None):
        return [self._public(a) for a in self.store.values()]

    def approval(self, aid):
        return self._public(self.store[aid])

    def chunks(self, kind, after=-1):
        return [{"chunk": n, "kind": kind} for n in sorted(self.chunk_lines) if n > after and kind == "events"]

    def chunk(self, n):
        yield from self.chunk_lines[n]

    # ---------------------------------------------------------------- mutations
    def submit_approval(self, body):
        def do():
            if body["proposal_id"] in self.proposal_ids:
                return Resp(409, {"error": "duplicate_proposal_id"})
            if body["base_version"] != self.versions[-1]["version"]:
                return Resp(409, {"error": "stale_base_version"})
            self.proposal_ids.add(body["proposal_id"])
            aid = f"apr_{len(self.store) + 1:05d}"
            self.store[aid] = {"approval_id": aid, "proposal_id": body["proposal_id"], "status": "pending",
                                   "base_version": body["base_version"], "config": body["proposed_config"]}
            return Resp(200, self._public(self.store[aid]))
        return self._call("submit_approval", do)

    def apply(self, wf, aid):
        def do():
            a = self.store[aid]
            if a["status"] != "approved":
                return Resp(409, {"error": "not_approved", "detail": {"status": a["status"]}})
            if self.now > a["decided"] + 120:
                a["status"] = "lapsed"
                return Resp(410, {"error": "approval_lapsed"})
            if a["base_version"] != self.versions[-1]["version"]:
                return Resp(409, {"error": "stale_base_version"})
            v = self._apply(a["config"], "controller_approved", a["proposal_id"], aid)
            a["status"] = "applied"
            return Resp(200, {"version": v})
        return self._call("apply", do)

    def auto_apply(self, wf, body):
        def do():
            if body["proposal_id"] in self.proposal_ids:
                return Resp(409, {"error": "duplicate_proposal_id"})
            if body["base_version"] != self.versions[-1]["version"]:
                return Resp(409, {"error": "stale_base_version"})
            dims = changed_dims(self.versions[-1]["config"], body["proposed_config"])
            if any(d not in self.auto_dims for d in dims):
                return Resp(403, {"error": "auto_apply_not_permitted", "detail": [f"dims {dims}"]})
            self.proposal_ids.add(body["proposal_id"])
            return Resp(200, {"version": self._apply(body["proposed_config"], "controller_auto", body["proposal_id"], None)})
        return self._call("auto_apply", do)

    # ---------------------------------------------------------------- test controls
    def decide(self, aid, status, at=None):
        a = self.store[aid]
        a["status"], a["decided"] = status, self.now if at is None else at

    def supervisor_edit(self, **alloc):
        cfg = copy.deepcopy(self.versions[-1]["config"])
        cfg["allocations"]["default"].update(alloc)
        self._apply(cfg, "supervisor", None, None)

    def _apply(self, cfg, actor, pid, aid):
        v = len(self.versions) + 1
        self.versions.append({"version": v, "actor": actor, "config": copy.deepcopy(cfg), "proposal_id": pid,
                              "approval_id": aid, "minute": self.now,
                              "changed_dims": changed_dims(self.versions[-1]["config"], cfg)})
        return v

    def _call(self, name, do):
        self.calls[name] = self.calls.get(name, 0) + 1
        r = do()
        if name in self.lose_response:
            self.lose_response.discard(name)
            return Resp(None, error="timeout")
        return r

    def _public(self, a):
        out = {k: a[k] for k in ("approval_id", "proposal_id", "status", "base_version")}
        if a["status"] in ("approved", "rejected", "applied", "lapsed", "expired"):
            out["decided_at"] = ts(a["decided"])
        if a["status"] == "approved":
            out["apply_by"] = ts(a["decided"] + 120)
        out["reasons"] = []
        return out


def call_line(**kw) -> bytes:
    ev = {"type": "call", "ts": ts(kw.get("minute", 600)), "workflow_id": "wf", "campaign_id": "wf:c1",
          "lead_id": kw.get("lead", "wf:l1"), "attempt_no": 1, "config_version": 1, "cohort_id": "default",
          "variant": {"welcome_message": "W1", "voice": kw.get("voice", "V1"), "caller_id": "D1",
                      "prompt_version": "P1"},
          "connected": kw.get("connected", True), "engaged": kw.get("engaged", True),
          "disposition": kw.get("disposition", "concluded_interested"), "qa": {"hallucination_flag": False}}
    return json.dumps(ev).encode()


def lead_line(lead="wf:l1", minute=480) -> bytes:
    return json.dumps({"type": "lead", "ts": ts(minute), "workflow_id": "wf", "campaign_id": "wf:c1", "lead_id": lead,
                       "person_id": "wf:p1", "features": {"lang": "hi", "city_tier": "1", "age_band": "60+",
                                                         "value_band": "low"}}).encode()


def campaign_line(minute=480, leads=2) -> bytes:
    return json.dumps({"type": "campaign_created", "ts": ts(minute), "workflow_id": "wf", "campaign_id": "wf:c1",
                       "leads": leads, "config_version_at_creation": 1}).encode()
