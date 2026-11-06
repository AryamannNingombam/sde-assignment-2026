"""Approver fatigue ledger and filing-time rules (CONTEXT P4/P5).

* The sim counts requests by ``created_at`` over a rolling 24 h, rejected and expired ones
  included. Slot tiers: the LAST slot is reserved for safety incidents (hallucination fix, flagged-DID
  evacuation); harm-stop/rollback may use the second-to-last; routine bundles get the rest
  (``max(1, total - 2)``). A rollback never blocks a safety fix.
* ``settings.SOFT_CAPS`` adds per-workflow soft preferences for routine requests.
* A request is filed only inside approver hours, and only if the worst-case decision time,
  ``next_working(now + max_latency)``, is before ``expires_at`` (so it cannot expire unseen).
"""
from __future__ import annotations

from typing import Mapping

from . import settings
from .desired import Priority

DAY = settings.MINUTES_PER_DAY


def in_hours(minute: int, hours: Mapping | list) -> bool:
    lo, hi = hours
    return lo * 60 <= minute % DAY < hi * 60


def next_working(t: int, hours: list) -> int:
    """First approver-working minute at or after ``t`` (same rule as the sim's decision time)."""
    lo, hi = hours
    day, mod = divmod(t, DAY)
    if mod < lo * 60:
        return day * DAY + lo * 60
    if mod >= hi * 60:
        return (day + 1) * DAY + lo * 60
    return t


def ttl_minutes(gov: Mapping, expires_in_hours: float | None = None) -> int:
    ttl = gov["proposal_ttl_hours"]
    return int(min(float(expires_in_hours or ttl), ttl) * 60)


def worst_case_decision(now: int, gov: Mapping) -> int:
    return next_working(now + gov["approver_latency_minutes"][1], gov["approver_hours"])


def filing_window_ok(now: int, gov: Mapping, routine: bool, workflow_id: str,
                     expires_in_hours: float | None = None) -> tuple[bool, str]:
    """May a request be filed right now? Returns ``(ok, reason_if_not)``."""
    if not in_hours(now, gov["approver_hours"]):
        return False, "outside approver hours"
    soft = settings.SOFT_CAPS.get(workflow_id, {})
    if routine and now % DAY < soft.get("not_before_hour", 0) * 60:
        return False, f"soft cap: not before {soft['not_before_hour']}:00"
    if worst_case_decision(now, gov) >= now + ttl_minutes(gov, expires_in_hours):
        return False, "worst-case decision time is not before expires_at"
    return True, ""


def routine_budget(gov: Mapping, workflow_id: str) -> int:
    """Routine bundles: all but the last two slots (at least one, never the reserved last one)."""
    total = gov["max_requests_per_24h"]
    budget = min(max(1, total - 2), total - 1)
    soft = settings.SOFT_CAPS.get(workflow_id, {}).get("max_per_day")
    return max(0, min(budget, soft) if soft is not None else budget)


def severe_budget(gov: Mapping) -> int:
    """Harm-stop / rollback may use the second-to-last slot, never the last."""
    return max(0, gov["max_requests_per_24h"] - 1)


def slot_limit(gov: Mapping, priority: int, workflow_id: str) -> int:
    if priority <= Priority.INCIDENT:
        return gov["max_requests_per_24h"]  # the last slot is reserved for safety incidents
    if priority <= Priority.SEVERE:
        return severe_budget(gov)
    return routine_budget(gov, workflow_id)


def slot_available(used: int, gov: Mapping, priority: int, workflow_id: str) -> tuple[bool, str]:
    limit = slot_limit(gov, priority, workflow_id)
    if used >= limit:
        return False, f"fatigue budget: {used} requests in 24h, limit {limit} for priority {int(priority)}" + (
            " (last slot reserved for safety incidents)" if priority > Priority.INCIDENT else "")
    return True, ""
