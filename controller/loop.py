"""The controller loop: fixed per-tick order (CONTEXT section 8, C9).

reconcile (stub) -> ingest -> detectors/planner (flagged off, stubs) -> metrics -> advance.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from . import settings
from .client import AdvanceNotApplied, Finished, SimClient
from .ingest import IngestStats, Ingestor, mirror_configs
from .store import Store

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
            for span in (dialling, approver):
                if span and len(span) == 2:
                    spans.append((int(span[0]), int(span[1])))
                else:
                    unknown = True
        return cls(tuple(spans), unknown)

    def active_at(self, minute: int) -> bool:
        tod = minute % settings.MINUTES_PER_DAY
        return self.unknown or any(s * 60 <= tod < e * 60 for s, e in self.spans)

    def minutes_to_next_boundary(self, minute: int) -> int:
        """Minutes until the next window start (searching up to one day ahead)."""
        for ahead in range(settings.TICK_MINUTES, settings.MINUTES_PER_DAY + 1, settings.TICK_MINUTES):
            if self.active_at(minute + ahead):
                return ahead
        return settings.MINUTES_PER_DAY


def choose_step(minute: int, end_minute: int, windows: Windows, in_flight: bool) -> int:
    """15 minutes, or up to 60 when idle outside every window with nothing in flight."""
    step = settings.TICK_MINUTES
    if not in_flight and not windows.active_at(minute):
        step = min(settings.LONG_STEP_MINUTES, windows.minutes_to_next_boundary(minute))
    step = min(step, end_minute - minute)
    return max(step, settings.TICK_MINUTES)


@dataclass
class RunResult:
    finished: bool
    ticks: int
    sim_minute: int
    stats: IngestStats = field(default_factory=IngestStats)


class Controller:
    def __init__(self, client: SimClient, store: Store, ingestor: Ingestor | None = None,
                 stop_at_minute: int | None = None) -> None:
        self.client = client
        self.store = store
        self.ingestor = ingestor or Ingestor(client, store)
        self.stop_at_minute = stop_at_minute
        self.windows = Windows(())
        self._workflow_ids: list[str] = []
        self._advance_returned = time.monotonic()

    # ------------------------------------------------------------ startup
    def startup(self) -> IngestStats:
        state = self.client.state()
        workflows = self.client.workflows()
        self._workflow_ids = [w["workflow_id"] for w in workflows]
        self.windows = Windows.from_workflows(workflows)
        mirror_configs(self.client, self.store, self._workflow_ids)
        stats = self.ingestor.sync()
        self.store.add_decision(state["sim_minute"], "startup",
                                f"startup: ingested {stats.events} events in {stats.chunks} chunks",
                                inputs={"workflows": self._workflow_ids,
                                        "cursor": self.store.get_cursor().last_event_id})
        return stats

    # ------------------------------------------------------------ per tick
    def reconcile(self) -> None:
        """Governance reconciliation (Phase 2)."""

    def detect_and_plan(self) -> None:
        """Detectors and planner stubs; every lever is behind a feature flag (all off)."""

    def in_flight(self) -> bool:
        return False

    def tick(self) -> tuple[bool, IngestStats]:
        """One loop iteration. Returns ``(finished_and_drained, stats)``."""
        t0 = time.perf_counter()
        state = self.client.state()
        self.reconcile()
        stats = self.ingestor.sync()
        self.detect_and_plan()
        finished = state["finished"]
        hit_stop = self.stop_at_minute is not None and state["sim_minute"] >= self.stop_at_minute
        step = 0
        if not (finished or hit_stop):
            step = choose_step(state["sim_minute"], state["end_minute"], self.windows,
                               self.in_flight())
        self._record_metrics(state["sim_minute"], stats, t0, step)
        if finished:
            self.store.add_decision(state["sim_minute"], "finished", "scenario finished; exiting 0")
            return True, stats
        if hit_stop:
            self.store.add_decision(state["sim_minute"], "stopped",
                                    f"stop_at_minute {self.stop_at_minute} reached")
            return True, stats
        self._advance(state["sim_minute"], step)
        return False, stats

    def _record_metrics(self, minute: int, stats: IngestStats, t0: float, step: int) -> None:
        now = time.perf_counter()
        lag = time.monotonic() - self._advance_returned
        self.store.add_metric(minute, stats.events, stats.wall_s, lag, now - t0, step)

    def _advance(self, minute: int, step: int) -> None:
        self.store.add_decision(minute, "advance_intent", f"advance {step} min from {minute}",
                                inputs={"target": minute + step})
        try:
            result = self.client.advance(step)
        except Finished:
            log.info("advance reported finished")
            return
        if result.get("recovered"):
            self.store.add_decision(minute, "advance_recovered",
                                    "advance transport error; sim_minute had moved")
        self._advance_returned = time.monotonic()

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
                minute = self.client.state()["sim_minute"]
                return RunResult(self.client.state()["finished"], ticks, minute, total)
