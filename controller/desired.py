"""Desired changes and the registry later phases plug into.

Producers (DID health, hallucination incidents, experiments, schedule refresh) are pure
functions of the data: each tick they return the changes they *currently* want, expressed as
patches against the current config (see ``configlib`` for the patch format). Once a change has
been applied, the producer stops returning it. That makes re-planning after a rejection,
expiry or stale base automatic.

Detectors run before the planner each tick and may persist incidents/state; they return None.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Callable, Iterable


class Priority(IntEnum):
    """Lower value = more urgent (CONTEXT P2: incident > severe harm-stop/rollback > daily bundle)."""

    INCIDENT = 0
    SEVERE = 1
    ROUTINE = 2


ROUTE_AUTO = "auto"
ROUTE_APPROVAL = "approval"


@dataclass(frozen=True)
class DesiredChange:
    workflow: str
    kind: str  # incident | harm_stop | rollback | daily_bundle | did_evacuation ...
    priority: int
    patch: dict
    route_preference: str = ROUTE_APPROVAL  # auto | approval
    evidence: dict = field(default_factory=dict)  # validation_run_id, flag_evacuation, rationale, ...
    summary: str = ""

    def __post_init__(self) -> None:
        if self.route_preference not in (ROUTE_AUTO, ROUTE_APPROVAL):
            raise ValueError(f"bad route_preference {self.route_preference!r}")


@dataclass
class PlanContext:
    """Read access handed to detectors and producers."""

    store: Any
    client: Any
    workflows: dict[str, dict]
    now: int  # sim minute

    @property
    def day(self) -> int:
        return self.now // 1440


Producer = Callable[[PlanContext, str], Iterable[DesiredChange]]
Detector = Callable[[PlanContext], None]
Veto = Callable[[PlanContext, str, str], "str | None"]  # (ctx, workflow_id, proposal_kind) -> reason to withhold /apply


class Registry:
    def __init__(self) -> None:
        self.producers: list[Producer] = []
        self.detectors: list[Detector] = []
        self.vetoes: list[Veto] = []

    def register_producer(self, fn: Producer) -> Producer:
        self.producers.append(fn)
        return fn

    def register_detector(self, fn: Detector) -> Detector:
        self.detectors.append(fn)
        return fn

    def register_veto(self, fn: Veto) -> Veto:
        self.vetoes.append(fn)
        return fn

    def veto(self, ctx: PlanContext, workflow_id: str, kind: str) -> str | None:
        """First reason any producer gives to withhold applying an approved change (the evidence went stale)."""
        for fn in self.vetoes:
            reason = fn(ctx, workflow_id, kind)
            if reason:
                return reason
        return None

    def clear(self) -> None:
        self.producers.clear()
        self.detectors.clear()
        self.vetoes.clear()

    def run_detectors(self, ctx: PlanContext) -> None:
        for detector in self.detectors:
            detector(ctx)

    def collect(self, ctx: PlanContext, workflow_id: str) -> list[DesiredChange]:
        out: list[DesiredChange] = []
        for producer in self.producers:
            out.extend(c for c in producer(ctx, workflow_id) if c.workflow == workflow_id)
        return sorted(out, key=lambda c: (c.priority, c.kind, c.summary))


DEFAULT_REGISTRY = Registry()  # later phases register here; empty = the controller changes nothing
