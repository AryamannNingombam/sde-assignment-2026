"""Welcome/voice (and KYC caller-ID) experiments: screen -> confirm -> promote with holdback -> decay -> rollback.

One row per (workflow, dimension). Lifecycle (SUBMISSION §5):

  PLANNED --draft--> STARTING --apply--> STAGE1 (80/10/10, 2 days, daily uncorrected harm stop)
     STAGE1 --best survivor >= control--> ADVANCING --apply--> STAGE2 (50/50, fresh data, looks at n/2 and n)
     STAGE1 --none qualifies--> PLANNED with the next untested options (if days remain) | CONCLUDING
     STAGE2 --primary passes at alpha* and guardrail non-inferior--> PROMOTING --apply--> PROMOTED (90/10)
     STAGE2 --harm, or inconclusive and significantly worse--> CONCLUDING --apply--> KEPT_CONTROL
     STAGE2 --inconclusive, ahead or tied--> MONITORING_SPLIT (no change request)
     STAGE2 --inconclusive, behind but not significantly--> STEPPING_DOWN --apply--> MONITORING_SPLIT (90/10)
     PROMOTED --daily decay check fires--> ROLLING_BACK [--auto de-risk step--> DERISKED] --apply--> ROLLED_BACK
     DERISKED --3 clean daily windows--> RESTORING --apply--> PROMOTED | MONITORING_SPLIT (asked once)
     DERISKED --48h unresolved--> DERISKED_STALLED (terminal for automation; a human decides)
  Supervisor edit on the dimension (or cohorts) -> INVALIDATED. Rejected request -> REJECTED.

Data for a test is always filtered by config_version >= the stage's start version, so stages never share data
(no winner's curse) and next-campaign-only workflows are analysed by the version a call was dialled with.
"""
from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass, field

from . import configs, governance, impact, metrics, policy, settings, stats, store
from .clock import MIN_PER_DAY, fmt, hour_of_day

OWNER = "experiments"
RUNNING = ("STAGE1", "STAGE2", "PROMOTED", "MONITORING_SPLIT", "DERISKED")
MONITORED = ("PROMOTED", "MONITORING_SPLIT", "DERISKED")      # under the daily decay/harm check
TRANSITIONAL = ("STARTING", "ADVANCING", "PROMOTING", "CONCLUDING", "ROLLING_BACK", "ABORTING", "STEPPING_DOWN",
                "RESTORING")
TERMINAL = ("KEPT_CONTROL", "ROLLED_BACK", "INVALIDATED", "REJECTED", "DERISKED_STALLED", "EXHAUSTED")
ROUTINE_KINDS = ("explore", "advance", "promote", "conclude", "stepdown", "restore")


@dataclass
class Action:
    kind: str                       # explore | advance | promote | conclude | stepdown | restore | abort | rollback
    exp_id: int
    next_state: str
    patch: dict
    summary: str
    rationale: str
    impact: float
    analysis: dict = field(default_factory=dict)


class Experiments:
    def __init__(self, conn: sqlite3.Connection, specs: dict[str, dict]):
        self.conn, self.specs = conn, specs

    # ================================================================== tick
    def step(self, minute: int) -> None:
        for wf, spec in self.specs.items():
            with store.tx(self.conn):
                self._ensure_planned(wf, spec, minute)
                actions = []
                for exp in self._rows(wf, RUNNING + ("PLANNED",)):
                    act = self._evaluate(exp, spec, minute)
                    if act:
                        actions.append(act)
                self._draft(wf, spec, actions, minute)
                self._check_derisk_expiry(wf, minute)

    # ================================================================== planning
    def _ensure_planned(self, wf: str, spec: dict, minute: int) -> None:
        kpi_name = spec["objective"]["primary"]
        _, cur = configs.current(self.conn, wf)
        for dim in settings.EXPERIMENT_DIMS.get(kpi_name, ()):
            if self.conn.execute("SELECT 1 FROM experiments WHERE wf=? AND dim=?", (wf, dim)).fetchone():
                continue
            control_dist = cur["allocations"]["default"][dim]
            single = len(control_dist) == 1
            control = max(control_dist, key=control_dist.get)
            eid = self.conn.execute(
                "INSERT INTO experiments(wf, dim, kpi, stage, state, control, arms_json, screened_json, result_json,"
                " end_reason, updated_minute) VALUES(?,?,?,1,?,?, '[]', '[]', '{}', ?, ?)",
                (wf, dim, kpi_name, "PLANNED" if single else "EXHAUSTED", control,
                 None if single else "control is not a single option", minute)).lastrowid
            store.record_decision(self.conn, minute, wf, "experiment",
                                  "plan: test this dimension" if single else "plan: control must be a single option",
                                  {"dim": dim, "allocation": control_dist}, "planned" if single else "not started",
                                  experiment_id=eid)

    def _next_challengers(self, spec: dict, exp: sqlite3.Row) -> list[str]:
        screened = set(json.loads(exp["screened_json"]))
        untested = [o for o in spec["options"][exp["dim"]] if o != exp["control"] and o not in screened]
        return untested[:len(settings.STAGE1_SHARES)]          # catalogue order: there is no history to rank them

    # ================================================================== evaluation
    def _evaluate(self, exp: sqlite3.Row, spec: dict, minute: int) -> Action | None:
        state = exp["state"]
        if state == "PLANNED":
            return self._plan_stage1(exp, spec, minute)
        if state == "STAGE1":
            return self._eval_stage1(exp, spec, minute)
        if state == "STAGE2":
            return self._eval_stage2(exp, spec, minute)
        if state in MONITORED:
            return self._eval_decay(exp, spec, minute)
        return None

    def _plan_stage1(self, exp: sqlite3.Row, spec: dict, minute: int) -> Action | None:
        arms = self._next_challengers(spec, exp)
        days_left = self._days_left(minute)
        if not arms:
            self._set(exp, minute, "EXHAUSTED", "plan: no untested options left", {})
            return None
        needed = settings.STAGE1_DAYS + 1
        if days_left < needed:
            self._set(exp, minute, "EXHAUSTED",
                      f"plan: {days_left:.1f} days left, a stage-1 screen needs {needed}", {})
            return None
        shares = dict(zip(arms, settings.STAGE1_SHARES))
        if sum(shares.values()) > settings.MAX_UNTESTED_TOTAL + 1e-9 \
                or max(shares.values()) > settings.MAX_UNTESTED_PER_ARM + 1e-9:
            raise ValueError("settings.STAGE1_SHARES exceed the untested-exposure caps")
        alloc = {exp["control"]: 1 - sum(shares.values()), **shares}
        mdes = self._stage1_mde(exp, spec)
        return Action("explore", exp["id"], "STAGE1", {"allocations": {"default": {exp["dim"]: alloc}}},
                      f"Screen {exp['dim']} {', '.join(arms)} at {int(settings.STAGE1_SHARES[0] * 100)}% each "
                      f"(control {exp['control']} keeps {round(alloc[exp['control']] * 100)}%)",
                      f"{', '.join(arms)} have never run on {exp['wf']}, so their effect is unknown. A 2-day screen at "
                      f"<= {int(settings.MAX_UNTESTED_PER_ARM * 100)}% per option bounds the exposure; a daily harm "
                      f"stop removes any option that is worse than control. Survivors are confirmed 50/50 on fresh "
                      f"data before anything is promoted.",
                      impact.score_exploration(sum(shares.values())),
                      {"design": "stage 1 screen", "arms": arms, "control": exp["control"], "kpi": exp["kpi"],
                       "smallest_harm_detectable_by_day_2": mdes})

    def _eval_stage1(self, exp: sqlite3.Row, spec: dict, minute: int) -> Action | None:
        start = self._data_start(exp)
        if start is None:
            return None
        look = exp["looks_done"] + 1
        if minute < start + look * MIN_PER_DAY:
            return None
        arms = json.loads(exp["arms_json"])
        data = self._arm_counts(exp, exp["start_version"])
        ctrl = data.get(exp["control"], metrics.Counts())
        harm = self._harm(exp, data, arms, settings.HARM_ALPHA)
        inputs = {"look": look, "counts": _counts_dict(data, exp["kpi"]), "harm_p": harm["p"], "stage": 1}
        self.conn.execute("UPDATE experiments SET looks_done=?, last_look_minute=? WHERE id=?", (look, minute, exp["id"]))
        survivors = [a for a in arms if a not in harm["drop"]]
        if look < settings.STAGE1_DAYS:
            if harm["drop"]:
                return self._abort_arms(exp, harm["drop"], survivors, data, inputs, minute)
            store.record_decision(self.conn, minute, exp["wf"], "experiment", "stage1 daily harm look: no harm",
                                  inputs, "continue", experiment_id=exp["id"])
            return None
        # end of stage 1: advancement rule
        c_rate = ctrl.rate(exp["kpi"]) or 0.0
        ranked = sorted(survivors, key=lambda a: (-(data.get(a, metrics.Counts()).rate(exp["kpi"]) or -1),
                                                  spec["options"][exp["dim"]].index(a)))
        best = next((a for a in ranked if (data.get(a, metrics.Counts()).rate(exp["kpi"]) or -1) >= c_rate), None)
        inputs.update({"survivors": survivors, "dropped": harm["drop"], "best": best})
        if best is None:
            store.record_decision(self.conn, minute, exp["wf"], "experiment",
                                  "stage1 end: no survivor at or above control", inputs, "screen next or conclude",
                                  experiment_id=exp["id"])
            return self._conclude(exp, data, inputs, minute, reason="no challenger survived screening",
                                  then_state="PLANNED_NEXT")
        alloc = {exp["control"]: 1 - settings.STAGE2_SHARE, best: settings.STAGE2_SHARE}
        n_req = self._n_required(exp)
        days = n_req / max(1.0, self._daily_units(exp) * settings.STAGE2_SHARE)
        inputs.update({"n_required_per_arm": n_req, "expected_days": round(days, 1)})
        b = data[best]
        return Action("advance", exp["id"], "STAGE2", {"allocations": {"default": {exp["dim"]: alloc}}},
                      f"Confirm {exp['dim']} {best} vs {exp['control']} at 50/50",
                      f"{best} passed a 2-day harm screen and had the highest {exp['kpi']} among survivors "
                      f"({_pct(b.rate(exp['kpi']))} vs control {_pct(c_rate)}). Screening data is NOT reused: a fresh "
                      f"50/50 test needs {n_req} {_unit(exp['kpi'])} per arm (~{days:.1f} days) to detect "
                      f"{settings.STAGE2_MDE[exp['kpi']] * 100:.0f}pp at one-sided alpha "
                      f"{settings.ALPHA / settings.STAGE2_LOOKS}.",
                      impact.score_exploration(settings.STAGE2_SHARE),
                      {**inputs, "design": "stage 2 confirmation", "challenger": best})

    def _eval_stage2(self, exp: sqlite3.Row, spec: dict, minute: int) -> Action | None:
        start = self._data_start(exp)
        if start is None:
            return None
        arms = json.loads(exp["arms_json"])
        ch = arms[0]
        data = self._arm_counts(exp, exp["start_version"])
        res = json.loads(exp["result_json"])
        harm_looks = res.get("harm_looks", 0)
        if minute >= start + (harm_looks + 1) * MIN_PER_DAY:
            res["harm_looks"] = harm_looks + 1
            self._save_result(exp, res)
            harm = self._harm(exp, data, arms, settings.HARM_ALPHA)
            inputs = {"stage": 2, "harm_look": harm_looks + 1, "counts": _counts_dict(data, exp["kpi"]),
                      "harm_p": harm["p"]}
            if harm["drop"]:
                return self._conclude(exp, data, inputs, minute, reason=f"{ch} worse than control (harm stop)")
            store.record_decision(self.conn, minute, exp["wf"], "experiment", "stage2 daily harm look: no harm",
                                  inputs, "continue", experiment_id=exp["id"])
        n_req = exp["n_required"]
        if exp["looks_done"] >= settings.STAGE2_LOOKS:
            # Every pre-declared look is spent; we are back here because a promotion request didn't land. No new
            # test: re-propose only if a look already passed AND the result still holds now. Requiring both can only
            # lower the false-winner rate, so the family-wise alpha stays <= ALPHA.
            verdict = self.test_promotion(exp, spec, data, self._recent(exp, minute))
            inputs = {"stage": 2, "recheck_of_passed_look": res.get("passed_look"),
                      "promote_asks": res.get("promote_asks", 0), **verdict}
            if res.get("passed_look") and verdict["promote"] and \
                    res.get("promote_asks", 0) < settings.PROMOTE_MAX_ASKS:
                return self._promote(exp, spec, verdict, inputs, minute)
            return self._end_inconclusive(exp, spec, data, verdict, inputs, minute)
        look = exp["looks_done"] + 1
        n_min = min(data.get(o, metrics.Counts()).num_den(exp["kpi"])[1] for o in (exp["control"], ch))
        due = n_min >= math.ceil(n_req * look / settings.STAGE2_LOOKS)
        spaced = exp["last_look_minute"] is None or minute - exp["last_look_minute"] >= MIN_PER_DAY
        if not (due and spaced):
            return None
        self.conn.execute("UPDATE experiments SET looks_done=?, last_look_minute=? WHERE id=?", (look, minute, exp["id"]))
        verdict = self.test_promotion(exp, spec, data, self._recent(exp, minute))
        inputs = {"stage": 2, "efficacy_look": look, "of": settings.STAGE2_LOOKS, "n_required": n_req, **verdict}
        if verdict["promote"]:
            res["passed_look"] = look
            self._save_result(exp, res)
            return self._promote(exp, spec, verdict, inputs, minute)
        if look >= settings.STAGE2_LOOKS:
            return self._end_inconclusive(exp, spec, data, verdict, inputs, minute)
        store.record_decision(self.conn, minute, exp["wf"], "experiment", "stage2 interim look: not yet significant",
                              inputs, "continue", experiment_id=exp["id"])
        return None

    def _end_inconclusive(self, exp, spec, data, verdict: dict, inputs: dict, minute: int) -> Action | None:
        """Pre-registered (SUBMISSION §5): inconclusive means "not proven better" AND "not proven worse".

        Three cases, by the evidence at the final look:
        - significantly worse on the primary or the guardrail (one-sided HARM_ALPHA): back to control;
        - not significantly worse and ahead or tied on the primary: keep the split as it is, no request, under
          the daily decay monitor. A full revert of an indistinguishable challenger is a coin flip;
        - behind but not significantly: step the challenger down to the screening share (the exposure we already
          accept for an untested option). After a test powered for MDE, a challenger that is behind is unlikely
          to be better, so 50% of traffic on it carries risk with no expected upside; a step-down bounds that
          without staking a full revert on a non-significant difference."""
        ch = verdict["challenger"]
        g_kpi, _ = _guardrail(spec)
        a, b = data.get(ch, metrics.Counts()), data.get(exp["control"], metrics.Counts())
        p_primary = stats.p_less(*a.num_den(exp["kpi"]), *b.num_den(exp["kpi"]))
        p_guard = stats.p_less(*a.num_den(g_kpi), *b.num_den(g_kpi))
        r1, r0 = a.rate(exp["kpi"]), b.rate(exp["kpi"])
        behind = r1 is not None and r0 is not None and r1 < r0
        inputs.update(p_primary_worse=_r(p_primary, 6), p_guardrail_worse=_r(p_guard, 6), challenger_behind=behind)
        if p_primary < settings.HARM_ALPHA or p_guard < settings.HARM_ALPHA:
            why = f"{exp['kpi']} significantly worse" if p_primary < settings.HARM_ALPHA \
                else f"guardrail {g_kpi} significantly worse"
            return self._conclude(exp, data, inputs, minute, reason=f"inconclusive at the final look and {why}: "
                                                                     "back to control")
        if not behind:
            self._keep_split(exp, minute, inputs, "inconclusive, ahead or tied and not shown worse: keep the split, "
                                                  "monitor daily")
            return None
        res = json.loads(exp["result_json"])
        if res.get("stepdown_asks", 0) >= settings.STEPDOWN_MAX_ASKS:
            self._keep_split(exp, minute, {**inputs, "stepdown_asks": res["stepdown_asks"]},
                             "inconclusive and behind, but the step-down request did not land "
                             f"{settings.STEPDOWN_MAX_ASKS} times: keep the split, monitor daily")
            return None
        res["stepdown_asks"] = res.get("stepdown_asks", 0) + 1
        self._save_result(exp, res)
        share = settings.INCONCLUSIVE_BEHIND_SHARE
        ctrl = exp["control"]
        return Action("stepdown", exp["id"], "MONITORING_SPLIT",
                      {"allocations": {"default": {exp["dim"]: {ctrl: 1 - share, ch: share}}}},
                      f"Step {exp['dim']} {ch} down from {int(settings.STAGE2_SHARE * 100)}% to {int(share * 100)}% "
                      f"(inconclusive and behind {ctrl})",
                      f"Final look inconclusive: {exp['kpi']} {_pct(r1)} vs {_pct(r0)} (n={verdict['n']}), not "
                      f"significantly worse (one-sided p={_r(p_primary, 4)}) but behind. A test powered for "
                      f"{settings.STAGE2_MDE[exp['kpi']] * 100:.0f}pp makes a real gain unlikely, so half the traffic "
                      f"is cut to the {int(share * 100)}% untested-option share instead of a full revert on a "
                      f"non-significant difference. The daily decay monitor keeps watching.",
                      impact.score_harm_avoided(max(0.0, (r0 or 0) - (r1 or 0)), settings.STAGE2_SHARE - share),
                      inputs)

    def test_promotion(self, exp: sqlite3.Row, spec: dict, data: dict[str, metrics.Counts],
                       recent: dict[str, metrics.Counts] | None = None) -> dict:
        """Primary one-sided z at alpha* = alpha / looks, plus guardrail non-inferiority, plus a recency check:
        the latest 24h must not show the challenger behind control. The pooled test can be carried by strong early
        days of a variant that is already fading; the recency check is an extra requirement, so it can only lower
        the false-winner rate. Deterministic."""
        ch, ctrl = json.loads(exp["arms_json"])[0], exp["control"]
        a, b = data.get(ch, metrics.Counts()), data.get(ctrl, metrics.Counts())
        x1, n1 = a.num_den(exp["kpi"])
        x0, n0 = b.num_den(exp["kpi"])
        alpha_star = settings.ALPHA / settings.STAGE2_LOOKS
        p = stats.p_greater(x1, n1, x0, n0)
        g_kpi, max_drop = _guardrail(spec)
        gx1, gn1 = a.num_den(g_kpi)
        gx0, gn0 = b.num_den(g_kpi)
        g_ok = stats.noninferior(gx1, gn1, gx0, gn0, max_drop, settings.GUARDRAIL_CI_Z)
        lcb = stats.diff_lower_bound(x1, n1, x0, n0, settings.GUARDRAIL_CI_Z)
        ra, rb = ((recent or {}).get(ch, metrics.Counts()), (recent or {}).get(ctrl, metrics.Counts()))
        r1, r0 = ra.rate(exp["kpi"]), rb.rate(exp["kpi"])
        recent_ok = recent is None or r1 is None or r0 is None or r1 >= r0
        return {"challenger": ch, "control": ctrl, "primary": exp["kpi"],
                "challenger_rate": _r(x1 / n1 if n1 else None), "control_rate": _r(x0 / n0 if n0 else None),
                "n": [n1, n0], "p_value": _r(p, 6), "alpha_star": alpha_star, "primary_pass": p < alpha_star,
                "lift_lcb95": _r(lcb), "guardrail": g_kpi, "guardrail_max_drop": max_drop,
                "guardrail_lcb95": _r(stats.diff_lower_bound(gx1, gn1, gx0, gn0, settings.GUARDRAIL_CI_Z)),
                "guardrail_pass": g_ok, "recent_challenger_rate": _r(r1), "recent_control_rate": _r(r0),
                "recent_not_behind": recent_ok, "promote": p < alpha_star and g_ok and recent_ok}

    def _promote(self, exp: sqlite3.Row, spec: dict, verdict: dict, inputs: dict, minute: int) -> Action:
        ch, ctrl, dim = verdict["challenger"], exp["control"], exp["dim"]
        res = json.loads(self._row(exp["id"])["result_json"])
        res["promote_asks"] = res.get("promote_asks", 0) + 1
        self._save_result(exp, res)
        carve = self._band_safety(exp, ch, minute)
        patch: dict = {"allocations": {"default": {dim: {ch: 1 - settings.HOLDBACK, ctrl: settings.HOLDBACK}}}}
        if carve:
            patch["cohorts_add"] = [{"id": _carve_id(dim, b), "where": {settings.SPLIT_FEATURE: [b]}} for b in carve]
            for b in carve:
                patch["allocations"][_carve_id(dim, b)] = {dim: {ctrl: 1.0}}
        inputs["carve_out_bands"] = carve
        self.conn.execute("UPDATE experiments SET carve_json=? WHERE id=?", (json.dumps(carve), exp["id"]))
        lift = verdict["lift_lcb95"] or 0.0
        return Action("promote", exp["id"], "PROMOTED", patch,
                      f"Promote {dim} {ch} to {int((1 - settings.HOLDBACK) * 100)}% (keep {ctrl} "
                      f"{int(settings.HOLDBACK * 100)}% holdback)" + (f"; keep {', '.join(carve)} on {ctrl}" if carve else ""),
                      f"50/50 test on fresh data: {exp['kpi']} {_pct(verdict['challenger_rate'])} vs "
                      f"{_pct(verdict['control_rate'])} (n={verdict['n']}), one-sided p={verdict['p_value']} < "
                      f"{verdict['alpha_star']}; lift lower 95% bound {lift * 100:+.1f}pp. Guardrail {verdict['guardrail']}"
                      f" lower bound {_pp(verdict['guardrail_lcb95'])} > -{verdict['guardrail_max_drop'] * 100:.0f}pp. "
                      f"A {int(settings.HOLDBACK * 100)}% holdback keeps a concurrent control so decay is caught.",
                      impact.score_promotion(lift, 1 - settings.HOLDBACK), inputs)

    def _band_safety(self, exp: sqlite3.Row, ch: str, minute: int) -> list[str]:
        """Bands where the challenger is significantly worse: they stay on control (a cohort carve-out)."""
        _, cur = configs.current(self.conn, exp["wf"])
        room = settings.MAX_COHORTS_PER_WF - len(cur.get("cohorts", []))
        out = []
        for band in ("18-30", "31-45", "46-60", "60+"):
            d = metrics.by_option(self.conn, exp["wf"], exp["dim"], min_version=exp["start_version"],
                                  cohorts=self._cohorts(exp), age_band=band)
            a, b = d.get(ch, metrics.Counts()), d.get(exp["control"], metrics.Counts())
            p = stats.p_less(*a.num_den(exp["kpi"]), *b.num_den(exp["kpi"]))
            if p < settings.BAND_SAFETY_ALPHA and len(out) < room:
                out.append(band)
        return out

    def _eval_decay(self, exp: sqlite3.Row, spec: dict, minute: int) -> Action | None:
        res = json.loads(exp["result_json"])
        last = res.get("last_decay_check", exp["start_minute"])
        if hour_of_day(minute) != settings.DECAY_CHECK_HOUR or minute - last < MIN_PER_DAY:
            return None
        res["last_decay_check"] = minute
        res["decay_checks"] = res.get("decay_checks", 0) + 1
        self._save_result(exp, res)
        ch = json.loads(exp["arms_json"])[0]
        h = minute // 60
        data = metrics.by_option(self.conn, exp["wf"], exp["dim"], since_hour=h - settings.DECAY_WINDOW_MIN // 60,
                                 until_hour=h, min_version=exp["start_version"], cohorts=self._cohorts(exp))
        a, b = data.get(ch, metrics.Counts()), data.get(exp["control"], metrics.Counts())
        alpha = settings.ALPHA / (res["d_max"] * settings.DECAY_METRICS)
        g_kpi, _ = _guardrail(spec)
        p_primary = stats.p_less(*a.num_den(exp["kpi"]), *b.num_den(exp["kpi"]))
        p_guard = stats.p_less(*a.num_den(g_kpi), *b.num_den(g_kpi))
        inputs = {"window": [fmt(minute - settings.DECAY_WINDOW_MIN), fmt(minute)], "alpha_decay": round(alpha, 5),
                  "counts": _counts_dict(data, exp["kpi"]), "p_primary_worse": _r(p_primary, 6),
                  "p_guardrail_worse": _r(p_guard, 6), "check": res["decay_checks"], "d_max": res["d_max"]}
        fired = p_primary < alpha or p_guard < alpha
        streak = res.get("decay_streak", 0) + 1 if fired else 0
        res["decay_streak"] = streak
        clean = 0 if fired else res.get("clean_windows", 0) + 1
        res["clean_windows"] = clean
        self._save_result(exp, res)
        inputs.update(consecutive_windows_fired=streak, consecutive_clean_windows=clean)
        if not fired:
            restore = res.get("pre_derisk")
            if exp["state"] == "DERISKED" and restore and not res.get("revert_requested") \
                    and clean >= settings.DERISK_RESTORE_WINDOWS \
                    and res.get("restore_asks", 0) < settings.RESTORE_MAX_ASKS:
                res["restore_asks"] = res.get("restore_asks", 0) + 1
                self._save_result(exp, res)
                return Action("restore", exp["id"], restore["state"],
                              {"allocations": {"default": {exp["dim"]: restore["alloc"]}}},
                              f"Undo the {exp['dim']} de-risk step: {ch} back to its "
                              f"{_pct(restore['alloc'].get(ch))} share",
                              f"The de-risk step was taken on one decay signal that never confirmed: "
                              f"{clean} consecutive clean daily windows since (one-sided alpha {alpha:.4f}). "
                              f"Changing config only on evidence cuts both ways, so the cut is offered back once.",
                              impact.score_exploration(restore["alloc"].get(ch, 0.0)), inputs)
            store.record_decision(self.conn, minute, exp["wf"], "experiment", "decay check: no decay", inputs,
                                  "keep the de-risked split" if exp["state"] == "DERISKED" else "keep",
                                  experiment_id=exp["id"])
            return None
        what = exp["kpi"] if p_primary < alpha else g_kpi
        harm = (b.rate(what) or 0) - (a.rate(what) or 0)
        impact_score = impact.score_harm_avoided(harm, 1 - settings.HOLDBACK)
        if res.get("revert_requested"):
            store.record_decision(self.conn, minute, exp["wf"], "experiment", "decay check fired again",
                                  inputs, "full revert already requested", experiment_id=exp["id"])
            return None
        if streak < settings.DECAY_CONFIRM_WINDOWS:
            # One window of a 10% holdback is ~100 calls: never enough on its own for a full revert. Cut exposure
            # with a single in-policy step if the policy allows one, and let the next fresh window decide.
            if exp["state"] in ("PROMOTED", "MONITORING_SPLIT") and not res.get("client_kept") \
                    and self._derisk_possible(exp, spec):
                _, cur = configs.current(self.conn, exp["wf"])
                res["pre_derisk"] = {"state": exp["state"], "alloc": configs.dist(cur, "default", exp["dim"])}
                res["restore_asks"] = 0
                self._save_result(exp, res)
                return Action("derisk", exp["id"], "DERISKED",
                              {"allocations": {"default": {exp["dim"]: {exp["control"]: 1.0}}}},
                              f"Cut {exp['dim']} {ch} exposure by one in-policy step (first decay signal)",
                              f"First decay signal ({what}: {ch} {_pct(a.rate(what))} vs holdback {exp['control']} "
                              f"{_pct(b.rate(what))}, one-sided p < {alpha:.4f}). One window of the holdback is small, "
                              f"so only exposure is cut now; the full revert is requested only if the next fresh "
                              f"daily window confirms.", impact_score, inputs)
            store.record_decision(self.conn, minute, exp["wf"], "experiment",
                                  "first decay signal: waiting for the next window to confirm", inputs, "watch",
                                  experiment_id=exp["id"])
            return None
        if res.get("client_kept"):
            # The client already rejected a rollback. Their decision stands unless fresh evidence confirms again
            # (the streak was reset on rejection), and even then they are asked at most CLIENT_KEPT_MAX_REASKS times.
            asks = res.get("kept_reasks", 0)
            inputs["reasks_after_client_kept"] = asks
            if asks >= settings.CLIENT_KEPT_MAX_REASKS:
                store.record_decision(self.conn, minute, exp["wf"], "experiment",
                                      "decay confirmed again, but the client kept this variant and was already "
                                      "re-asked: no further request", inputs, "keep (client decision)",
                                      experiment_id=exp["id"])
                return None
            res["kept_reasks"] = asks + 1
            self._save_result(exp, res)
        if exp["state"] == "DERISKED":
            self._draft_full_revert(exp, minute, impact_score, inputs)
            return None
        return Action("rollback", exp["id"], "ROLLED_BACK",
                      {"allocations": {"default": {exp["dim"]: {exp["control"]: 1.0}}}},
                      f"Roll back {exp['dim']} {ch} to {exp['control']} (winner decayed)",
                      f"Decay confirmed on {streak} consecutive daily windows; latest "
                      f"{inputs['window'][0]}..{inputs['window'][1]}: {ch} {_pct(a.rate(what))} vs holdback "
                      f"{exp['control']} {_pct(b.rate(what))} on {what}, one-sided p < {alpha:.4f} (alpha 0.05 split "
                      f"over {res['d_max']} checks and 2 metrics).", impact_score, inputs)

    # ================================================================== actions that end or shrink a test
    def _abort_arms(self, exp, drop, survivors, data, inputs, minute) -> Action:
        _, cur = configs.current(self.conn, exp["wf"])
        alloc = dict(configs.dist(cur, "default", exp["dim"]))
        for a in drop:
            alloc[exp["control"]] = alloc.get(exp["control"], 0) + alloc.pop(a, 0)
        harm = max((data[exp["control"]].rate(exp["kpi"]) or 0) - (data[a].rate(exp["kpi"]) or 0) for a in drop)
        inputs["dropped"] = drop
        return Action("abort", exp["id"], "STAGE1" if survivors else "PLANNED_NEXT",
                      {"allocations": {"default": {exp["dim"]: alloc}}},
                      f"Stop screening {exp['dim']} {', '.join(drop)} (worse than control)",
                      f"Daily harm look: {', '.join(drop)} below control {exp['control']} at one-sided p < "
                      f"{settings.HARM_ALPHA} (uncorrected on purpose: a false stop only costs time). Its traffic goes "
                      f"back to control.", impact.score_harm_avoided(harm, settings.MAX_UNTESTED_PER_ARM), inputs)

    def _conclude(self, exp, data, inputs, minute, *, reason: str, then_state: str = "KEPT_CONTROL") -> Action | None:
        _, cur = configs.current(self.conn, exp["wf"])
        if configs.dist(cur, "default", exp["dim"]) == {exp["control"]: 1.0}:
            self._finish_conclude(exp, then_state, minute, reason)
            return None
        arms = json.loads(exp["arms_json"])
        c = data.get(exp["control"], metrics.Counts()).rate(exp["kpi"]) or 0
        harm = max([c - (data.get(a, metrics.Counts()).rate(exp["kpi"]) or c) for a in arms] + [0])
        inputs["reason"] = reason
        return Action("conclude", exp["id"], then_state, {"allocations": {"default": {exp["dim"]: {exp["control"]: 1.0}}}},
                      f"End {exp['dim']} test: back to {exp['control']} 100% ({reason})",
                      f"{reason}. No winner is forced; the test result is recorded and challenger traffic returns to "
                      f"control.", impact.score_harm_avoided(harm, sum(1 for _ in arms) * settings.MAX_UNTESTED_PER_ARM),
                      inputs)

    def _d_max(self, minute: int) -> int:
        return max(1, math.ceil(self._days_left(minute))) if self._end() else settings.PRODUCTION_DECAY_DAYS

    def _keep_split(self, exp, minute: int, inputs: dict, rule: str) -> None:
        """Inconclusive and not shown worse: no change request; the split stays under the daily monitor."""
        res = json.loads(exp["result_json"])
        res.update(kept_split=True, promoted_minute=minute, d_max=self._d_max(minute))
        self._save_result(exp, res)
        store.record_decision(self.conn, minute, exp["wf"], "experiment", rule, inputs, "keep split",
                              experiment_id=exp["id"])
        self._set(exp, minute, "MONITORING_SPLIT", "split kept under monitoring (not a promotion)",
                  {"start_minute": minute, "stage": 3})

    def _finish_conclude(self, exp, then_state: str, minute: int, reason: str) -> None:
        if then_state == "PLANNED_NEXT":
            self._set(exp, minute, "PLANNED", f"screen next options ({reason})", {"stage": 1, "arms_json": "[]"})
        else:
            self._set(exp, minute, then_state, reason, {})

    # ================================================================== drafting (batched per workflow)
    def _draft(self, wf: str, spec: dict, actions: list[Action], minute: int) -> None:
        if not actions:
            return
        _, cur = configs.current(self.conn, wf)
        routine = [a for a in actions if a.kind in ROUTINE_KINDS]
        urgent = [a for a in actions if a.kind not in ROUTINE_KINDS]
        if routine:
            self._make_draft(wf, routine, "approval", False, minute)
        for a in urgent:                        # harm-reduction: auto where the policy allows, else approval
            if a.kind == "rollback" and json.loads(self._row(a.exp_id)["result_json"]).get("client_kept"):
                self._make_draft(wf, [a], "approval", True, minute)     # the client said no once: ask, never step
                continue
            target = configs.apply_patch(cur, a.patch)
            route = policy.route_change(spec, cur, target)
            if a.kind == "derisk":              # the one in-policy step toward control, nothing more
                self._make_draft(wf, [a], "auto", True, minute, kind="derisk", next_state="DERISKED",
                                 patch=_patch_from(route[0][1], a.patch))
            elif len(route) == 2:               # too big to auto-apply: the full change goes to approval
                self._make_draft(wf, [a], "approval", True, minute)
            else:
                self._make_draft(wf, [a], route[0][0], True, minute)

    def _make_draft(self, wf, acts: list[Action], path, urgent, minute, *, kind=None, next_state=None, patch=None,
                    hold_state: str | None = None):
        """One proposal for all `acts`. Experiments wait in a transitional state (or `hold_state`) until it lands."""
        merged: dict = {}
        for a in acts:
            merged = _merge(merged, a.patch)
        kind = kind or (acts[0].kind if len(acts) == 1 else "+".join(sorted({a.kind for a in acts})))
        inputs = {a.exp_id: a.analysis for a in acts}
        did = store.record_decision(self.conn, minute, wf, "experiment", f"{kind}: draft proposal",
                                    {"actions": [a.kind for a in acts], "analysis": inputs},
                                    "drafted", experiment_id=acts[0].exp_id)
        payload = {"change_summary": "; ".join(a.summary for a in acts),
                   "rationale": " | ".join(a.rationale for a in acts),
                   "impact_score": max(a.impact for a in acts),
                   "dry_run_extra": {str(k): v for k, v in inputs.items()}}
        pid = governance.draft(self.conn, minute, wf, kind, patch or merged, payload, owner=OWNER,
                               refs={"experiments": {str(a.exp_id): next_state or a.next_state for a in acts}},
                               decision_id=did, path=path, urgent=urgent)
        self.conn.execute("UPDATE decisions SET proposal_id=? WHERE id=?", (pid, did))
        for a in acts:
            exp = self._row(a.exp_id)
            res = json.loads(exp["result_json"])
            res["pending"] = {"kind": kind, "prev_state": exp["state"], "proposal_id": pid,
                              "arms_after": _arms_after(a, exp), "analysis": a.analysis}
            self._save_result(exp, res)
            self.conn.execute("UPDATE experiments SET state=?, updated_minute=? WHERE id=?",
                              (hold_state or _transitional(a.kind, kind), minute, a.exp_id))

    # ================================================================== governance callbacks
    def revalidate(self, conn, p, minute) -> tuple[bool, str]:
        for eid in json.loads(p["refs_json"])["experiments"]:
            exp = self._row(int(eid))
            if exp["state"] in TERMINAL:
                return False, f"experiment {eid} has ended ({exp['state']}: {exp['end_reason']})"
            pending = json.loads(exp["result_json"]).get("pending") or {}
            if pending.get("proposal_id") != p["proposal_id"] and pending.get("proposal_id") != p["parent_proposal_id"]:
                return False, f"experiment {eid} is no longer waiting for this change ({exp['state']})"
            if p["kind"] == "promote":
                data = self._arm_counts(exp, exp["start_version"])
                verdict = self.test_promotion(exp, self.specs[exp["wf"]], data, self._recent(exp, minute))
                if not verdict["promote"]:
                    return False, f"promotion no longer passes on data up to now: {verdict}"
        return True, "still valid"

    def on_applied(self, conn, p, version, minute) -> None:
        refs = json.loads(p["refs_json"])["experiments"]
        for eid, next_state in refs.items():
            exp = self._row(int(eid))
            if exp["state"] in TERMINAL and next_state != "ROLLED_BACK":
                store.record_decision(conn, minute, exp["wf"], "experiment", f"{p['kind']} landed after the test ended",
                                      {"state": exp["state"], "version": version}, "no state change",
                                      experiment_id=exp["id"], proposal_id=p["proposal_id"])
                continue
            res = json.loads(exp["result_json"])
            pending = res.pop("pending", {}) or {}
            cols: dict = {}
            if next_state in ("STAGE1", "STAGE2"):
                arms = pending.get("arms_after", [])
                fresh = next_state == "STAGE2" or exp["state"] == "STARTING"
                if fresh:
                    cols.update(start_version=version, start_minute=None, looks_done=0, last_look_minute=None,
                                stage=1 if next_state == "STAGE1" else 2)
                    screened = sorted(set(json.loads(exp["screened_json"])) | set(arms))
                    cols["screened_json"] = json.dumps(screened)
                    res.pop("harm_looks", None)
                if next_state == "STAGE2":
                    cols["n_required"] = self._n_required(exp)
                cols["arms_json"] = json.dumps(arms)
            elif next_state in ("PROMOTED", "MONITORING_SPLIT"):   # promote, step-down, or a de-risk undone
                cols.update(start_version=version, start_minute=minute, stage=3)
                res.update(d_max=self._d_max(minute), promoted_minute=minute, decay_streak=0, clean_windows=0)
                if next_state == "MONITORING_SPLIT":
                    res["kept_split"] = True
                for k in ("pre_derisk", "derisk_version"):
                    res.pop(k, None)
            elif next_state == "DERISKED":
                res["derisk_version"] = version     # the full revert waits for a confirming window
            elif next_state == "PLANNED_NEXT":
                next_state = "PLANNED"
                cols.update(arms_json="[]", stage=1)
            self._save_result(exp, res)
            self._set(exp, minute, next_state, f"{p['kind']} applied as v{version}", cols, proposal_id=p["proposal_id"])

    def on_terminal(self, conn, p, state, minute) -> None:
        for eid in json.loads(p["refs_json"])["experiments"]:
            exp = self._row(int(eid))
            res = json.loads(exp["result_json"])
            pending = res.pop("pending", {}) or {}
            prev = pending.get("prev_state", "STAGE1")
            if exp["state"] in TERMINAL:
                continue
            if p["kind"] == "rollback":
                res["revert_requested"] = False                  # a later confirmed signal may ask again
            if state == "REJECTED":
                if p["kind"] == "stepdown":                      # client wants the 50/50 kept: keep it, monitored
                    res.update(kept_split=True, promoted_minute=minute, d_max=self._d_max(minute))
                    self._save_result(exp, res)
                    self._set(exp, minute, "MONITORING_SPLIT",
                              "step-down rejected: client kept the 50/50 split; monitored daily", {"stage": 3,
                                                                                                  "start_minute": minute},
                              proposal_id=p["proposal_id"])
                    continue
                if p["kind"] == "restore":                       # client prefers the reduced share: it stays
                    res["restore_asks"] = settings.RESTORE_MAX_ASKS
                    self._save_result(exp, res)
                    self._set(exp, minute, prev, "undoing the de-risk step was rejected: reduced share kept", {},
                              proposal_id=p["proposal_id"])
                    continue
                if p["kind"] in ("rollback", "derisk"):
                    res["client_kept"] = True                    # client decided: no further auto steps
                    res["decay_streak"] = 0                      # asking again needs fresh confirmation
                    self._save_result(exp, res)
                    self._set(exp, minute, prev,
                              "rollback rejected: client kept the promoted variant despite decay evidence",
                              {"derisk_expires": None}, proposal_id=p["proposal_id"])
                    store.raise_alert(conn, minute, "summary", exp["wf"],
                                      f"client kept {exp['dim']} promotion despite decay evidence (exp {exp['id']})")
                else:
                    self._save_result(exp, res)
                    self._set(exp, minute, "REJECTED", f"{p['kind']} rejected by approver; current split kept", {},
                              proposal_id=p["proposal_id"])
                continue
            if p["kind"] == "rollback" and state in ("EXPIRED", "LAPSED"):
                res["revert_redrafts"] = res.get("revert_redrafts", 0) + 1
            self._save_result(exp, res)                          # expired/lapsed/dropped/stale: decide again
            self._set(exp, minute, prev, f"{p['kind']} {state.lower()}: re-decide from fresh data", {},
                      proposal_id=p["proposal_id"])
            if prev == "DERISKED" and res.get("revert_redrafts", 0) <= 1 and state in ("EXPIRED", "LAPSED"):
                payload = json.loads(p["payload_json"])
                self._draft_full_revert(self._row(exp["id"]), minute, payload["impact_score"],
                                        {"redraft_of": p["proposal_id"]})

    # ================================================================== supervisor edits
    def on_supervisor_edit(self, wf: str, dims: list[str], version: int, minute: int) -> None:
        for exp in self._rows(wf, RUNNING + TRANSITIONAL):
            if exp["dim"] in dims or "cohorts" in dims:
                self._invalidate(exp, minute, f"supervisor edit v{version} changed {dims}: experiment ended, their "
                                              "change preserved", "invalidated_by_supervisor")

    def invalidate(self, wf: str, dim: str, minute: int, reason: str) -> None:
        for exp in self._rows(wf, RUNNING + TRANSITIONAL):
            if exp["dim"] == dim:
                self._invalidate(exp, minute, reason, reason)

    def _invalidate(self, exp, minute: int, rule: str, end_reason: str) -> None:
        """End the test and forget any request it was waiting on, so that request can never go out later."""
        res = json.loads(exp["result_json"])
        res.pop("pending", None)
        self._save_result(exp, res)
        self._set(exp, minute, "INVALIDATED", rule, {"end_reason": end_reason})

    # ================================================================== de-risk
    def _recent(self, exp, minute: int) -> dict[str, metrics.Counts]:
        """Arm counters over the latest RECENT_WINDOW_MIN, same stage version and cohorts as the test."""
        h = minute // 60
        return metrics.by_option(self.conn, exp["wf"], exp["dim"], since_hour=h - settings.RECENT_WINDOW_MIN // 60,
                                 until_hour=h, min_version=exp["start_version"], cohorts=self._cohorts(exp))

    def _derisk_possible(self, exp, spec: dict) -> bool:
        """True when the full revert is too big to auto-apply but one in-policy step toward control is allowed."""
        _, cur = configs.current(self.conn, exp["wf"])
        target = configs.apply_patch(cur, {"allocations": {"default": {exp["dim"]: {exp["control"]: 1.0}}}})
        return len(policy.route_change(spec, cur, target)) == 2

    def _draft_full_revert(self, exp, minute: int, impact_score: float, analysis: dict) -> None:
        """Confirmed decay on a de-risked split: the rest of the revert goes to approval. Starts the 48h clock."""
        act = Action("rollback", exp["id"], "ROLLED_BACK",
                     {"allocations": {"default": {exp["dim"]: {exp["control"]: 1.0}}}},
                     f"Complete rollback of {exp['dim']} to {exp['control']} (decay confirmed; exposure already cut)",
                     f"Decay fired on {settings.DECAY_CONFIRM_WINDOWS} consecutive daily windows. The de-risk step "
                     f"already cut exposure by {self.specs[exp['wf']]['governance']['auto_apply']['max_shift']}; "
                     f"the rest needs approval.", impact_score, analysis)
        res = json.loads(exp["result_json"])
        res["revert_requested"] = True
        self._save_result(exp, res)
        self.conn.execute("UPDATE experiments SET derisk_expires=? WHERE id=?",
                          (minute + settings.DERISK_EXPIRY_MIN, exp["id"]))
        self._make_draft(exp["wf"], [act], "approval", True, minute, hold_state="DERISKED")

    def _check_derisk_expiry(self, wf: str, minute: int) -> None:
        for exp in self._rows(wf, ("DERISKED",)):
            if exp["derisk_expires"] is None or minute < exp["derisk_expires"]:
                continue
            self._set(exp, minute, "DERISKED_STALLED",
                      "de-risk expired unresolved: config kept as is, no further automatic change on this dimension",
                      {"end_reason": "derisk_stalled"})
            store.raise_alert(self.conn, minute, "page", wf,
                              f"{exp['dim']} rollback unresolved after 48h at the de-risked split: a human must decide")

    # ================================================================== helpers
    def _arm_counts(self, exp, min_version: int) -> dict[str, metrics.Counts]:
        return metrics.by_option(self.conn, exp["wf"], exp["dim"], min_version=min_version, cohorts=self._cohorts(exp))

    def _cohorts(self, exp) -> list[str]:
        _, cur = configs.current(self.conn, exp["wf"])
        return configs.cohorts_using_default(cur, exp["dim"])

    def _harm(self, exp, data, arms, alpha) -> dict:
        ctrl = data.get(exp["control"], metrics.Counts())
        p = {a: stats.p_less(*data.get(a, metrics.Counts()).num_den(exp["kpi"]), *ctrl.num_den(exp["kpi"])) for a in arms}
        return {"p": {a: _r(v, 6) for a, v in p.items()}, "drop": [a for a in arms if p[a] < alpha]}

    def _data_start(self, exp) -> int | None:
        """Calendar of looks starts at the first call dialled under the stage's version (matters on KYC)."""
        if exp["start_minute"] is not None:
            return exp["start_minute"]
        row = self.conn.execute("SELECT MIN(hour) FROM agg WHERE wf=? AND config_version>=?",
                                (exp["wf"], exp["start_version"])).fetchone()
        if row[0] is None:
            return None
        self.conn.execute("UPDATE experiments SET start_minute=? WHERE id=?", (row[0] * 60, exp["id"]))
        return row[0] * 60

    def _baseline(self, exp) -> float:
        c = metrics.total(self.conn, exp["wf"], until_hour=0)
        return c.rate(exp["kpi"]) or 0.5

    def _daily_units(self, exp) -> float:
        """Average trials per day in history, in the unit of the KPI under test."""
        c = metrics.total(self.conn, exp["wf"], until_hour=0)
        first_hour = self.conn.execute("SELECT MIN(hour) FROM agg WHERE wf=?", (exp["wf"],)).fetchone()[0] or -24
        return c.num_den(exp["kpi"])[1] / max(1, -first_hour // 24)

    def _n_required(self, exp) -> int:
        return stats.n_per_arm(self._baseline(exp), settings.STAGE2_MDE[exp["kpi"]],
                               settings.ALPHA / settings.STAGE2_LOOKS, settings.POWER)

    def _stage1_mde(self, exp, spec) -> dict:
        n = self._daily_units(exp) * settings.STAGE1_DAYS
        p = self._baseline(exp)
        share = settings.STAGE1_SHARES[0]
        return {"per_challenger_pp": round(stats.mde(p, n * share, n * (1 - sum(settings.STAGE1_SHARES)),
                                                     settings.HARM_ALPHA, settings.POWER) * 100, 1)}

    def _end(self) -> int | None:
        return store.get_meta(self.conn, "end_minute")

    def _days_left(self, minute: int) -> float:
        end = self._end()
        return (end - minute) / MIN_PER_DAY if end else float("inf")

    def _rows(self, wf: str, states: tuple[str, ...]) -> list[sqlite3.Row]:
        return self.conn.execute(f"SELECT * FROM experiments WHERE wf=? AND state IN ({','.join('?' * len(states))})"
                                 " ORDER BY id", (wf, *states)).fetchall()

    def _row(self, eid: int) -> sqlite3.Row:
        return self.conn.execute("SELECT * FROM experiments WHERE id=?", (eid,)).fetchone()

    def _save_result(self, exp, res: dict) -> None:
        self.conn.execute("UPDATE experiments SET result_json=? WHERE id=?", (json.dumps(res), exp["id"]))

    def _set(self, exp, minute: int, state: str, rule: str, cols: dict, proposal_id: str | None = None) -> None:
        cols = {"state": state, "updated_minute": minute, **cols}
        self.conn.execute(f"UPDATE experiments SET {', '.join(f'{k}=?' for k in cols)} WHERE id=?",
                          (*cols.values(), exp["id"]))
        store.record_decision(self.conn, minute, exp["wf"], "experiment", rule,
                              {"dim": exp["dim"], "from": exp["state"], "to": state}, state,
                              experiment_id=exp["id"], proposal_id=proposal_id)


# ====================================================================== module helpers
def _guardrail(spec: dict) -> tuple[str, float]:
    (key, drop), = spec["objective"]["guardrail"].items()
    return key.removesuffix("_max_drop"), float(drop)


def _transitional(action_kind: str, draft_kind: str) -> str:
    if draft_kind == "derisk":
        return "ROLLING_BACK"
    return {"explore": "STARTING", "advance": "ADVANCING", "promote": "PROMOTING", "conclude": "CONCLUDING",
            "abort": "ABORTING", "rollback": "ROLLING_BACK", "derisk": "ROLLING_BACK",
            "stepdown": "STEPPING_DOWN", "restore": "RESTORING"}[action_kind]


def _arms_after(a: Action, exp: sqlite3.Row) -> list[str]:
    """Challengers still live on this dimension once the action lands (control excluded)."""
    alloc = a.patch.get("allocations", {}).get("default", {}).get(exp["dim"], {})
    return [o for o in sorted(alloc, key=lambda o: -alloc[o]) if o != exp["control"]]


def _patch_from(cfg: dict, patch: dict) -> dict:
    """Patch that reproduces `cfg`'s allocation for every cohort/dim the original patch touched."""
    out = {"allocations": {}}
    for cohort, dims in patch.get("allocations", {}).items():
        out["allocations"][cohort] = {dim: configs.dist(cfg, cohort, dim) for dim in dims}
    return out


def _merge(a: dict, b: dict) -> dict:
    out = json.loads(json.dumps(a))
    for cohort, dims in b.get("allocations", {}).items():
        out.setdefault("allocations", {}).setdefault(cohort, {}).update(dims)
    if b.get("cohorts_add"):
        out.setdefault("cohorts_add", []).extend(b["cohorts_add"])
    return out


def _carve_id(dim: str, band: str) -> str:
    return f"keep_{dim}_{band.replace('+', 'plus').replace('-', '_')}"


def _counts_dict(data: dict[str, metrics.Counts], kpi: str) -> dict:
    return {o: {"x": c.num_den(kpi)[0], "n": c.num_den(kpi)[1], "rate": _r(c.rate(kpi))} for o, c in sorted(data.items())}


def _r(x, nd: int = 4):
    return None if x is None else round(float(x), nd)


def _pct(x) -> str:
    return "n/a" if x is None else f"{x * 100:.1f}%"


def _pp(x) -> str:
    return "n/a" if x is None else f"{x * 100:+.1f}pp"


def _unit(kpi: str) -> str:
    return "dials" if kpi == "pickup_rate" else "connected calls"
