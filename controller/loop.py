"""The controller loop: fixed per-tick order (CONTEXT section 8, C9).

reconcile -> ingest -> apply approved -> detectors -> planner/submit -> metrics -> advance.
Detectors and producers come from a registry (empty by default: the controller then changes
nothing); governance reconciliation runs at startup and on every tick.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from . import settings
from .client import AdvanceNotApplied, Finished, SimClient
from .desired import DEFAULT_REGISTRY, Registry
from .faults import crash_point
from .governance import Governance
from .planner import Planner
from .ingest import IngestStats, Ingestor, mirror_configs
from .store import Store
from .world_id import note_progress

log = logging.getLogger(__name__)
_MAX_ADVANCE_FAILURES = 5


@dataclass(frozen=True)
class Windows:
    """Hour-granular activity windows read from ``GET /workflows``."""

    spans: tuple[tuple[int, int], ...]  # [start_hour, end_hour) in IST
    unknown: bool = False  # a workflow without readable windows: always treat as active

    @classmethod
    def from_workflows(cls, workflows: list[dict]) -> "Windows":
        spans: list[tuple[int, int]] = []
        unknown = False
        for wf in workflows:
            dialling = wf.get("dialling_window")
            approver = (wf.get("governance") or {}).get("approver_hours")
            if dialling and len(dialling) == 2:
                spans.append((int(dialling[0]), int(dialling[1])))
            else:
                unknown = True  # cannot tell when this workflow dials: always active
            if approver and len(approver) == 2:  # a missing approver window only drops its own span
                spans.append((int(approver[0]), int(approver[1])))
        return cls(tuple(spans), unknown)

    def active_at(self, minute: int) -> bool:
        tod = minute % settings.MINUTES_PER_DAY
        return self.unknown or any(s * 60 <= tod < e * 60 for s, e in self.spans)

    def minutes_to_next_boundary(self, minute: int, tick: int = settings.TICK_MINUTES) -> int:
        """Minutes until the next window start (searching up to one day ahead)."""
        for ahead in range(tick, settings.MINUTES_PER_DAY + 1, tick):
            if self.active_at(minute + ahead):
                return ahead
        return settings.MINUTES_PER_DAY


def choose_step(minute: int, end_minute: int, windows: Windows, in_flight: bool,
                tick: int = settings.TICK_MINUTES) -> int:
    """One tick, or up to 60 min when idle outside every window with nothing in flight."""
    step = tick
    if not in_flight and not windows.active_at(minute):
        step = min(max(settings.LONG_STEP_MINUTES // tick, 1) * tick,
                   windows.minutes_to_next_boundary(minute, tick))
    step = min(step, end_minute - minute)
    return max(step, tick)


@dataclass
class RunResult:
    finished: bool
    ticks: int
    sim_minute: int
    stats: IngestStats = field(default_factory=IngestStats)


class Controller:
    def __init__(self, client: SimClient, store: Store, ingestor: Ingestor | None = None,
                 stop_at_minute: int | None = None, registry: Registry | None = None) -> None:
        self.client = client
        self.registry = registry if registry is not None else DEFAULT_REGISTRY
        self.gov: Governance | None = None
        self.planner: Planner | None = None
        self.store = store
        self.ingestor = ingestor or Ingestor(client, store)
        self.stop_at_minute = stop_at_minute
        self.windows = Windows(())
        self._workflow_ids: list[str] = []
        self._advance_returned = time.monotonic()
        self._last_state: dict = {}
        self._saw_finished = False

    # ------------------------------------------------------------ startup
    def startup(self) -> IngestStats:
        state = self.client.state()
        workflows = self.client.workflows()
        self._workflow_ids = [w["workflow_id"] for w in workflows]
        self.windows = Windows.from_workflows(workflows)
        mirror_configs(self.client, self.store, self._workflow_ids)
        self.gov = Governance(self.client, self.store, {w["workflow_id"]: w for w in workflows})
        self.planner = Planner(self.client, self.store, self.gov, self.registry)
        self.gov.reconcile(state["sim_minute"])  # resolve anything a previous run left in flight
        stats = self.ingestor.sync()
        self.store.add_decision(state["sim_minute"], "startup",
                                f"startup: ingested {stats.events} events in {stats.chunks} chunks",
                                inputs={"workflows": self._workflow_ids,
                                        "cursor": self.store.get_cursor().last_event_id})
        self._advance_returned = time.monotonic()  # lag is measured from here, not from import
        return stats

    # ------------------------------------------------------------ per tick
    def in_flight(self) -> bool:
        return self.gov is not None and self.gov.any_in_flight()

    def plan_and_submit(self, now: int) -> None:
        """Detectors, planner and submission (steps 4-6 of the tick)."""
        assert self.planner is not None
        self.planner.run_detectors(now)
        self.planner.plan(now)

    def tick(self) -> tuple[bool, IngestStats]:
        """One loop iteration. Returns ``(finished_and_drained, stats)``."""
        t0 = time.perf_counter()
        state = self._last_state = self.client.state()
        note_progress(self.store, state)
        assert self.gov is not None
        now = state["sim_minute"]
        finished = state["finished"]
        self.gov.reconcile(now)
        stats = self.ingestor.sync()
        if not finished:
            self.gov.apply_approved(now)
            self.plan_and_submit(now)
        hit_stop = self.stop_at_minute is not None and state["sim_minute"] >= self.stop_at_minute
        step = 0
        if not (finished or hit_stop):
            step = choose_step(state["sim_minute"], state["end_minute"], self.windows,
                               self.in_flight(), state.get("tick_minutes", settings.TICK_MINUTES))
        self._record_metrics(state["sim_minute"], stats, t0, step)
        if finished:
            self.store.add_decision(state["sim_minute"], "finished", "scenario finished; exiting 0")
            return True, stats
        if hit_stop:
            self.store.add_decision(state["sim_minute"], "stopped",
                                    f"stop_at_minute {self.stop_at_minute} reached")
            return True, stats
        if self._advance(state["sim_minute"], step):
            self.store.add_decision(state["sim_minute"], "finished",
                                    "advance reported finished; exiting 0")
            self._last_state = {**state, "finished": True}
            self._saw_finished = True
            return True, stats + self.ingestor.sync()  # drain what the final advance produced
        return False, stats

    def _record_metrics(self, minute: int, stats: IngestStats, t0: float, step: int) -> None:
        now = time.perf_counter()
        lag = max(0.0, time.monotonic() - self._advance_returned)
        self.store.add_metric(minute, stats.events, stats.wall_s, lag, now - t0, step)

    def _advance(self, minute: int, step: int) -> bool:
        """Advance; returns True if the sim reported ``finished``."""
        self.store.add_decision(minute, "advance_intent", f"advance {step} min from {minute}",
                                inputs={"target": minute + step})
        try:
            result = self.client.advance(step)
        except Finished:
            log.info("advance reported finished")
            return True
        if result.get("recovered"):
            self.store.add_decision(minute, "advance_recovered",
                                    "advance transport error; sim_minute had moved")
        self._advance_returned = time.monotonic()
        crash_point("after-advance-before-ingest")
        return False

    # ------------------------------------------------------------ run
    def run(self) -> RunResult:
        self.startup()
        ticks, failures = 0, 0
        total = IngestStats()
        while True:
            try:
                done, stats = self.tick()
            except AdvanceNotApplied as exc:
                failures += 1
                self.store.add_alert(None, "error", "advance_failed", str(exc))
                if failures >= _MAX_ADVANCE_FAILURES:
                    raise
                time.sleep(settings.RETRY_BASE_DELAY_S)
                continue
            failures = 0
            ticks += 1
            total += stats
            if done:
                final = self.client.state()  # one read for both fields
                return RunResult(final["finished"] or self._saw_finished, ticks, final["sim_minute"], total)
