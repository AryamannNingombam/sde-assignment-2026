"""Outcome-first controller for the dialling simulator.

The controller deliberately keeps its policy small and explainable. It learns
from call events, keeps a little exploration traffic alive, and only proposes
changes after a variant has enough evidence to be useful.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import time
import uuid
from collections import defaultdict
from pathlib import Path

import httpx


MIN_VARIANT_CALLS = 80
MIN_INCIDENT_CALLS = 40
MAX_HALLUCINATION_HISTORY = 2000
EXPLORATION_WEIGHT = 0.20
ADVANCE_MINUTES = 60
# Validation is intentionally noisy in the simulator. A 99% pass gate is
# strict enough to reject unsafe suggestions without making every fix fail.
MAX_HALLUCINATION_RATE = 0.01
# Prompt safety validation is noisy and does not measure engagement. Until we
# have a proper post-apply rollback loop, prompt changes remain manual.
ALLOW_PROMPT_CHANGES = False
MIN_PROMOTION_LIFT = 0.01


class Controller:
    def __init__(self, base_url: str, state_path: Path):
        self.client = httpx.Client(base_url=base_url, timeout=120)
        self.state_path = state_path
        self.state = self._load_state()
        self.state.setdefault("last_proposal_minute", {})
        self.state.setdefault("incident_attempted", {})
        self.state.setdefault("voice_promotions", {})
        self._audit("controller_started", state_file=str(self.state_path))
        self.workflows = {
            item["workflow_id"]: item
            for item in self.client.get("/workflows").raise_for_status().json()
        }

    def _load_state(self) -> dict:
        if self.state_path.exists():
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        return {"chunks": {"events": -1, "history": -1}, "stats": {},
                "proposals": {}, "last_proposal_minute": {}, "incident_attempted": {}}

    def _save_state(self) -> None:
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.state, indent=2), encoding="utf-8")
        temporary.replace(self.state_path)

    def _audit(self, action: str, **details) -> None:
        """Append-only decision trail for the supervisor review."""
        audit_path = self.state_path.with_name("controller_audit.jsonl")
        record = {"action": action, "sim_minute": getattr(self, "now", 0), **details}
        with audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")

    def _stats(self, workflow_id: str) -> dict:
        return self.state["stats"].setdefault(workflow_id, {"dimensions": {}, "hallucinations": []})

    def _consume_chunks(self, kind: str, chunks: list[dict]) -> None:
        for chunk in sorted(chunks, key=lambda item: item["chunk"]):
            if chunk["chunk"] <= self.state["chunks"].get(kind, -1):
                continue
            response = self.client.get(f"/events/chunks/{chunk['chunk']}")
            response.raise_for_status()
            for line in response.text.splitlines():
                self._consume_event(json.loads(line))
            self.state["chunks"][kind] = chunk["chunk"]

    def _consume_event(self, event: dict) -> None:
        if event.get("type") == "config_changed":
            self._audit("config_changed", workflow_id=event.get("workflow_id"),
                        actor=event.get("actor"), version=event.get("version"),
                        changed_dims=event.get("changed_dims", []))
            if event.get("actor") == "supervisor":
                self.state.setdefault("supervisor_edits", {})[event["workflow_id"]] = event
            return
        if event.get("type") != "call":
            return
        workflow_id = event["workflow_id"]
        stats = self._stats(workflow_id)
        variant = event.get("variant", {})
        connected = bool(event.get("connected"))
        engaged = bool(event.get("engaged"))

        for dimension in ("welcome_message", "voice", "caller_id"):
            option = variant.get(dimension)
            if not option:
                continue
            bucket = stats["dimensions"].setdefault(dimension, {}).setdefault(
                option, {"dials": 0, "connected": 0, "engaged": 0}
            )
            bucket["dials"] += 1
            bucket["connected"] += int(connected)
            bucket["engaged"] += int(engaged)

        if connected and "qa" in event:
            stats["hallucinations"].append({
                "flag": bool(event["qa"].get("hallucination_flag")),
                "minute": event.get("ts"),
            })
            # Keep incident detection bounded at load-scenario scale. The
            # complete event stream remains on disk; controller state only
            # needs a recent window for decisions.
            if len(stats["hallucinations"]) > MAX_HALLUCINATION_HISTORY:
                del stats["hallucinations"][:-MAX_HALLUCINATION_HISTORY]

    @staticmethod
    def _rate(bucket: dict, primary: str) -> float:
        denominator = bucket["connected"] if primary == "engagement_rate" else bucket["dials"]
        numerator = bucket["engaged"] if primary == "engagement_rate" else bucket["connected"]
        return numerator / max(denominator, 1)

    def _best_dimension(self, workflow_id: str, dimension: str, primary: str) -> str | None:
        buckets = self._stats(workflow_id)["dimensions"].get(dimension, {})
        eligible = [
            (option, bucket)
            for option, bucket in buckets.items()
            if bucket["dials"] >= MIN_VARIANT_CALLS
        ]
        if not eligible:
            return None
        return max(eligible, key=lambda item: self._rate(item[1], primary))[0]

    def _proposal_body(self, workflow_id: str, current: dict, proposed: dict, summary: str) -> dict:
        return {
            "proposal_id": f"controller-{uuid.uuid4().hex}",
            "workflow_id": workflow_id,
            "base_version": current["version"],
            "proposed_config": proposed,
            "change_summary": summary,
            "diff": {"allocations": proposed["allocations"]},
            "affected_leads": 0,
            "dry_run": {"method": "historical event replay", "minimum_calls": MIN_VARIANT_CALLS},
            "impact_score": 0.25,
            "rationale": "Promote a sufficiently sampled variant while retaining exploration traffic.",
        }

    def _proposal_allowed(self, workflow_id: str) -> bool:
        """Avoid turning a rejected experiment into an approval-fatique loop."""
        if workflow_id in self.state["proposals"]:
            return False
        last = self.state["last_proposal_minute"].get(workflow_id)
        return last is None or self.now - last >= 1440

    def _propose_best_voice(self, workflow_id: str) -> None:
        if not self._proposal_allowed(workflow_id):
            return
        if self.state["voice_promotions"].get(workflow_id):
            return
        workflow = self.workflows[workflow_id]
        objective = workflow["objective"]["primary"]
        best = self._best_dimension(workflow_id, "voice", objective)
        if not best:
            return
        current = self.client.get(f"/workflows/{workflow_id}/config").raise_for_status().json()
        current_config = current["config"]
        old = current_config["allocations"]["default"].get("voice", {})
        buckets = self._stats(workflow_id)["dimensions"].get("voice", {})
        options = workflow["options"]["voice"]
        observed = [option for option, bucket in buckets.items() if bucket["dials"] > 0]
        if len(observed) == 1 and len(options) > 1:
            proposed = copy.deepcopy(current_config)
            incumbent = observed[0]
            proposed["allocations"]["default"]["voice"] = {
                option: (0.90 if option == incumbent else 0.10 / (len(options) - 1))
                for option in options
            }
            body = self._proposal_body(workflow_id, current, proposed, "Seed a fair voice exploration experiment")
            response = self.client.post("/approvals", json=body)
            if response.status_code == 200:
                approval = response.json()
                self.state["proposals"][workflow_id] = approval["approval_id"]
                self.state["last_proposal_minute"][workflow_id] = self.now
                self.state["voice_promotions"][workflow_id] = True
                self._audit("approval_requested", workflow_id=workflow_id,
                            approval_id=approval["approval_id"], summary=body["change_summary"])
            return
        if len(old) == 1 and best in old and old[best] >= 1:
            return
        best_rate = self._rate(buckets[best], objective)
        current_options = [option for option, weight in old.items() if weight > 0]
        current_rate = max((self._rate(buckets[o], objective) for o in current_options if o in buckets), default=0)
        if best_rate - current_rate < MIN_PROMOTION_LIFT:
            return

        proposed = copy.deepcopy(current_config)
        proposed["allocations"]["default"]["voice"] = {
            option: (1 - EXPLORATION_WEIGHT if option == best else EXPLORATION_WEIGHT / max(len(options) - 1, 1))
            for option in options
        }
        body = self._proposal_body(workflow_id, current, proposed, f"Promote sampled voice {best}")
        response = self.client.post("/approvals", json=body)
        if response.status_code == 200:
            approval = response.json()
            self.state["proposals"][workflow_id] = approval["approval_id"]
            self.state["last_proposal_minute"][workflow_id] = self.now
            self._audit("approval_requested", workflow_id=workflow_id,
                        approval_id=approval["approval_id"],
                        summary=body["change_summary"])
            self.state["voice_promotions"][workflow_id] = True

    def _propose_best_caller_id(self, workflow_id: str) -> None:
        """Rotate away from a clearly underperforming caller ID."""
        if not self._proposal_allowed(workflow_id) or self.state["voice_promotions"].get(workflow_id):
            return
        workflow = self.workflows[workflow_id]
        buckets = self._stats(workflow_id)["dimensions"].get("caller_id", {})
        eligible = [(o, b) for o, b in buckets.items() if b["dials"] >= MIN_VARIANT_CALLS]
        if len(eligible) < 2:
            return
        best, best_bucket = max(eligible, key=lambda item: self._rate(item[1], "pickup_rate"))
        current = self.client.get(f"/workflows/{workflow_id}/config").raise_for_status().json()
        cfg = current["config"]
        old = cfg["allocations"]["default"].get("caller_id", {})
        current_options = [o for o, w in old.items() if w > 0 and o in buckets]
        current_rate = max((self._rate(buckets[o], "pickup_rate") for o in current_options), default=0)
        if self._rate(best_bucket, "pickup_rate") - current_rate < MIN_PROMOTION_LIFT:
            return
        proposed = copy.deepcopy(cfg)
        options = workflow["options"]["caller_id"]
        proposed["allocations"]["default"]["caller_id"] = {
            option: (0.8 if option == best else 0.2 / max(len(options) - 1, 1))
            for option in options
        }
        body = self._proposal_body(workflow_id, current, proposed, f"Rotate traffic toward healthier caller ID {best}")
        response = self.client.post("/approvals", json=body)
        if response.status_code == 200:
            self.state["proposals"][workflow_id] = response.json()["approval_id"]
            self.state["last_proposal_minute"][workflow_id] = self.now
            self.state["voice_promotions"][workflow_id] = True

    def _reconcile_approvals(self) -> None:
        for workflow_id, approval_id in list(self.state["proposals"].items()):
            response = self.client.get(f"/approvals/{approval_id}")
            if response.status_code != 200:
                continue
            approval = response.json()
            status = approval.get("status")
            if status == "approved":
                applied = self.client.post(
                    f"/workflows/{workflow_id}/apply", json={"approval_id": approval_id}
                )
                if applied.status_code in (200, 409, 410):
                    self._audit("approval_reconciled", workflow_id=workflow_id,
                                approval_id=approval_id, status=applied.status_code)
                    self.state["proposals"].pop(workflow_id, None)
            elif status in ("rejected", "expired", "lapsed", "applied"):
                self._audit("approval_reconciled", workflow_id=workflow_id,
                            approval_id=approval_id, status=status)
                self.state["proposals"].pop(workflow_id, None)

    def _handle_prompt_incident(self, workflow_id: str) -> None:
        if not ALLOW_PROMPT_CHANGES:
            return
        if self.state["incident_attempted"].get(workflow_id):
            return
        history = self._stats(workflow_id)["hallucinations"][-MIN_INCIDENT_CALLS:]
        if len(history) < MIN_INCIDENT_CALLS:
            return
        rate = sum(item["flag"] for item in history) / len(history)
        if rate <= MAX_HALLUCINATION_RATE:
            return
        self.state["incident_attempted"][workflow_id] = True
        suggestion = self.client.post(
            "/llm/suggest-fixes",
            json={"workflow_id": workflow_id, "problem": "hallucination rate exceeded 1%"},
        )
        if suggestion.status_code != 200:
            return
        for candidate in suggestion.json().get("suggestions", []):
            prompt = candidate.get("prompt_version")
            if not prompt:
                continue
            validation = self.client.post(
                "/validation/runs", json={"workflow_id": workflow_id, "prompt_version": prompt, "n": 500}
            )
            if validation.status_code == 200 and validation.json().get("pass_rate", 0) >= 1 - MAX_HALLUCINATION_RATE:
                self._propose_prompt(workflow_id, prompt, validation.json()["validation_run_id"])
                return

    def _propose_prompt(self, workflow_id: str, prompt: str, validation_id: str) -> None:
        if not self._proposal_allowed(workflow_id):
            return
        current = self.client.get(f"/workflows/{workflow_id}/config").raise_for_status().json()
        proposed = copy.deepcopy(current["config"])
        if proposed["prompt_version"] == prompt:
            return
        proposed["prompt_version"] = prompt
        body = self._proposal_body(workflow_id, current, proposed, f"Validated prompt safety fix {prompt}")
        body["evidence"] = {"validation_run_id": validation_id}
        response = self.client.post("/approvals", json=body)
        if response.status_code == 200:
            self.state["proposals"][workflow_id] = response.json()["approval_id"]
            self.state["last_proposal_minute"][workflow_id] = self.now

    def run(self) -> None:
        while True:
            state = self.client.get("/sim/state").raise_for_status().json()
            self.now = state.get("sim_minute", 0)
            if state.get("finished"):
                break
            history = self.client.get("/events/chunks", params={"kind": "history", "after": self.state["chunks"].get("history", -1)})
            history.raise_for_status()
            self._consume_chunks("history", history.json())

            advanced = self.client.post("/sim/advance", json={"minutes": ADVANCE_MINUTES})
            if advanced.status_code == 409:
                break
            advanced.raise_for_status()
            self._consume_chunks("events", advanced.json().get("new_chunks", []))
            self._reconcile_approvals()
            for workflow_id in self.workflows:
                self._propose_best_caller_id(workflow_id)
                self._propose_best_voice(workflow_id)
                self._handle_prompt_incident(workflow_id)
            self._save_state()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("url", help="Simulator URL")
    parser.add_argument("--state", default="controller_state.json")
    args = parser.parse_args()
    Controller(args.url, Path(args.state)).run()


if __name__ == "__main__":
    main()
