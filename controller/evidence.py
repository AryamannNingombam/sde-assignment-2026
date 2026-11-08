"""What a proposal claims about itself: affected leads, dry run and impact score.

Rule from memo 05: only what actually happened counts. A dry run replays observed calls. An arm
with no observed calls in the replay window is listed as unobserved and contributes nothing.
"""
from __future__ import annotations

import math

from . import cohorts as ch
from . import configops as co

REPLAY_DAYS = 7
DIM_COL = {"welcome_message": "welcome", "voice": "voice", "caller_id": "did"}


def daily_connected(store, wid: str, now: int) -> float:
    hour = now // 60
    row = store.one("SELECT SUM(connected) c FROM fact_hour WHERE workflow_id=? AND hour_idx>=? AND hour_idx<?",
                    wid, hour - 72, hour)
    return (row["c"] or 0) / 3.0


def impact_score(value_per_day: float, confidence: float, connected_per_day: float) -> float:
    """One scale for every proposal kind, since the supervisor queue is ranked on it.

    value_per_day is in engaged calls gained, or equivalent. A change worth 5% of a day's
    connected calls at full confidence scores about 0.63.
    """
    if connected_per_day <= 0:
        return 0.01
    score = (1 - math.exp(-max(value_per_day, 0) / (0.05 * connected_per_day))) * max(min(confidence, 1), 0)
    return round(max(min(score, 1.0), 0.01), 4)


def affected_leads(store, segments: dict[int, dict], spec: dict, old: dict, new: dict, now: int) -> tuple[int, dict]:
    """Leads with attempts remaining, weighted by the share of their traffic that changes.

    Counts each person once at the largest per-dimension move. The estimate covers live campaigns
    only, so tomorrow's upload is excluded on purpose.
    """
    wid = spec["workflow_id"]
    active_since = now - (len(spec["cadence"]) + 1) * 1440
    rows = store.q("SELECT cs.seg, SUM(cs.leads - cs.concluded) n FROM campaign_seg cs "
                   "JOIN campaigns c ON c.campaign_id = cs.campaign_id "
                   "WHERE c.workflow_id=? AND c.created_minute>=? GROUP BY cs.seg", wid, active_since)
    everyone = old.get("prompt_version") != new.get("prompt_version") or old.get("schedule") != new.get("schedule")
    new_cohorts, old_cohorts = ch.from_config(new), ch.from_config(old)
    total, by_cohort = 0.0, {}
    for r in rows:
        feats = segments.get(r["seg"])
        if feats is None:
            continue
        before, after = ch.assign(old_cohorts, feats), ch.assign(new_cohorts, feats)
        share = 1.0 if everyone else max(
            co.total_variation(co.effective(old, before, d), co.effective(new, after, d)) for d in co.ALLOC_DIMS)
        if share > 0:
            total += r["n"] * share
            by_cohort[after] = by_cohort.get(after, 0.0) + r["n"] * share
    return int(round(total)), {k: int(round(v)) for k, v in sorted(by_cohort.items())}


def dry_run(store, segments: dict[int, dict], spec: dict, old: dict, new: dict, now: int) -> dict:
    """Replays the last REPLAY_DAYS of real calls under the proposed allocation."""
    wid = spec["workflow_id"]
    since = now // 1440 - REPLAY_DAYS
    rows = store.q("SELECT seg, welcome, voice, did, prompt, SUM(dials) d, SUM(connected) c, SUM(engaged) e "
                   "FROM fact_arm WHERE workflow_id=? AND day>=? GROUP BY seg, welcome, voice, did, prompt", wid, since)
    new_cohorts = ch.from_config(new)
    out: dict = {"method": f"replay of observed calls, last {REPLAY_DAYS} days", "calls_replayed": sum(r["d"] for r in rows),
                 "changes": []}
    groups: dict[tuple, dict] = {}
    for r in rows:
        feats = segments.get(r["seg"])
        if feats is None:
            continue
        cohort = ch.assign(new_cohorts, feats)
        for dim, col in DIM_COL.items():
            g = groups.setdefault((cohort, dim), {})
            s = g.setdefault(r[col], [0, 0, 0])
            s[0] += r["d"]
            s[1] += r["c"]
            s[2] += r["e"]
    old_cohorts = ch.from_config(old)
    for (cohort, dim), arms in sorted(groups.items()):
        before_cohort = cohort if cohort in {c.id for c in old_cohorts} else ch.DEFAULT
        a, b = co.effective(old, before_cohort, dim), co.effective(new, cohort, dim)
        if co.total_variation(a, b) == 0:
            continue
        out["changes"].append(_replay_change(cohort, dim, a, b, arms))
    if old.get("prompt_version") != new.get("prompt_version"):
        out["changes"].append(_replay_prompt(store, wid, old["prompt_version"], new["prompt_version"], since))
    if not out["changes"]:
        out["changes"].append({"note": "no allocation change to replay"})
    return out


def _replay_change(cohort: str, dim: str, before: dict, after: dict, arms: dict) -> dict:
    unobserved = sorted(k for k in set(before) | set(after) if arms.get(k, [0, 0, 0])[1] == 0)
    expected = {}
    for label, dist in (("current", before), ("proposed", after)):
        obs = {k: v for k, v in dist.items() if k not in unobserved}
        weight = sum(obs.values())
        if weight:
            expected[label] = {
                "engagement_rate": round(sum(v * arms[k][2] / arms[k][1] for k, v in obs.items()) / weight, 4),
                "pickup_rate": round(sum(v * arms[k][1] / arms[k][0] for k, v in obs.items()) / weight, 4),
            }
    return {"cohort": cohort, "dim": dim, "from": before, "to": after, "expected_on_observed_arms": expected,
            "unobserved_arms": unobserved,
            "note": "unobserved arms have no historical calls and are excluded from the estimate" if unobserved else ""}


def _replay_prompt(store, wid: str, old: str, new: str, since_day: int) -> dict:
    out = {"dim": "prompt_version", "from": old, "to": new, "observed": {}}
    for prompt in (old, new):
        r = store.one("SELECT SUM(qa) q, SUM(halluc) h, SUM(connected) c, SUM(engaged) e FROM fact_hour "
                      "WHERE workflow_id=? AND prompt=? AND hour_idx>=?", wid, prompt, since_day * 24)
        if r["q"]:
            out["observed"][prompt] = {"qa_calls": r["q"], "hallucination_flag_rate": round(r["h"] / r["q"], 4),
                                       "engagement_rate": round(r["e"] / r["c"], 4) if r["c"] else None}
        else:
            out["observed"][prompt] = "no live calls in the replay window"
    return out
