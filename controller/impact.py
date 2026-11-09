"""Proposal contents a busy supervisor can say yes to: diff, affected leads, dry run, impact score (SUBMISSION §6).

Honesty rules:
- Every dry-run number carries an evidence class: observed (ran here recently), estimated (history only) or
  unknown (never ran here). Unknown options get no predicted lift, only an exposure bound.
- Impact scores are conservative and computed in one place, because Product sorts the queue by them.
"""
from __future__ import annotations

import sqlite3

from . import kpi as K
from . import metrics, settings
from .clock import MIN_PER_DAY
from .cohorts import from_config, assign, features_of
from .configs import AGENT_DIMS, changed_dims, cohort_ids, dist


# ---------------------------------------------------------------------------- impact score
def clip01(x: float) -> float:
    return max(0.0, min(1.0, x))


def score_promotion(lift_lcb: float, affected_share: float) -> float:
    return clip01(lift_lcb / settings.IMPACT_NORMALISER) * clip01(affected_share)


def score_exploration(challenger_share: float) -> float:
    return settings.EXPLORE_IMPACT_FACTOR * clip01(challenger_share)


def score_harm_avoided(harm_observed: float, affected_share: float) -> float:
    return clip01(harm_observed / settings.IMPACT_NORMALISER) * clip01(affected_share)


# ---------------------------------------------------------------------------- diff
def diff(old: dict, new: dict) -> dict:
    dims = changed_dims(old, new)
    out: dict = {"changed_dims": dims}
    for dim in AGENT_DIMS:
        if dim not in dims:
            continue
        out[dim] = {c: {"from": dist(old, c, dim), "to": dist(new, c, dim)}
                    for c in sorted(set(cohort_ids(old)) | set(cohort_ids(new)))
                    if dist(old, c, dim) != dist(new, c, dim)}
    if "cohorts" in dims:
        out["cohorts"] = {"from": old.get("cohorts", []), "to": new.get("cohorts", [])}
    if "prompt_version" in dims:
        out["prompt_version"] = {"from": old["prompt_version"], "to": new["prompt_version"]}
    return out


# ---------------------------------------------------------------------------- affected leads
def _changed_for(old: dict, new: dict, features: dict) -> bool:
    if old["prompt_version"] != new["prompt_version"]:
        return True
    co, cn = assign(from_config(old), features), assign(from_config(new), features)
    return any(dist(old, co, d) != dist(new, cn, d) for d in AGENT_DIMS)


def affected_leads(conn: sqlite3.Connection, spec: dict, old: dict, new: dict, minute: int) -> int:
    """Leads that could hear something different: open leads in running campaigns (unless the workflow locks
    agent config per campaign) plus the next batch, both restricted to the segments whose allocation changes."""
    wf = spec["workflow_id"]
    span = len(spec["cadence"]) * MIN_PER_DAY
    rows = conn.execute("SELECT l.segment, SUM(1 - l.concluded) FROM leads l JOIN campaign_kpi c USING(campaign_id)"
                        " WHERE c.wf=? AND c.created_minute > ? GROUP BY 1", (wf, minute - span)).fetchall()
    changed = {seg for seg, _ in rows if _changed_for(old, new, features_of(seg))}
    open_now = sum(n for seg, n in rows if seg in changed)
    total_now = sum(n for _, n in rows) or 1
    agent_only = old["prompt_version"] == new["prompt_version"]
    if spec.get("mid_flight") == "next_campaign_only" and agent_only:
        open_now = 0                                     # running campaigns keep their config
    share = sum(n for seg, n in rows if seg in changed) / total_now
    return int(open_now + round(spec["daily_batch"]["size"] * share))


# ---------------------------------------------------------------------------- dry run
def dry_run(conn: sqlite3.Connection, wf: str, old: dict, new: dict, minute: int, extra: dict | None) -> dict:
    """Replay evidence for every option the new config uses on a changed dim, tagged by evidence class."""
    now_h = minute // 60
    since = now_h - settings.DRY_RUN_DAYS * 24
    out: dict = {"window": f"last {settings.DRY_RUN_DAYS} days of live calls + 14-day history",
                 "evidence": {}, "exposure_bound": {}}
    for dim in changed_dims(old, new):
        if dim not in AGENT_DIMS:
            continue
        recent = metrics.by_option(conn, wf, dim, since_hour=max(0, since), until_hour=now_h)
        history = metrics.by_option(conn, wf, dim, until_hour=0)
        options = sorted({o for c in cohort_ids(new) for o in dist(new, c, dim)})
        ev = {}
        for o in options:
            if recent.get(o) and recent[o].dials:
                c, cls = recent[o], "observed"
            elif history.get(o) and history[o].dials:
                c, cls = history[o], "estimated"
            else:
                ev[o] = {"class": "unknown", "note": "never ran on this workflow: no prediction, exposure bound only"}
                continue
            ev[o] = {"class": cls, "pickup": K.pickup(c.dials, c.connected).as_dict(),
                     "engagement": K.engagement(c.connected, c.concluded).as_dict()}
            if cls == "estimated":
                ev[o]["note"] = "history only (business default period); different days and hours"
        out["evidence"][dim] = ev
        unknown = [o for o, e in ev.items() if e["class"] == "unknown"]
        out["exposure_bound"][dim] = {
            "max_share_on_unknown_options": round(max((sum(dist(new, c, dim).get(o, 0) for o in unknown)
                                                       for c in cohort_ids(new)), default=0.0), 4),
            "unknown_options": unknown}
    if old["prompt_version"] != new["prompt_version"]:
        out["prompt"] = {"from": old["prompt_version"], "to": new["prompt_version"],
                         "note": "applies to every call immediately; validation evidence attached"}
    if extra:
        out["analysis"] = extra
    return out
