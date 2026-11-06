"""C6 + C7 driver: welcome_message and voice experiments on engagement-primary workflows.

Detector (each tick, before the planner) advances a per-(workflow, dim) state machine kept in ``detector_state``:

  pending -> running (entry applied) -> promoted (winner + holdout) -> closed (rollback / concluded)
  any phase -> interrupted by a supervisor edit of the dim -> a fresh pending experiment with the edit as control

Producer (pure function of that state): the single allocation the experiment currently wants for the dim
(``desired``). Entry, ramp, drop and promotion are customer-facing and always go through approval (daily bundle);
only the risk-reducing harm-stop and rollback ask for auto-apply, which the planner downgrades to the reserved
approval slot when the policy (dim, max_shift) does not allow it. Everything is behind ``ENABLE_EXPERIMENTS``.
"""
from __future__ import annotations

import json
import logging
from typing import Mapping

from . import exp_alloc, exp_data, exp_decay, exp_proposals as prop, exp_rules as er, exp_state as xs, settings
from .cohorts import VOCAB_META_KEY, FeatureVocab
from .desired import DEFAULT_REGISTRY, ROUTE_APPROVAL, ROUTE_AUTO, DesiredChange, PlanContext, Priority
from .detectors.common import latest_config

log = logging.getLogger(__name__)
DAY = settings.MINUTES_PER_DAY


def _auto_ok(wf: Mapping, dim: str) -> bool:
    pol = wf["governance"]["auto_apply"]
    return bool(pol.get("enabled")) and dim in pol.get("allowed_dims", [])


def _guard(wf: Mapping) -> float:
    return float(((wf.get("objective") or {}).get("guardrail") or {}).get("pickup_rate_max_drop", 0.02))


def _version_row(store, wid: str, version: int) -> tuple[str | None, int | None]:
    row = store.conn.execute("SELECT actor, ts_minute FROM config_versions WHERE workflow_id=? AND version=?",
                             (wid, version)).fetchone()
    return (row[0], row[1]) if row else (None, None)


# ------------------------------------------------------------------ state transitions
def _new_state(wf: Mapping, dim: str, cfg: tuple[int, dict], excluded=(), note: str = "", not_before: int = 0) -> dict:
    live = xs.live_dist(cfg[1], dim)
    return {"phase": xs.PENDING, "control": xs.top_option(live), "options": list(wf["options"][dim]),
            "excluded": sorted(excluded), "note": note, "not_before": not_before, "shares": {}, "arms": {},
            "family": [], "desired": None, "live": live, "seen_version": cfg[0], "start_minute": None,
            "scopes": {"all": {"arm_t": {}, "looks": 0}}, "ramped": [], "groups": None, "last_look_day": -1,
            "last_check": -10 ** 9, "history": []}


def _set_desired(st: dict, weights, kind: str, summary: str, rationale: str, *, severe=False, then=None,
                 cohort_weights=None, extra: Mapping | None = None, impact: float | None = None) -> None:
    prev = st.get("desired")
    severe = severe or bool(prev and prev.get("severe"))
    st["desired"] = {"weights": dict(weights), "cohort_weights": cohort_weights or {}, "kind": kind,
                     "summary": summary, "rationale": rationale, "severe": severe, "then": then,
                     "evidence": dict(extra or {}), "impact": impact}


def _plan_entry(ctx: PlanContext, st: dict, wid: str, dim: str) -> None:
    challengers = [o for o in st["options"] if o != st["control"] and o not in st["excluded"]]
    shares = exp_alloc.entry_shares(challengers)
    if not shares:
        return
    st["shares"], st["family"] = shares, sorted(shares)
    st["arms"] = {a: {"state": "active"} for a in shares}
    st["untested"] = [o for o in challengers if o not in shares]
    weights = exp_alloc.weights(st["control"], shares)
    summary, rationale, impact = prop.entry(dim, st["control"], weights, st["note"])
    _set_desired(st, weights, "experiment_entry", summary, rationale, then=xs.RUNNING, impact=impact)
    ctx.store.add_decision(ctx.now, "experiment_entry", summary, wid,
                           {"dim": dim, "control": st["control"], "shares": shares, "weights": weights})


def _on_applied(ctx: PlanContext, st: dict, wid: str, dim: str, minute: int) -> None:
    d = st["desired"]
    st["desired"] = None
    st["applied"] = {"kind": d["kind"], "minute": minute}
    if d["then"] == xs.RUNNING:
        st["phase"] = xs.RUNNING
    elif d["then"] == xs.PROMOTED:
        st["phase"] = xs.PROMOTED
        st["promo"].update(minute=minute)
    elif d["then"] == xs.CLOSED:
        st["phase"] = xs.CLOSED
    ctx.store.add_decision(ctx.now, "experiment_applied", f"{d['kind']} for {dim} is live ({xs.clock(minute)}): "
                           f"{prop.weights_text(d['weights'])}", wid, {"kind": d["kind"], "phase": st["phase"]})


def _interrupt(ctx: PlanContext, st: dict, wid: str, dim: str, cfg, version: int, minute: int, dist: Mapping) -> dict:
    new_control = xs.top_option(dist)
    bad = [a for a, v in st["arms"].items() if v["state"] in ("dropped", "harm_stopped")]
    note = (f"A client supervisor set {dim} to {new_control} at {xs.clock(minute)} (config v{version}); treating it as "
            f"the new control (never re-imposing {st['control']}). ")
    fresh = _new_state(ctx.workflows[wid], dim, cfg, st["excluded"] + bad, note, minute + settings.EXP_SUPERVISOR_COOLDOWN_MINUTES)
    fresh["history"] = st["history"] + [{k: st[k] for k in ("phase", "control", "arms", "shares", "scopes", "promo", "applied")
                                           if k in st} | {"interrupted_minute": minute, "interrupted_version": version}]
    fresh["control"], fresh["live"] = new_control, dict(dist)
    ctx.store.add_decision(ctx.now, "experiment_interrupted", f"supervisor edit of {dim} at {xs.clock(minute)} (v{version}): "
                           f"experiment interrupted, {new_control} is the new control; pre-edit data stays valid for arms that "
                           "ran; nothing will re-impose the old allocation", wid,
                           {"dim": dim, "version": version, "new_control": new_control, "old_control": st["control"],
                            "dist": dict(dist), "pre_edit_arms": st["arms"]})
    return fresh


def _watch(ctx: PlanContext, st: dict, wid: str, dim: str, cfg: tuple[int, dict]) -> dict:
    """Applied detection and supervisor-edit detection from the mirrored config versions."""
    rows = ctx.store.conn.execute("SELECT version, actor, ts_minute, body FROM config_versions WHERE workflow_id=?"
                                  " AND version>? ORDER BY version", (wid, st["seen_version"])).fetchall()
    for version, actor, ts, body in rows:
        if not body:
            continue
        dist = xs.live_dist(json.loads(body), dim)
        exposed = st["phase"] in (xs.RUNNING, xs.PROMOTED)
        if actor == "supervisor" and exposed and not xs.same_dist(dist, st["live"]):
            return _interrupt(ctx, st, wid, dim, cfg, version, ts if ts is not None else ctx.now, dist)
        st["live"], st["seen_version"] = dist, version
    live_dist = xs.live_dist(cfg[1], dim)
    if st["desired"] and xs.desired_matches(cfg[1], dim, st["desired"]):
        _on_applied(ctx, st, wid, dim, _version_row(ctx.store, wid, cfg[0])[1] or ctx.now)
    elif st["phase"] == xs.PENDING and xs.top_option(live_dist) != st["control"]:
        if st["desired"] or st["history"]:  # production changed under a pending proposal: re-plan from the new control
            st["note"] = (f"The live {dim} control is now {xs.top_option(live_dist)} (changed at config v{cfg[0]}); "
                          f"treating it as the control. ")
        st["control"], st["live"], st["desired"] = xs.top_option(live_dist), live_dist, None
    return st


# ------------------------------------------------------------------ looks
def _groups(ctx: PlanContext, st: dict, wid: str, cfg: tuple[int, dict]) -> list[dict]:
    sig = xs.cohort_signature(cfg[1].get("cohorts") or [])
    if st["groups"] is None or st["groups"].get("sig") != sig:
        vocab = FeatureVocab.load(ctx.store.get_meta(VOCAB_META_KEY))
        groups = xs.analysis_groups(ctx.store, vocab, wid, cfg[1].get("cohorts") or [], ctx.now)
        st["groups"] = {"sig": sig, "groups": groups}
        for g in groups:
            st["scopes"].setdefault(g["name"], {"arm_t": {}, "looks": 0})
        ctx.store.add_decision(ctx.now, "experiment_groups", f"pre-registered analysis groups: "
                               f"{[(g['name'], g['cohorts'], g['share']) for g in groups] or 'none'}", wid,
                               {"groups": [{k: v for k, v in g.items() if k != "cells"} for g in groups]})
    return st["groups"]["groups"]


def _start(ctx: PlanContext, st: dict, wid: str, dim: str) -> int | None:
    if st["start_minute"] is None:
        since = (st.get("applied") or {}).get("minute", 0)
        st["start_minute"] = exp_data.first_exposure_minute(ctx.store, wid, dim, st["family"], since)
    return st["start_minute"]


def _scope_look(ctx, st, wid, dim, wf, name, alpha, cells, active, exposure_days, start):
    data = exp_data.load_arms(ctx.store, wid, dim, start, ctx.now, cells)
    sc = st["scopes"][name]
    out = er.daily_look(data, st["control"], active, len(st["family"]), alpha, arm_t=sc["arm_t"],
                        looks_taken=sc["looks"], ramped=st["ramped"], exposure_days=exposure_days, max_drop=_guard(wf))
    if out.took_look:
        sc["looks"], sc["arm_t"] = out.look_index, out.arm_t
    ctx.store.add_decision(ctx.now, "experiment_look", f"{dim} {name}: " + "; ".join(
        f"{a} lift {r['lift']:+.1%} z {r['z']:.2f}" + (f" bound {r['boundary']:.2f}" if r.get("boundary") else "")
        for a, r in sorted(out.records.items()) if r["ok"]) + (f" [look {out.look_index}]" if out.took_look else ""), wid,
        {"dim": dim, "scope": name, "control": st["control"], "alpha": alpha, "took_look": out.took_look,
         "look_index": out.look_index, "records": out.records, "drop": out.drop, "ramp": out.ramp,
         "winner": out.winner, "family": st["family"], "exposure_days": round(exposure_days, 2)})
    return out


def _daily_look(ctx: PlanContext, st: dict, wid: str, dim: str, wf: Mapping, cfg: tuple[int, dict]) -> None:
    start = _start(ctx, st, wid, dim)
    st["last_look_day"] = ctx.now // DAY
    active = sorted(a for a, v in st["arms"].items() if v["state"] == "active")
    if start is None or not active:
        return
    days = (ctx.now - start) / DAY
    main = _scope_look(ctx, st, wid, dim, wf, "all", settings.EXP_ALPHA_WORKFLOW, None, active, days, start)
    winner, scope, rec, cells = main.winner, "workflow", main.records.get(main.winner or ""), None
    for g in _groups(ctx, st, wid, cfg):
        out = _scope_look(ctx, st, wid, dim, wf, g["name"], settings.EXP_ALPHA_GROUP, g["cells"], active, days, start)
        if winner is None and out.winner:
            winner, scope, rec, cells = out.winner, f"analysis group {g['name']} ({'+'.join(g['cohorts'])})", out.records[out.winner], g
    if winner:
        _promote(ctx, st, wid, dim, winner, scope, rec, cells)
        return
    ended = st["scopes"]["all"]["looks"] >= len(settings.EXP_LOOK_FRACTIONS)
    if ended and not st.get("exhausted"):  # no winner after the last planned look: stop learning, do not revert
        st["exhausted"] = True
        ctx.store.add_decision(ctx.now, "experiment_exhausted", f"{dim}: all {len(settings.EXP_LOOK_FRACTIONS)} planned looks "
                               "used without a winner; no promotion will be made. Reverting the surviving challengers would "
                               "itself be an unvalidated customer-facing change, so they keep their shares under the drop "
                               "and harm-stop rules only", wid, {"dim": dim, "shares": st["shares"]})
    shares = exp_alloc.next_shares(st["shares"], main.ramp, main.drop, [] if ended else st.get("untested", []))
    for a in main.drop:
        st["arms"][a]["state"] = "dropped"
    st["ramped"] = sorted(set(st["ramped"]) | set(main.ramp))
    for a in shares:
        st["arms"].setdefault(a, {"state": "active"})
        if a not in st["family"]:
            st["family"] = sorted(st["family"] + [a])
    st["untested"] = [o for o in st.get("untested", []) if o not in shares]
    if not shares:
        _conclude(ctx, st, wid, dim, "no challenger left")
    elif shares != st["shares"]:
        weights = exp_alloc.weights(st["control"], shares)
        summary, rationale = prop.update(dim, weights, main.ramp, main.drop, main.records, st["note"])
        _set_desired(st, weights, "experiment_update", summary, rationale, extra={"records": main.records})
    st["shares"] = shares


def _conclude(ctx, st, wid, dim, why: str) -> None:
    for a, v in st["arms"].items():
        if v["state"] == "active":
            v["state"] = "dropped"
    st["shares"] = {}
    summary = f"End {dim} experiment: {why}; all traffic back to control {st['control']}"
    _set_desired(st, {st["control"]: 1.0}, "experiment_conclude", summary, summary, then=xs.CLOSED)
    ctx.store.add_decision(ctx.now, "experiment_conclude", summary, wid, {"dim": dim, "control": st["control"]})


def _promote(ctx, st, wid, dim, winner, scope, rec, group) -> None:
    weights = exp_alloc.promotion_weights(winner, st["control"])
    cohort_weights = {}
    if group:
        cohort_weights = {cid: weights for cid in group["cohorts"]}
        weights = {st["control"]: 1.0}  # challengers elsewhere have no evidence: back to control
    summary, rationale = prop.promotion(dim, scope, winner, st["control"], rec, exp_alloc.promotion_weights(winner, st["control"]))
    st["promo"] = {"winner": winner, "old_control": st["control"], "scope": scope, "cells": group["cells"] if group else None,
                   "cohorts": group["cohorts"] if group else None, "decided_minute": ctx.now}
    for a, v in st["arms"].items():
        v["state"] = "winner" if a == winner else ("dropped" if v["state"] == "active" else v["state"])
    st["shares"] = {}
    _set_desired(st, weights, "experiment_promote", summary, rationale, cohort_weights=cohort_weights, then=xs.PROMOTED,
                 extra={"record": rec, "scope": scope})
    ctx.store.add_decision(ctx.now, "experiment_promote", summary, wid, {"dim": dim, "record": rec, "scope": scope})


def _harm_check(ctx, st, wid, dim, wf) -> None:
    start = _start(ctx, st, wid, dim)
    st["last_check"] = ctx.now
    active = sorted(a for a, v in st["arms"].items() if v["state"] == "active")
    if start is None or not active:
        return
    data = exp_data.load_arms(ctx.store, wid, dim, start, ctx.now)
    stops = {a: m for a, m in er.harm_stops(er.summarise(data, st["control"], active)).items() if m == "now"}
    if not stops:
        return
    rows = er.summarise(data, st["control"], active)
    shares = {a: s for a, s in st["shares"].items() if a not in stops}
    for a in stops:
        st["arms"][a]["state"] = "harm_stopped"
    st["shares"] = shares
    arm = sorted(stops)[0]
    summary, rationale = prop.harm_stop(dim, arm, rows[arm])
    weights = exp_alloc.weights(st["control"], shares)
    _set_desired(st, weights, "experiment_harm_stop", summary, rationale, severe=True,
                 then=xs.RUNNING if shares else xs.CLOSED, extra={"records": rows}, impact=1.0)
    ctx.store.add_decision(ctx.now, "experiment_harm_stop", summary, wid, {"dim": dim, "records": rows, "stopped": sorted(stops)})


# ------------------------------------------------------------------ promoted: decay and rollback
def _decay_check(ctx, st, wid, dim) -> None:
    st["last_check"] = ctx.now
    promo = st.get("promo") or {}
    since = promo.get("minute")
    if since is None or st["desired"]:
        return
    cells = promo.get("cells")
    ref, pooled = exp_decay.reference_rates(ctx.store, wid, dim, promo["old_control"], since // DAY - 1, cells)
    blocks = exp_decay.winner_blocks(ctx.store, wid, dim, promo["winner"], since, ref, pooled, cells)
    cus = exp_decay.cusum(blocks)
    held = exp_decay.holdout_view(ctx.store, wid, dim, promo["winner"], promo["old_control"], since, ctx.now, cells)
    roll, why = exp_decay.decide(cus, held)
    status = {"cusum": cus, "holdout": held, "rollback": roll}
    if json.dumps(status, sort_keys=True) != json.dumps(st.get("decay_status"), sort_keys=True) and (
            roll or ctx.now // DAY != st.get("decay_note_day")):
        st["decay_note_day"] = ctx.now // DAY
        ctx.store.add_decision(ctx.now, "experiment_decay_check", f"{dim} {promo['winner']} after promotion: blocks "
                               f"{cus['blocks']}, CUSUM S {cus['S']}, holdout recent lift {held.get('recent_lift')}", wid, status)
    st["decay_status"] = status
    if roll:
        summary, rationale = prop.rollback(dim, promo["winner"], promo["old_control"], why)
        cohort_weights = {cid: {promo["old_control"]: 1.0} for cid in (promo.get("cohorts") or [])}
        _set_desired(st, {promo["old_control"]: 1.0}, "experiment_rollback", summary, rationale, severe=True,
                     cohort_weights=cohort_weights, then=xs.CLOSED, extra=status, impact=0.5)
        ctx.store.add_decision(ctx.now, "experiment_rollback", summary, wid, status)


# ------------------------------------------------------------------ detector / producer
def _step(ctx: PlanContext, wid: str, dim: str, wf: Mapping) -> None:
    cfg = latest_config(ctx.store, wid)
    if cfg is None:
        return
    st = xs.load(ctx.store, wid, dim) or _new_state(wf, dim, cfg)
    before = json.dumps(st, sort_keys=True)
    st = _watch(ctx, st, wid, dim, cfg)
    pending_promotion = bool(st["desired"] and st["desired"]["kind"] == "experiment_promote")
    if st["phase"] == xs.PENDING:
        if ctx.now >= st["not_before"] and not st["desired"]:
            _plan_entry(ctx, st, wid, dim)
    elif st["phase"] == xs.RUNNING and not pending_promotion:
        if ctx.now % DAY >= wf["dialling_window"][1] * 60 and st["last_look_day"] < ctx.now // DAY:
            _daily_look(ctx, st, wid, dim, wf, cfg)
        elif ctx.now - st["last_check"] >= settings.EXP_HARM_CHECK_MINUTES:
            _harm_check(ctx, st, wid, dim, wf)
    elif st["phase"] == xs.PROMOTED and ctx.now - st["last_check"] >= settings.EXP_HARM_CHECK_MINUTES:
        _decay_check(ctx, st, wid, dim)
    if json.dumps(st, sort_keys=True) != before:
        xs.save(ctx.store, wid, dim, st)


def experiments_detector(ctx: PlanContext) -> None:
    if not settings.ENABLE_EXPERIMENTS:
        return
    for wid in sorted(ctx.workflows):
        for dim in xs.DIMS:
            if xs.eligible(ctx.workflows[wid], dim):
                _step(ctx, wid, dim, ctx.workflows[wid])


def experiments_producer(ctx: PlanContext, wid: str) -> list[DesiredChange]:
    if not settings.ENABLE_EXPERIMENTS:
        return []
    wf, out = ctx.workflows[wid], []
    for dim in xs.DIMS:
        if not xs.eligible(wf, dim):
            continue
        d = (xs.load(ctx.store, wid, dim) or {}).get("desired")
        if not d:
            continue
        auto = d["severe"] and _auto_ok(wf, dim)  # entry/ramp/drop/promote are customer-facing: always approval
        evidence = {"rationale": d["rationale"], "dry_run_extra": {"experiment": {"dim": dim, "kind": d["kind"], **d["evidence"]}}}
        if d["impact"] is not None:
            evidence["impact_override"] = d["impact"]
        out.append(DesiredChange(wid, d["kind"], Priority.SEVERE if d["severe"] else Priority.ROUTINE,
                                 xs.desired_patch(dim, d), ROUTE_AUTO if auto else ROUTE_APPROVAL, evidence, d["summary"]))
    return out


def register(registry=DEFAULT_REGISTRY) -> None:
    registry.register_detector(experiments_detector)
    registry.register_producer(experiments_producer)
