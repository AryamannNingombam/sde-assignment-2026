"""Hallucination-incident detector and producer (CONTEXT C8), behind ``settings.ENABLE_HALLUC``.

Per workflow, each tick: (1) Day-0 validation of the live prompt, (2) one-sided two-proportion
test of the current prompt segment's flag rate against the last known-good prompt's, (3) fix
selection (revert to our own known-good prompt using its validation run; only if none, ask the
LLM for candidates and rank validated ones by the lowest failure upper bound), (4) verification
after the fix is applied (flag rate back to baseline, engagement inside the guardrail), (5) close.
The producer turns an open incident into a prompt-change DesiredChange (always via approval).
"""
from __future__ import annotations

import logging
from typing import Mapping

from .. import settings
from ..credits import call_with_credit_ledger
from ..client import OutcomeUnknown, SimUnavailable
from ..desired import DEFAULT_REGISTRY, ROUTE_APPROVAL, DesiredChange, PlanContext, Priority
from ..incidents import (can_spend, close_incident, open_incident, open_incidents, recover_validations,
                         run_validation, update_incident, validation_cost, validation_for)
from ..stats import two_prop_z, wilson_upper
from . import halluc_data as hd
from .common import latest_config, load_state, save_state

log = logging.getLogger(__name__)
KIND = "halluc"
_RECOVERED: set[str] = set()


def clock(minute: int) -> str:
    return f"Day {minute // 1440} {minute % 1440 // 60:02d}:{minute % 60:02d}"


def _rate(c: list) -> float:
    return c[1] / c[0] if c[0] else 0.0


def _wf_min_pass(wf: Mapping) -> float:
    return float(wf["governance"]["min_validation_pass_rate"])


def _max_engagement_drop(wf: Mapping) -> float:
    guard = (wf.get("objective") or {}).get("guardrail") or {}
    return float(guard.get("engagement_rate_max_drop", settings.ENGAGEMENT_VERIFY_MAX_DROP))


# ------------------------------------------------------------------ the statistical test
def segment_test(seg: list, base: list) -> dict:
    """Is the segment's flag rate above the baseline's? (one-sided two-proportion test)."""
    z, p = two_prop_z(seg[1], seg[0], base[1], base[0], alternative="greater")
    seg_adh = seg[2] / seg[0] if seg[0] else 0.0
    base_adh = base[2] / base[0] if base[0] else 0.0
    adh_drop = base_adh - seg_adh
    corroborated = adh_drop >= settings.HALLUC_ADHERENCE_DROP
    triggered = seg[0] >= settings.HALLUC_MIN_CONNECTS and (
        p < settings.HALLUC_P or (p < 10 * settings.HALLUC_P and corroborated))
    return {"n": seg[0], "flags": seg[1], "rate": _rate(seg), "base_n": base[0], "base_rate": _rate(base),
            "z": round(z, 3), "p": p, "adherence_drop": round(adh_drop, 4), "corroborated": corroborated,
            "triggered": triggered}


def engagement_ok(seg: list, base: list, max_drop: float) -> tuple[bool, dict]:
    """Engagement not significantly below (baseline - guardrail margin)."""
    if not seg[0] or not base[0]:
        return True, {}
    e_new, e_base = seg[3] / seg[0], base[3] / base[0]
    se = (e_new * (1 - e_new) / seg[0] + e_base * (1 - e_base) / base[0]) ** 0.5
    ok = (e_new - e_base) + 1.645 * se >= -max_drop
    return ok, {"engagement": round(e_new, 4), "base_engagement": round(e_base, 4), "max_drop": max_drop}


def rank_by_failure_bound(runs: list[dict], min_pass: float) -> list[dict]:
    """Validated candidates by the lowest failure upper bound (not merely >= the approver's bar)."""
    ok = [r for r in runs if r["pass_rate"] >= min_pass]
    for r in ok:
        r["fail_ub"] = round(wilson_upper(round((1 - r["pass_rate"]) * r["n"]), r["n"]), 5)
    return sorted(ok, key=lambda r: (r["fail_ub"], r["prompt"]))


# ------------------------------------------------------------------ Day-0 validation
def day0_validation(ctx: PlanContext) -> None:
    store = ctx.store
    if str(store.path) not in _RECOVERED:
        recover_validations(store)
        _RECOVERED.add(str(store.path))
    for wid in sorted(ctx.workflows):
        cfg = latest_config(store, wid)
        if cfg is None or store.get_job("halluc_day0", wid) is not None:
            continue
        live = cfg[1]["prompt_version"]
        if validation_for(store, wid, live) is not None:
            store.set_job("halluc_day0", wid, ctx.now)
            continue
        if not can_spend(ctx.client.credits_remaining(), validation_cost(settings.HALLUC_VALIDATION_N),
                         len(ctx.workflows)):
            store.add_alert(ctx.now, "warn", "day0_validation_skipped", "credit reserve would be breached", wid)
            continue
        store.set_job("halluc_day0", wid, ctx.now)  # one paid attempt, never a retry loop
        run_validation(ctx.client, store, wid, live, ctx.now)


# ------------------------------------------------------------------ fix selection
def _spend_ok(ctx, body: dict, cost: float) -> bool:
    return can_spend(ctx.client.credits_remaining(), cost, len(ctx.workflows), incident_spent=body["credits_spent"])


def _validated(ctx, wid: str, prompt: str, body: dict, min_pass: float) -> dict | None:
    """A passing validation of ``prompt`` (existing, or one paid run inside the incident budget)."""
    run = validation_for(ctx.store, wid, prompt)
    if run is None:
        cost = validation_cost(settings.HALLUC_VALIDATION_N)
        if not _spend_ok(ctx, body, cost):
            return None
        raw = run_validation(ctx.client, ctx.store, wid, prompt, ctx.now)
        body["credits_spent"] += cost
        if raw is None:
            return None
        run = {"run_id": raw["validation_run_id"], "n": raw["n"], "pass_rate": raw["pass_rate"]}
    return run if run["pass_rate"] >= min_pass else None


def _candidate(prompt: str, run: dict, source: str) -> dict:
    return {"prompt": prompt, "validation_run_id": run["run_id"], "pass_rate": run["pass_rate"], "n": run["n"],
            "source": source}


def prepare_fix(ctx: PlanContext, wid: str, body: dict, st: Mapping, live: str) -> None:
    """Fill ``body['candidates']`` / ``body['target']``: revert first; LLM only if none exists."""
    min_pass = _wf_min_pass(ctx.workflows[wid])
    tried = set(body["tried"])
    if not body["candidates"] and not body["reverts_checked"]:
        body["reverts_checked"] = True
        for prompt, counts in hd.known_good_candidates(st, live):
            run = _validated(ctx, wid, prompt, body, min_pass)
            if run is not None:
                cand = _candidate(prompt, run, "known_good")
                cand.update({"flag_rate": round(_rate(counts), 5), "flag_n": counts[0]})
                body["candidates"].append(cand)
                break
    if not any(c["prompt"] not in tried and c["prompt"] != live for c in body["candidates"]) \
            and not body["suggested"]:
        _suggest(ctx, wid, body, live, min_pass)
    options = [c for c in body["candidates"] if c["prompt"] not in tried and c["prompt"] != live]
    body["target"] = options[0]["prompt"] if options else None
    if body["target"] is None:
        ctx.store.add_alert(ctx.now, "error", "no_prompt_fix", "no validated fix available; incident stays open", wid)


def _suggest(ctx: PlanContext, wid: str, body: dict, live: str, min_pass: float) -> None:
    if not _spend_ok(ctx, body, settings.SUGGEST_FIXES_COST):
        ctx.store.add_alert(ctx.now, "error", "suggest_fixes_unaffordable", "incident credit budget exhausted", wid)
        return
    s = body["stats"]
    problem = (f"Hallucination flag rate {s.get('rate', 0):.1%} on prompt {live} "
               f"(baseline {s.get('base_rate', 0):.1%}, n={s.get('n', 0)}); need a safe replacement")
    body["suggested"] = True
    body["credits_spent"] += settings.SUGGEST_FIXES_COST
    try:
        resp = call_with_credit_ledger(ctx.client, ctx.store, wid, ctx.now, "suggest-fixes",
                                       ctx.client.suggest_fixes, wid, problem)
    except (OutcomeUnknown, SimUnavailable):
        return
    runs = []
    for sug in resp.get("suggestions", []):
        prompt = sug["prompt_version"]
        if prompt == live or prompt in body["tried"] or any(c["prompt"] == prompt for c in body["candidates"]):
            continue
        run = _validated(ctx, wid, prompt, body, 0.0)
        if run is not None:
            runs.append({"prompt": prompt, **run})
    for r in rank_by_failure_bound(runs, min_pass):
        body["candidates"].append(_candidate(r["prompt"], {"run_id": r["run_id"], "pass_rate": r["pass_rate"],
                                                           "n": r["n"]}, "llm") | {"fail_ub": r["fail_ub"]})


# ------------------------------------------------------------------ detection / incident management
def _edit_of_live_prompt(store, wid: str) -> dict:
    row = store.conn.execute("SELECT version, actor, ts_minute FROM config_versions WHERE workflow_id=?"
                             " AND changed_dims LIKE '%prompt_version%' ORDER BY version DESC LIMIT 1",
                             (wid,)).fetchone()
    return {"version": row[0], "actor": row[1], "minute": row[2]} if row else {}


def _baseline(st: Mapping, live: str) -> tuple[list | None, str | None, str]:
    """(counts, prompt, source): the first prompt's frozen baseline, else the newest known-good."""
    if live == st["first_prompt"] and st["base_frozen"]:
        return st["base"], live, "history" if st["base"][0] else "cold_start"
    cands = hd.known_good_candidates(st, live)
    return (cands[0][1], cands[0][0], "known_good") if cands else (None, None, "")


def _new_body(live: str, base_prompt: str | None, test: dict, edit: dict, kind: str) -> dict:
    return {"kind": kind, "bad_prompt": live, "baseline_prompt": base_prompt, "stats": test, "edit": edit,
            "candidates": [], "tried": [], "target": None, "reverts_checked": False, "suggested": False,
            "credits_spent": 0.0}


def _open(ctx, wid: str, st: dict, live: str, base_prompt, test: dict, kind: str) -> None:
    edit = _edit_of_live_prompt(ctx.store, wid)
    body = _new_body(live, base_prompt, test, edit, kind)
    st["bad"] = sorted(set(st["bad"]) | {live})
    hd.save(ctx.store, wid, st)
    inc_id = open_incident(ctx.store, wid, KIND, ctx.now, body)
    ctx.store.add_alert(ctx.now, "warn", "halluc_incident",
                        f"{kind}: {live} flags {test['rate']:.1%} vs {test['base_rate']:.1%} (n={test['n']}, p={test['p']:.1e})", wid)
    prepare_fix(ctx, wid, body, st, live)
    update_incident(ctx.store, inc_id, body)


def _detect(ctx: PlanContext, wid: str, st: dict, live: str) -> None:
    seg = st["seg"]
    if seg is None or seg["prompt"] != live:
        return
    run = validation_for(ctx.store, wid, live)
    if run is not None and run["pass_rate"] < _wf_min_pass(ctx.workflows[wid]) and live not in st["bad"]:
        test = {"n": run["n"], "flags": round((1 - run["pass_rate"]) * run["n"]), "rate": 1 - run["pass_rate"],
                "base_n": 0, "base_rate": 0.0, "z": 0.0, "p": 0.0, "adherence_drop": 0.0, "corroborated": False,
                "triggered": True, "validation_run_id": run["run_id"], "validation_pass_rate": run["pass_rate"]}
        _open(ctx, wid, st, live, None, test, "bad_prompt_day0")
        return
    base, base_prompt, source = _baseline(st, live)
    if base is None:
        return
    test = segment_test(hd.window_counts(st, ctx.now), base)
    test["baseline_source"] = source
    if ctx.now % 60 < settings.TICK_MINUTES:  # hourly audit row
        ctx.store.add_decision(ctx.now, "halluc_eval", f"{live}: flags {test['rate']:.2%} vs {test['base_rate']:.2%}"
                               f" (n={test['n']}, p={test['p']:.2e})", wid, {**test, "prompt": live, "segment_start": seg["start"]})
    if test["triggered"] and live not in st["bad"]:
        _open(ctx, wid, st, live, base_prompt, test, "prompt_flag_spike")


def _verify(ctx: PlanContext, wid: str, inc: dict, st: dict, live: str) -> None:
    body, seg = inc["body"], st["seg"]
    if seg is None or seg["prompt"] != live or seg["c"][0] < settings.HALLUC_VERIFY_MIN_CONNECTS:
        return
    done = st["done"].get(body.get("baseline_prompt") or "")
    base_counts = done["c"] if done else st["base"]
    if body.get("baseline_prompt") is None:  # Day-0 incident: compare with the bad prompt's own rate
        z, p = two_prop_z(seg["c"][1], seg["c"][0], body["stats"]["flags"], body["stats"]["n"], "less")
        flags_ok = p < 0.05
        base_counts = seg["c"]
    else:
        z, p = two_prop_z(seg["c"][1], seg["c"][0], base_counts[1], base_counts[0], "greater")
        flags_ok = p >= settings.HALLUC_VERIFY_P
    eng_ok, eng = engagement_ok(seg["c"], base_counts, _max_engagement_drop(ctx.workflows[wid]))
    info = {"prompt": live, "n": seg["c"][0], "flag_rate": round(_rate(seg["c"]), 5), "p": p, "flags_ok": flags_ok,
            "engagement_ok": eng_ok, **eng}
    if flags_ok and eng_ok:
        ctx.store.add_decision(ctx.now, "incident_verified", f"{live}: flags {info['flag_rate']:.2%}, engagement ok", wid, info)
        close_incident(ctx.store, inc["id"], ctx.now, f"fixed by {live}; flag rate back to baseline, engagement inside guardrail")
        return
    body["tried"].append(live)
    ctx.store.add_decision(ctx.now, "incident_verify_failed", f"{live} did not verify; trying next candidate", wid, info)
    prepare_fix(ctx, wid, body, st, live)
    update_incident(ctx.store, inc["id"], body)


def _manage(ctx: PlanContext, wid: str, inc: dict, st: dict, live: str) -> None:
    body = inc["body"]
    if live == body["bad_prompt"]:
        if body["target"] is None and not (body["suggested"] and body["reverts_checked"]):
            prepare_fix(ctx, wid, body, st, live)
            update_incident(ctx.store, inc["id"], body)
    elif live == body["target"]:
        _verify(ctx, wid, inc, st, live)
    elif live in body["tried"]:
        return  # a failed fix is still live: waiting for the next candidate to be applied
    else:
        close_incident(ctx.store, inc["id"], ctx.now, f"superseded: prompt is now {live}, not {body['bad_prompt']}")


def halluc_detector(ctx: PlanContext) -> None:
    if not settings.ENABLE_HALLUC:
        return
    day0_validation(ctx)
    for wid in sorted(ctx.workflows):
        cfg = latest_config(ctx.store, wid)
        if cfg is None:
            continue
        live = cfg[1]["prompt_version"]
        st = hd.update(ctx.store, wid)
        incs = open_incidents(ctx.store, wid, KIND)
        if incs:
            _manage(ctx, wid, incs[0], st, live)
        else:
            _detect(ctx, wid, st, live)


# ------------------------------------------------------------------ producer
def _describe_edit(edit: Mapping) -> str:
    if not edit:
        return "live prompt"
    who = edit.get("actor") or "unknown actor"
    return f"set by {who} {clock(edit['minute'])}" if edit.get("minute") is not None else f"set by {who}"


def halluc_producer(ctx: PlanContext, wid: str) -> list[DesiredChange]:
    if not settings.ENABLE_HALLUC:
        return []
    cfg = latest_config(ctx.store, wid)
    if cfg is None:
        return []
    out = []
    for inc in open_incidents(ctx.store, wid, KIND):
        body = inc["body"]
        target = body.get("target")
        if not target or target == cfg[1]["prompt_version"]:
            continue
        cand = next(c for c in body["candidates"] if c["prompt"] == target)
        s = body["stats"]
        live = cfg[1]["prompt_version"]
        base = f"{s['base_rate']:.1%} baseline ({body['baseline_prompt']})" if body.get("baseline_prompt") else "failed Day-0 validation"
        summary = (f"Revert {live} ({_describe_edit(body['edit'])}) to {target}" if cand["source"] == "known_good"
                   else f"Replace {live} ({_describe_edit(body['edit'])}) with {target}")
        summary += (f": flags {s['rate']:.1%} vs {base} (n={s['n']}, p={s['p']:.1e}); "
                    f"validation {cand['validation_run_id']} pass {cand['pass_rate']:.3f}")
        excess = max(s["rate"] - s["base_rate"], 0.0)
        evidence = {"validation_run_id": cand["validation_run_id"], "impact_override": min(1.0, excess / 0.01),
                    "rationale": summary + f". Fix source: {cand['source']}; engagement is verified after apply."}
        out.append(DesiredChange(wid, "halluc_fix", Priority.INCIDENT, {"prompt_version": target},
                                 ROUTE_APPROVAL, evidence, summary))
    return out


def register(registry=DEFAULT_REGISTRY) -> None:
    registry.register_detector(halluc_detector)
    registry.register_producer(halluc_producer)
