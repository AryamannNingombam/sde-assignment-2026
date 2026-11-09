"""Governance policy helpers (pure apart from the quota count). Read straight from GET /workflows."""
from __future__ import annotations

import copy
import sqlite3

from . import settings
from .clock import MIN_PER_DAY
from .configs import AGENT_DIMS, changed_dims, cohort_ids, dist, tv_shift


def _gov(spec: dict) -> dict:
    return spec["governance"]


def p_latency(spec: dict) -> float:
    lo, hi = _gov(spec)["approver_latency_minutes"]
    return lo + settings.LATENCY_QUANTILE * (hi - lo)


def window(spec: dict) -> tuple[int, int]:
    """Approver window in minutes of day, including the tenant's stated earliest hour."""
    lo, hi = _gov(spec)["approver_hours"]
    lo = max(lo, settings.TENANT_EARLIEST_HOUR.get(spec.get("tenant_id"), lo))
    return lo * 60, hi * 60


def next_working(spec: dict, minute: int) -> int:
    """When the simulated approver would get to a request that becomes due at `minute`.

    Deliberately the raw `approver_hours`, not `window()`: this predicts the approver's own schedule. The tenant's
    stated earliest hour only limits when *we* submit, which `can_submit_now` enforces through `window()`."""
    lo, hi = (h * 60 for h in _gov(spec)["approver_hours"])
    day, mod = divmod(minute, MIN_PER_DAY)
    if mod < lo:
        return day * MIN_PER_DAY + lo
    if mod >= hi:
        return (day + 1) * MIN_PER_DAY + lo
    return minute


def can_submit_now(spec: dict, minute: int, urgent: bool) -> tuple[bool, str]:
    """Routine changes must be decided and applied the same approver day; urgent ones only before expiry."""
    lo, hi = window(spec)
    mod = minute % MIN_PER_DAY
    if not lo <= mod < hi:
        return False, f"outside approver window {lo // 60}-{hi // 60}h"
    lat = p_latency(spec)
    if urgent:
        decide = next_working(spec, int(minute + lat))
        if decide > minute + _gov(spec)["proposal_ttl_hours"] * 60:
            return False, "p75 decision would land after expiry"
        return True, "urgent: within window and expected to be decided before expiry"
    if mod + lat + settings.STEP_MINUTES > hi:
        return False, f"p75 latency {lat:.0f}m would push the decision past {hi // 60}h"
    return True, "p75 decision and apply fit inside today's approver window"


def expires_in_hours(spec: dict, minute: int, urgent: bool) -> float:
    ttl = _gov(spec)["proposal_ttl_hours"]
    if urgent:
        return ttl
    _, hi = window(spec)
    return max(0.25, min(ttl, (hi - minute % MIN_PER_DAY) / 60))   # stale evidence is not approved tomorrow


def quota_left(conn: sqlite3.Connection, spec: dict, wf: str, minute: int, urgent: bool,
               safety_incident: bool = False) -> int:
    """Rolling 24h, counted the way the approver counts (every request created). The last slot is reserved.

    A tenant's stated cap (stricter than policy) applies to everything except a live safety incident fix, which
    may use the policy's own limit: a client preference can delay a test, not a fix for customers being misled."""
    used = conn.execute("SELECT COUNT(*) FROM proposals WHERE wf=? AND path='approval' AND submitted_minute IS NOT NULL"
                        " AND submitted_minute > ?", (wf, minute - MIN_PER_DAY)).fetchone()[0]
    limit = _gov(spec)["max_requests_per_24h"]
    if not safety_incident:
        limit = min(limit, settings.TENANT_MAX_REQUESTS_PER_24H.get(spec.get("tenant_id"), 10**6))
    cap = limit - (0 if urgent else settings.RESERVED_SLOTS_PER_WF)
    return max(0, cap - used)


def auto_apply_eligible(spec: dict, old: dict, new: dict) -> tuple[bool, list[str]]:
    """Local copy of the simulator's rule, so we never send a PUT we expect to be refused."""
    pol = _gov(spec)["auto_apply"]
    reasons = []
    dims = changed_dims(old, new)
    if not pol.get("enabled"):
        reasons.append("auto-apply disabled for this workflow")
    bad = [d for d in dims if d not in pol.get("allowed_dims", [])]
    if bad:
        reasons.append(f"dims not permitted: {bad}")
    sh = tv_shift(old, new)
    if sh > pol.get("max_shift", 0) + 1e-9:
        reasons.append(f"shift {sh:.3f} exceeds max_shift {pol.get('max_shift', 0)}")
    if not dims:
        reasons.append("no change")
    return not reasons, reasons


def route_change(spec: dict, old: dict, target: dict) -> list[tuple[str, dict]]:
    """How to get from `old` to `target` without evading the policy (SUBMISSION §5, rollback routing).

    - eligible for auto-apply  -> [("auto", target)]
    - auto-apply covers the dims but the shift is too big -> one de-risking auto step of exactly max_shift,
      then the full change through approval. Never a chain of auto steps.
    - otherwise -> [("approval", target)]
    """
    ok, _ = auto_apply_eligible(spec, old, target)
    if ok:
        return [("auto", target)]
    pol = _gov(spec)["auto_apply"]
    dims = changed_dims(old, target)
    if pol.get("enabled") and dims and all(d in pol.get("allowed_dims", []) for d in dims) \
            and set(dims) <= set(AGENT_DIMS):
        lam = (pol["max_shift"] - 1e-4) / tv_shift(old, target)     # margin for weight rounding
        step = interpolate(old, target, lam)
        if auto_apply_eligible(spec, old, step)[0]:
            return [("auto", step), ("approval", target)]
    return [("approval", target)]


def interpolate(old: dict, target: dict, lam: float) -> dict:
    """Move every agent-dim allocation a fraction `lam` of the way from old to target. Cohorts unchanged."""
    out = copy.deepcopy(old)
    for c in cohort_ids(old):
        for dim in AGENT_DIMS:
            a, b = dist(old, c, dim), dist(target, c, dim)
            if a == b:
                continue
            mixed = {o: (1 - lam) * a.get(o, 0) + lam * b.get(o, 0) for o in set(a) | set(b)}
            out["allocations"].setdefault(c, {})[dim] = {o: round(w, 6) for o, w in sorted(mixed.items()) if w > 1e-9}
    return out
