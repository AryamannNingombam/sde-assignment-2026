"""Caller-ID health detector and producer (CONTEXT C5), behind ``settings.ENABLE_DID``.

Detector (each tick, before the planner): learn the fatigue curve (refit once per sim day), run the
step test (FLAGGED -> incident mode) and the peer comparison (WEAK BASE, passing), persist the
verdicts and write a ``decisions`` row with every input so ``why`` can explain it.

Producer (pure function of persisted state + data): the caller-ID allocation we currently want,
as a bounded step (auto-apply where the policy allows it, otherwise one approval).
"""
from __future__ import annotations

import logging
from typing import Mapping

from .. import settings
from ..configlib import dist
from ..desired import DEFAULT_REGISTRY, ROUTE_APPROVAL, ROUTE_AUTO, DesiredChange, PlanContext, Priority
from ..incidents import close_incident, open_incident, open_incidents
from . import did_data, did_eval, did_plan
from .common import latest_config, load_state, save_state
from .did_plan import BAD, FLAGGED, SUSPECT, TESTED, UNTESTED, WEAK
from .fatigue_curve import FatigueCurve, fit_curve

log = logging.getLogger(__name__)
DETECTOR = "did"
MEMO: dict[tuple[str, str], tuple[int, did_eval.Evaluation, dict]] = {}


# ------------------------------------------------------------------ persisted verdicts
def _state(store, wid: str) -> dict:
    st = load_state(store, DETECTOR, wid)
    for key in ("flagged", "weak", "tested"):
        st.setdefault(key, {})
    return st


def _curve(store, wid: str, series, now: int, st: dict) -> FatigueCurve:
    day = now // 1440
    if st.get("curve") and st.get("curve_day") == day:
        return FatigueCurve.from_json(st["curve"])
    curve = fit_curve(series.obs())
    st["curve"], st["curve_day"] = curve.to_json(), day
    store.add_decision(now, "did_curve_fit", f"fatigue curve refit: tau={curve.tau_hours:.0f}h"
                       f" fitted={curve.fitted} points={curve.n_obs}", wid, curve.params())
    return curve


def status_of(ev: did_eval.Evaluation, did: str, st: Mapping) -> str:
    if did in st["flagged"]:
        return FLAGGED
    if did in st["weak"]:
        return WEAK
    if did in st["tested"]:
        return TESTED
    first = ev.first_hour.get(did)
    if (ev.total_dials.get(did, 0) < settings.DID_PASS_MIN_DIALS or first is None
            or ev.cur_hour - first < settings.DID_PASS_MIN_AGE_HOURS):
        return UNTESTED
    peer = ev.peers.get(did)
    if peer is None or peer.q >= settings.DID_PASS_RATIO:
        return TESTED
    return SUSPECT


def h_bar(ev: did_eval.Evaluation, alloc: Mapping[str, float]) -> float:
    total = sum(alloc.values()) or 1.0
    return sum(w * ev.curve.h(ev.loads_now.get(d, 0.0)) for d, w in alloc.items()) / total


# ------------------------------------------------------------------ detector
def _evaluate(ctx: PlanContext, wid: str) -> tuple[did_eval.Evaluation, dict] | None:
    """Evaluation at ``ctx.now`` (memoised per tick), plus the mutable verdict state."""
    key = (str(ctx.store.path), wid)
    memo = MEMO.get(key)
    if memo and memo[0] == ctx.now:
        return memo[1], memo[2]
    options = ctx.workflows[wid]["options"]["caller_id"]
    series = did_data.load_series(ctx.store, wid, ctx.now)
    if not any(series.total_dials(d) for d in options):
        return None
    st = _state(ctx.store, wid)
    curve = _curve(ctx.store, wid, series, ctx.now, st)
    ev = did_eval.evaluate(series, curve, ctx.now // 60, options, list(st["flagged"]),
                           list(st["flagged"]) + list(st["weak"]))
    MEMO[key] = (ctx.now, ev, st)
    return ev, st


def _flag(ctx: PlanContext, wid: str, ev, st: dict, step: did_eval.StepResult) -> None:
    q_est = step.test.q_window / max(step.test.q_ref, 1e-9)
    st["flagged"][step.did] = {"minute": ctx.now, "drop": round(step.test.drop, 4), "p": step.test.p,
                               "q_est": round(1.0 - step.test.drop, 4), "n": step.n_window}
    open_incident(ctx.store, wid, "did_flagged", ctx.now,
                  {"did": step.did, "step": step.as_dict(), "q_est": round(q_est, 4)})
    msg = (f"FLAGGED {step.did}: pickup ratio vs peers fell {step.test.drop:.0%} (p={step.test.p:.1e}, "
           f"{step.n_window} dials in {step.window_hours}h vs {step.n_ref} in prior day); incident mode")
    ctx.store.add_decision(ctx.now, "did_flagged", msg, wid, {"step": step.as_dict(),
                                                              "curve": ev.curve.params()})
    ctx.store.add_alert(ctx.now, "warn", "did_flagged", msg, wid)


def _mark_weak_and_tested(ctx: PlanContext, wid: str, ev, st: dict, options) -> None:
    for did, res in ev.peers.items():
        if did in st["flagged"] or did in st["weak"]:
            continue
        if res.weak():
            st["weak"][did] = {"minute": ctx.now, "q": round(res.q, 4), "z": round(res.z_weak, 3)}
            ctx.store.add_decision(ctx.now, "did_weak_base",
                                   f"WEAK BASE {did}: pickup {res.q:.2f}x expected at comparable load "
                                   f"(z={res.z_weak:.1f}, n={res.n})", wid, res.as_dict())
    for did in options:
        if did not in st["tested"] and status_of(ev, did, st) == TESTED:
            st["tested"][did] = ctx.now
            ctx.store.add_decision(ctx.now, "did_tested", f"{did} passes: not worse than peers at its load",
                                   wid, {"did": did, "peer": ev.peers[did].as_dict() if did in ev.peers else None,
                                         "dials": ev.total_dials.get(did)})


def _close_evacuated(ctx: PlanContext, wid: str, st: dict) -> None:
    cfg = latest_config(ctx.store, wid)
    if cfg is None:
        return
    share = dist(cfg[1], "default", "caller_id")
    for inc in open_incidents(ctx.store, wid, "did_flagged"):
        did = inc["body"]["did"]
        if share.get(did, 0.0) <= 1e-9:
            close_incident(ctx.store, inc["id"], ctx.now, f"{did} evacuated: share 0 in config v{cfg[0]}")


def did_detector(ctx: PlanContext) -> None:
    if not settings.ENABLE_DID:
        return
    for wid in sorted(ctx.workflows):
        options = ctx.workflows[wid]["options"]["caller_id"]
        if len(options) < 2:
            continue
        got = _evaluate(ctx, wid)
        if got is None:
            continue
        ev, st = got
        active = sum(ev.window_dials.values()) > 0 and ctx.now % 1440 // 60 in range(*ctx.workflows[wid]["dialling_window"])
        flagged = did_eval.flagged_step(ev.steps) if active else None
        if flagged is not None and flagged.did not in st["flagged"]:
            _flag(ctx, wid, ev, st, flagged)
        _mark_weak_and_tested(ctx, wid, ev, st, options)
        _close_evacuated(ctx, wid, st)
        save_state(ctx.store, DETECTOR, wid, st)
        if active:
            _log_evaluation(ctx, wid, ev, st, options)


def _log_evaluation(ctx, wid: str, ev, st: dict, options) -> None:
    status = {d: status_of(ev, d, st) for d in options}
    best = min(ev.steps, key=lambda r: r.test.p, default=None)
    inputs = {"status": status, "curve": ev.curve.params(), "loads": {d: round(v, 1) for d, v in ev.loads_now.items()},
              "window_dials": ev.window_dials, "peers": {d: r.as_dict() for d, r in ev.peers.items()},
              "best_step": best.as_dict() if best else None, "flagged": st["flagged"], "weak": st["weak"]}
    ctx.store.add_decision(ctx.now, "did_eval", "caller-ID evaluation: " + ", ".join(
        f"{d}={s}" for d, s in status.items()), wid, inputs)


# ------------------------------------------------------------------ producer
def _auto_limit(wf: Mapping) -> float | None:
    pol = wf["governance"]["auto_apply"]
    if pol.get("enabled") and "caller_id" in pol.get("allowed_dims", []):
        return float(pol["max_shift"])
    return None


def _keys(cfg: Mapping) -> list[str]:
    return ["default"] + [c["id"] for c in cfg["cohorts"]
                          if "caller_id" in (cfg["allocations"].get(c["id"]) or {})]


def did_producer(ctx: PlanContext, wid: str) -> list[DesiredChange]:
    if not settings.ENABLE_DID:
        return []
    wf = ctx.workflows[wid]
    options = wf["options"]["caller_id"]
    cfg = latest_config(ctx.store, wid)
    if len(options) < 2 or cfg is None:
        return []
    got = _evaluate(ctx, wid)
    if got is None:
        return []
    ev, st = got
    status = {d: status_of(ev, d, st) for d in options}
    limit = _auto_limit(wf)
    patch: dict = {}
    notes: list[str] = []
    for key in _keys(cfg[1]):
        cur = dist(cfg[1], key, "caller_id")
        target = did_plan.target_allocation(cur, status, h_bar(ev, cur))
        step = did_plan.plan_step(cur, target, limit, status)
        if did_plan.tv(cur, step) < settings.DID_MIN_TV:
            continue
        patch.setdefault("allocations", {}).setdefault(key, {})["caller_id"] = step
        notes.append(f"{key}: " + ", ".join(f"{d} {cur.get(d, 0):.1%}->{step.get(d, 0):.1%}"
                                            for d in sorted(set(cur) | set(step))))
    if not patch:
        return []
    return [_change(wid, patch, status, st, ev, notes, limit, cfg[1])]


def _change(wid, patch, status, st, ev, notes, limit, cfg) -> DesiredChange:
    flagged_live = [d for d in st["flagged"]
                    if dist(cfg, "default", "caller_id").get(d, 0.0) > 1e-9]
    bad_live = [d for d in st["weak"] if dist(cfg, "default", "caller_id").get(d, 0.0) > 1e-9]
    status_txt = ", ".join(f"{d}={s}" for d, s in status.items())
    evidence = {"rationale": f"caller-ID load spreading; statuses: {status_txt}; " + "; ".join(notes)}
    route = ROUTE_AUTO if limit is not None else ROUTE_APPROVAL
    if flagged_live:
        worst = min(st["flagged"][d]["q_est"] for d in flagged_live)
        evidence["flag_evacuation"] = worst < settings.DID_EVAC_FAST_RATIO
        summary = (f"Evacuate flagged caller ID {', '.join(flagged_live)} (pickup ratio vs peers x{worst:.2f}): "
                   + "; ".join(notes))
        return DesiredChange(wid, "did_evacuation", Priority.INCIDENT, patch, route, evidence, summary)
    kind = "did_rebalance" if bad_live else ("did_probe" if UNTESTED in status.values() else "did_spread")
    summary = {"did_rebalance": "Move traffic off weak-base caller ID", "did_probe": "Probe/spread caller IDs within "
               "the safe probe cap", "did_spread": "Spread calls evenly over healthy caller IDs"}[kind]
    return DesiredChange(wid, kind, Priority.ROUTINE, patch, route, evidence,
                         f"{summary} (h-bar {h_bar(ev, dist(cfg, 'default', 'caller_id')):.2f}): " + "; ".join(notes))


def register(registry=DEFAULT_REGISTRY) -> None:
    registry.register_detector(did_detector)
    registry.register_producer(did_producer)
