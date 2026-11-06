"""Approver fatigue ledger and filing-time rules (CONTEXT P4/P5).

* The sim counts requests by ``created_at`` over a rolling 24 h, rejected and expired ones
  included. Routine requests get ``max_requests_per_24h - 1``; the last slot is reserved for
  incident / rollback / harm-stop requests.
* ``settings.SOFT_CAPS`` adds per-workflow soft preferences for routine requests.
* A request is filed only inside approver hours, and only if the worst-case decision time,
  ``next_working(now + max_latency)``, is before ``expires_at`` (so it cannot expire unseen).
"""
from __future__ import annotations

from typing import Mapping

from . import settings

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
    budget = gov["max_requests_per_24h"] - 1
    soft = settings.SOFT_CAPS.get(workflow_id, {}).get("max_per_day")
    return max(0, min(budget, soft) if soft is not None else budget)


def slot_available(used: int, gov: Mapping, routine: bool, workflow_id: str) -> tuple[bool, str]:
    limit = routine_budget(gov, workflow_id) if routine else gov["max_requests_per_24h"]
    if used >= limit:
        return False, f"fatigue budget: {used} requests in 24h, limit {limit}" + (
            " (last slot reserved)" if routine else "")
    return True, ""
