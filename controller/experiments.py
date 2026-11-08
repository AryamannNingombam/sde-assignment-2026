"""Experiments, promotion and decay. Every winner here comes from a deterministic test.

Design in one paragraph: welcome and voice are sampled independently per call, so a single
allocation is a full factorial and each dimension's arms are compared marginally. Control keeps
half the traffic. Arms are compared with control, stratified by (config_version, prompt), and looked
at once a day against an O'Brien-Fleming alpha budget with Holm across arms. When an experiment
ends, one- and two-feature slices are scanned under Benjamini-Hochberg to find people for whom the
answer is different. After promotion a holdout on the old control keeps decay measurable.
"""
from __future__ import annotations

import json
import logging

from . import cohorts as ch
from . import config as cfg
from . import configops as co
from . import stats
from .evidence import DIM_COL, daily_connected
from .store import Store

log = logging.getLogger("controller.experiments")

KPI_COLS = {"engagement_rate": ("engaged", "connected"), "pickup_rate": ("connected", "dials")}
OTHER_KPI = {"engagement_rate": "pickup_rate", "pickup_rate": "engagement_rate"}
RUNNING = ("planned", "running", "concluding")


def guardrail_of(spec: dict) -> tuple[str, float]:
    for key, limit in spec["objective"].get("guardrail", {}).items():
        if key.endswith("_max_drop"):
            return key[: -len("_max_drop")], float(limit)
    return OTHER_KPI[spec["objective"]["primary"]], 0.02


class Experiments:
    def __init__(self, store: Store, governance, specs: dict[str, dict], segments: dict[int, dict], end_minute: int):
        self.store, self.gov, self.specs, self.segments, self.end_minute = store, governance, specs, segments, end_minute
        self.max_days = min(cfg.MAX_EXPERIMENT_DAYS, end_minute / 1440 * cfg.MAX_HORIZON_FRACTION)
        for kind, fn in (("experiment_start", self._started), ("promote", self._promoted), ("did_promote", self._promoted),
                         ("rollback", self._rolled_back), ("did_explore", self._started)):
            governance.on_applied[kind] = fn
        for kind in ("experiment_start", "did_explore"):
            governance.on_dropped[kind] = self._never_ran

    # --- planning -----------------------------------------------------------------------------
    def plan(self, wid: str, config: dict, now: int) -> None:
        """Opens experiments. Runs at most once per (workflow, dim, cohort) for the whole horizon."""
        spec = self.specs[wid]
        if self.end_minute - now < cfg.MIN_REMAINING_DAYS * 1440:
            return
        if self.store.q("SELECT 1 FROM incidents WHERE workflow_id=? AND status='open'", wid):
            return  # never start learning on top of a live incident
        if spec["objective"]["primary"] == "engagement_rate":
            for dim in ("welcome_message", "voice"):
                self._plan_dim(spec, config, dim, now)
        self._plan_did(spec, config, now)

    def _exists(self, wid: str, dim: str) -> bool:
        return bool(self.store.q("SELECT 1 FROM experiments WHERE workflow_id=? AND dim=? AND cohort_id='default'", wid, dim))

    def _plan_dim(self, spec: dict, config: dict, dim: str, now: int) -> None:
        wid = spec["workflow_id"]
        if self._exists(wid, dim):
            return
        current = co.effective(config, ch.DEFAULT, dim)
        options = spec["options"].get(dim, [])
        if not current or len(options) < 2:
            return
        control = max(sorted(current), key=lambda k: current[k])
        arms = [o for o in options if o != control]
        share = (1 - cfg.CONTROL_SHARE) / len(arms)
        dist = {control: cfg.CONTROL_SHARE, **{a: share for a in arms}}
        exp_id = f"{wid}:{dim}:default"
        kpi = spec["objective"]["primary"]
        connected = daily_connected(self.store, wid, now)
        with self.store.tx():
            self.store.x("INSERT INTO experiments(exp_id,workflow_id,cohort_id,dim,status,control,arms,kpi,state) "
                         "VALUES(?,?,'default',?,'planned',?,?,?,?)", exp_id, wid, dim, json.dumps([control]), json.dumps(arms),
                         kpi, json.dumps({"alpha_spent": 0.0, "stopped": [], "looks": 0}))
            self.gov.enqueue(wid, "experiment_start", 40, [{"op": "set_alloc", "cohort": ch.DEFAULT, "dim": dim, "dist": dist}],
                             {"exp_id": exp_id, "dims": [dim], "cohort": ch.DEFAULT,
                              "summary": f"Test {dim.replace('_', ' ')} options {', '.join(arms)} against {control} on half of calls",
                              "rationale": f"History only contains {control}, so nothing is known about the alternatives. "
                                           f"{control} keeps {cfg.CONTROL_SHARE:.0%} of calls and a clearly worse arm is removed early.",
                              "value_per_day": connected * 0.5 * cfg.MDE_RELATIVE * 0.3 * 0.25, "confidence": 0.25},
                             now, exp_id)
            self.store.audit(now, wid, "experiment_planned", f"{dim}: {arms} vs {control}", {"exp_id": exp_id})

    def _plan_did(self, spec: dict, config: dict, now: int) -> None:
        wid = spec["workflow_id"]
        if self._exists(wid, "caller_id"):
            return
        current = co.effective(config, ch.DEFAULT, "caller_id")
        quarantined = {r["did"] for r in self.store.q("SELECT did FROM did_status WHERE workflow_id=?", wid)}
        arms = [o for o in spec["options"].get("caller_id", []) if o not in current and o not in quarantined]
        if not current or not arms:
            return
        incumbents = sorted(current)
        explore_total = cfg.DID_EXPLORE_SHARE * len(arms)
        dist = {k: v * (1 - explore_total) for k, v in current.items()}
        dist.update({a: cfg.DID_EXPLORE_SHARE for a in arms})
        exp_id = f"{wid}:caller_id:default"
        kind_auto = self.gov.auto_allowed(spec, "caller_id")
        with self.store.tx():
            self.store.x("INSERT INTO experiments(exp_id,workflow_id,cohort_id,dim,status,control,arms,kpi,state) "
                         "VALUES(?,?,'default','caller_id','planned',?,?,'pickup_rate',?)", exp_id, wid, json.dumps(incumbents),
                         json.dumps(arms), json.dumps({"alpha_spent": 0.0, "stopped": [], "looks": 0}))
            self.gov.enqueue(wid, "did_explore", 45, [{"op": "set_did_shares", "dist": dist}],
                             {"exp_id": exp_id, "dims": ["caller_id"], "cohort": ch.DEFAULT,
                              "summary": f"Try unused caller IDs {', '.join(arms)} on {cfg.DID_EXPLORE_SHARE:.0%} of calls each",
                              "rationale": "History only covers the numbers in use, so a healthy spare is unproven. "
                                           "Small shares limit the cost if one is poor.",
                              "value_per_day": 0.0, "confidence": 0.2, "auto": kind_auto}, now, exp_id)
            self.store.audit(now, wid, "experiment_planned", f"caller_id: {arms} vs {incumbents}", {"exp_id": exp_id})

    # --- applied / dropped callbacks ----------------------------------------------------------
    def _started(self, intent: dict, version: int, now: int) -> None:
        evidence = json.loads(intent["evidence"])
        self.store.x("UPDATE experiments SET status='running', start_version=?, start_minute=? WHERE exp_id=? AND status='planned'",
                     version, now, evidence["exp_id"])
        self.store.audit(now, intent["workflow_id"], "experiment_started", evidence["summary"],
                         {"exp_id": evidence["exp_id"], "version": version})

    def _never_ran(self, intent: dict, now: int) -> None:
        """Memo 05: permission never came, so nothing is recorded as if the arms had run."""
        evidence = json.loads(intent["evidence"])
        self.store.x("UPDATE experiments SET status='never_ran', end_minute=? WHERE exp_id=?", now, evidence["exp_id"])
        self.store.audit(now, intent["workflow_id"], "experiment_never_ran", "permission was not granted; no arm data exists",
                         {"exp_id": evidence["exp_id"]})

    def _promoted(self, intent: dict, version: int, now: int) -> None:
        evidence = json.loads(intent["evidence"])
        self.store.x("UPDATE experiments SET status='concluded', end_minute=? WHERE exp_id=?", now, evidence["exp_id"])
        for promo in evidence.get("promotions", []):
            promo_id = f"{evidence['exp_id']}:{promo['cohort']}:{version}"
            self.store.x("INSERT OR IGNORE INTO promotions(promo_id,workflow_id,cohort_id,dim,winner,holdout,kpi,lift_at_promotion,"
                         "version,status,applied_minute) VALUES(?,?,?,?,?,?,?,?,?,'active',?)", promo_id, intent["workflow_id"],
                         promo["cohort"], promo["dim"], promo["winner"], promo["holdout"], promo["kpi"], promo["diff"], version, now)
            self.store.audit(now, intent["workflow_id"], "winner_promoted",
                             f"{promo['dim']}={promo['winner']} live for {promo['cohort']} (holdout {promo['holdout']})",
                             {**promo, "version": version})

    def _rolled_back(self, intent: dict, version: int, now: int) -> None:
        evidence = json.loads(intent["evidence"])
        self.store.x("UPDATE promotions SET status='rolled_back', closed_minute=? WHERE promo_id=?", now, evidence["promo_id"])
        self.store.audit(now, intent["workflow_id"], "rolled_back", evidence["summary"], {**evidence, "version": version})

    # --- daily look ---------------------------------------------------------------------------
    def look_due(self, wid: str, now: int) -> bool:
        spec = self.specs[wid]
        earliest, _ = self.gov.send_window(spec)
        day = now // 1440
        if now % 1440 < earliest or self.store.get_meta(f"look_day:{wid}") == day:
            return False
        return True

    def daily(self, wid: str, config: dict, now: int) -> None:
        with self.store.tx():
            for row in self.store.q("SELECT * FROM experiments WHERE workflow_id=? AND status='running'", wid):
                self._look(dict(row), config, now)
            for row in self.store.q("SELECT * FROM promotions WHERE workflow_id=? AND status='active'", wid):
                self._check_decay(dict(row), now)
            self.store.set_meta(f"look_day:{wid}", now // 1440)

    def _rows(self, wid: str, cohort: str, min_version: int, since_day: int | None = None) -> list:
        sql = ("SELECT day, config_version, prompt, seg, welcome, voice, did, SUM(dials) dials, SUM(connected) connected, "
               "SUM(engaged) engaged FROM fact_arm WHERE workflow_id=? AND cohort_id=? AND config_version>=?")
        args = [wid, cohort, min_version]
        if since_day is not None:
            sql += " AND day>=?"
            args.append(since_day)
        return self.store.q(sql + " GROUP BY day, config_version, prompt, seg, welcome, voice, did", *args)

    @staticmethod
    def _compare(rows, dim: str, arm: str, control: list[str], kpi: str, segs: set[int] | None = None):
        col = DIM_COL[dim]
        num, den = KPI_COLS[kpi]
        strata: dict[tuple, list[int]] = {}
        for r in rows:
            if segs is not None and r["seg"] not in segs:
                continue
            value = r[col]
            if value != arm and value not in control:
                continue
            s = strata.setdefault((r["day"], r["config_version"], r["prompt"]), [0, 0, 0, 0])
            offset = 0 if value == arm else 2
            s[offset] += r[num]
            s[offset + 1] += r[den]
        return stats.compare_stratified([tuple(v) for v in strata.values()])

    def _look(self, exp: dict, config: dict, now: int) -> None:
        wid, dim, kpi = exp["workflow_id"], exp["dim"], exp["kpi"]
        spec = self.specs[wid]
        state, control = json.loads(exp["state"]), json.loads(exp["control"])
        arms = [a for a in json.loads(exp["arms"]) if a not in state["stopped"]]
        rows = self._rows(wid, exp["cohort_id"], exp["start_version"])
        comps = {a: self._compare(rows, dim, a, control, kpi) for a in arms}
        comps = {a: c for a, c in comps.items() if c is not None}
        if not comps:
            return
        any_c = next(iter(comps.values()))
        n_max = stats.sample_size_per_arm(any_c.rate_c, cfg.MDE_RELATIVE, cfg.ALPHA_FAMILY / max(len(arms), 1), cfg.POWER)
        info = min(c.n_t for c in comps.values()) / n_max
        elapsed = (now - exp["start_minute"]) / (self.max_days * 1440)
        horizon_days_left = (self.end_minute - now) / 1440
        final = elapsed >= 1 or info >= 1 or horizon_days_left < 2
        t = 1.0 if final else max(info, elapsed)
        spent_total = stats.obf_alpha_spent(t, cfg.ALPHA_FAMILY)
        nominal = max(spent_total - state["alpha_spent"], 0.0)
        state["alpha_spent"], state["looks"] = max(spent_total, state["alpha_spent"]), state["looks"] + 1
        pvals = {a: c.p_two_sided for a, c in comps.items()}
        rejected = stats.holm_rejections(pvals, nominal)
        winners = sorted((a for a in rejected if comps[a].diff > 0), key=lambda a: -comps[a].diff)
        self.store.audit(now, wid, "experiment_look", f"{dim} look {state['looks']}: {winners or 'no winner yet'}",
                         {"exp_id": exp["exp_id"], "information_fraction": round(t, 3), "nominal_alpha": nominal,
                          "alpha_spent": state["alpha_spent"], "final": final,
                          "arms": {a: _fmt(c) for a, c in comps.items()}})
        self._stop_harmful(exp, comps, state, now)
        self.store.x("UPDATE experiments SET state=? WHERE exp_id=?", json.dumps(state), exp["exp_id"])
        if winners or final:
            self._conclude(exp, spec, config, rows, comps, winners, control, now)

    def _stop_harmful(self, exp: dict, comps: dict, state: dict, now: int) -> None:
        wid = exp["workflow_id"]
        for arm, c in comps.items():
            if c.diff >= 0 or min(c.n_t, c.n_c) < cfg.HARM_MIN_CONNECTED or stats.one_sided_p(-c.z) >= cfg.HARM_ALPHA:
                continue
            state["stopped"].append(arm)
            self.gov.enqueue(wid, "stop_arm", 70, [{"op": "remove_arm", "cohort": exp["cohort_id"], "dim": exp["dim"], "arm": arm}],
                             {"exp_id": exp["exp_id"], "dims": [exp["dim"]],
                              "summary": f"Stop testing {exp['dim']}={arm}: clearly worse than control",
                              "rationale": f"{arm} is {c.lift:+.1%} on {exp['kpi']} vs control (z={c.z:.2f}, one-sided p below {cfg.HARM_ALPHA}).",
                              "value_per_day": abs(c.diff) * c.n_t / max((now - exp["start_minute"]) / 1440, 1),
                              "confidence": 0.9}, now, f"{exp['exp_id']}:{arm}")
            self.store.audit(now, wid, "arm_stopped", f"{exp['dim']}={arm} stopped for harm", {"exp_id": exp["exp_id"], **_fmt(c)})

    def _lift_is_stable(self, rows, dim: str, arm: str, control: list[str], kpi: str, now: int) -> tuple[bool, dict]:
        """An average over the whole test can hide a variant that has already stopped working."""
        cut = now // 1440 - cfg.STABILITY_RECENT_DAYS
        early = self._compare([r for r in rows if r["day"] < cut], dim, arm, control, kpi)
        recent = self._compare([r for r in rows if r["day"] >= cut], dim, arm, control, kpi)
        if early is None or recent is None:
            return True, {"note": "not enough days to compare"}
        se = (early.se ** 2 + recent.se ** 2) ** 0.5
        z = (recent.diff - early.diff) / se if se else 0.0
        trend = {"early": _fmt(early), "recent": _fmt(recent), "z_change": round(z, 3)}
        return not (z < -cfg.STABILITY_Z and recent.diff < 0.5 * early.diff), trend

    def _guardrail_ok(self, spec: dict, rows, dim: str, arm: str, control: list[str], segs=None, exp_kpi=None) -> tuple[bool, dict]:
        kpi, limit = guardrail_of(spec)
        if exp_kpi == kpi:  # testing caller IDs on pickup in a pickup-guarded workflow
            kpi = OTHER_KPI[kpi]
        c = self._compare(rows, dim, arm, control, kpi, segs)
        if c is None:
            return True, {"kpi": kpi, "note": "no data"}
        prob = stats.prob_drop_exceeds(c.diff, c.se, limit)
        return prob <= cfg.GUARDRAIL_BLOCK_PROB, {"kpi": kpi, "limit": limit, "prob_exceeds": round(prob, 4), **_fmt(c)}

    def _conclude(self, exp: dict, spec: dict, config: dict, rows, comps: dict, winners: list[str], control: list[str], now: int) -> None:
        wid, dim = exp["workflow_id"], exp["dim"]
        self.store.x("UPDATE experiments SET status='concluding' WHERE exp_id=?", exp["exp_id"])
        if dim == "caller_id":
            self._conclude_did(exp, spec, config, rows, comps, winners, control, now)
            return
        winner, guard = None, {}
        for arm in winners:
            stable, trend = self._lift_is_stable(rows, dim, arm, control, exp["kpi"], now)
            if not stable:
                self.store.audit(now, wid, "winner_unstable", f"{dim}={arm} won overall but its lift collapsed inside the test",
                                 {"exp_id": exp["exp_id"], "trend": trend})
                continue
            ok, guard = self._guardrail_ok(spec, rows, dim, arm, control)
            if ok:
                winner = arm
                break
            self.store.audit(now, wid, "guardrail_block", f"{dim}={arm} beat control on the primary KPI but failed the guardrail",
                             {"exp_id": exp["exp_id"], "guardrail": guard})
        base_control = control[0]
        ops, promotions, notes = [], [], []
        if winner:
            c = comps[winner]
            dist = {winner: 1 - cfg.HOLDOUT_SHARE, base_control: cfg.HOLDOUT_SHARE}
            promotions.append({"cohort": ch.DEFAULT, "dim": dim, "winner": winner, "holdout": base_control, "kpi": exp["kpi"],
                               "diff": c.diff, **_fmt(c)})
            notes.append(f"{winner} beat {base_control}: {c.rate_t:.1%} vs {c.rate_c:.1%} (lift {c.lift:+.1%}, z={c.z:.2f})")
        else:
            dist = {base_control: 1.0}
            notes.append(f"no option proved better than {base_control}")
        ops.append({"op": "set_alloc", "cohort": ch.DEFAULT, "dim": dim, "dist": dist})
        slice_ops, slice_promos, slice_notes = self._scan_slices(exp, spec, rows, winner, base_control, now)
        ops += slice_ops
        promotions += slice_promos
        notes += slice_notes
        volume = daily_connected(self.store, wid, now)
        best_lift = max([comps[winner].diff] if winner else [0.0])
        summary = f"{dim.replace('_', ' ')}: " + "; ".join(notes)
        self.gov.enqueue(wid, "promote", 60, ops,
                         {"exp_id": exp["exp_id"], "dims": [dim], "summary": summary[:300], "promotions": promotions,
                          "rationale": f"Daily-look group-sequential test, Holm across arms, family alpha {cfg.ALPHA_FAMILY}. "
                                       + " ".join(notes) + f" Guardrail: {guard or 'not applicable'}.",
                          "value_per_day": volume * best_lift * (1 - cfg.HOLDOUT_SHARE), "confidence": 0.9 if winner else 0.3},
                         now, exp["exp_id"])
        self.store.audit(now, wid, "experiment_concluded", summary, {"exp_id": exp["exp_id"], "promotions": promotions})

    def _scan_slices(self, exp: dict, spec: dict, rows, global_winner: str | None, control: str, now: int):
        """Finds people for whom the population answer is wrong, including people it would hurt."""
        wid, dim, kpi = exp["workflow_id"], exp["dim"], exp["kpi"]
        arms = [a for a in json.loads(exp["arms"]) if a not in json.loads(exp["state"])["stopped"]]
        shares = self._segment_shares(wid)
        tests: dict[tuple[str, str], float] = {}
        comps: dict[tuple[str, str], stats.Comparison] = {}
        by_id: dict[str, tuple[ch.Cohort, set[int]]] = {}
        for cohort in ch.candidate_slices(self.segments):
            segs = {s for s, f in self.segments.items() if cohort.matches(f)}
            if sum(shares.get(s, 0.0) for s in segs) < cfg.MIN_SLICE_LEAD_SHARE:
                continue
            by_id[cohort.id] = (cohort, segs)
            for arm in arms:
                c = self._compare(rows, dim, arm, [control], kpi, segs)
                if c is None or min(c.n_t, c.n_c) < cfg.MIN_SLICE_CONNECTED:
                    continue
                tests[(cohort.id, arm)] = c.p_two_sided
                comps[(cohort.id, arm)] = c
        if not tests:
            return [], [], []
        rejected = stats.bh_rejections(tests, cfg.SLICE_FDR_Q)
        self.store.audit(now, wid, "slice_scan", f"{dim}: {len(rejected)} of {len(tests)} slice hypotheses survived FDR",
                         {"exp_id": exp["exp_id"], "tests": len(tests), "survivors": [list(k) for k in sorted(rejected)]})
        best_for: dict[str, tuple[str, stats.Comparison]] = {}
        for (cid, arm) in rejected:
            c = comps[(cid, arm)]
            if c.diff > 0 and (cid not in best_for or c.diff > best_for[cid][1].diff):
                best_for[cid] = (arm, c)
        harmed = {cid for (cid, arm) in rejected if arm == global_winner and comps[(cid, arm)].diff < 0}
        candidates = []
        for cid, (arm, c) in best_for.items():
            if arm != global_winner:
                candidates.append((cid, arm, c))
        for cid in harmed - set(best_for):
            candidates.append((cid, control, comps[(cid, global_winner)]))
        candidates.sort(key=lambda t: (-abs(t[2].z), t[0]))
        ops, promos, notes, taken_segs, count = [], [], [], set(), 0
        for cid, arm, c in candidates:
            if count >= cfg.MAX_NEW_COHORTS:
                break
            cohort, segs = by_id[cid]
            if segs & taken_segs:
                continue
            if arm != control:
                ok, guard = self._guardrail_ok(spec, rows, dim, arm, [control], segs)
                if not ok:
                    self.store.audit(now, wid, "guardrail_block", f"{dim}={arm} for {cid} failed the guardrail", {"guardrail": guard})
                    continue
            taken_segs |= segs
            count += 1
            self.store.x("INSERT OR IGNORE INTO cohorts VALUES(?,?,?,'controller',?)", wid, cohort.id, json.dumps(cohort.where_dict()), now)
            dist = {control: 1.0} if arm == control else {arm: 1 - cfg.HOLDOUT_SHARE, control: cfg.HOLDOUT_SHARE}
            ops += [{"op": "add_cohort", "id": cohort.id, "where": cohort.where_dict()},
                    {"op": "set_alloc", "cohort": cohort.id, "dim": dim, "dist": dist}]
            if arm != control:
                promos.append({"cohort": cohort.id, "dim": dim, "winner": arm, "holdout": control, "kpi": kpi, "diff": c.diff, **_fmt(c)})
                notes.append(f"{cohort.describe()} prefers {arm} ({c.lift:+.1%})")
            else:
                notes.append(f"{cohort.describe()} stays on {control}: {global_winner} hurts this group ({c.lift:+.1%})")
        return ops, promos, notes

    def _segment_shares(self, wid: str) -> dict[int, float]:
        rows = self.store.q("SELECT cs.seg, SUM(cs.leads) n FROM campaign_seg cs JOIN campaigns c ON c.campaign_id=cs.campaign_id "
                            "WHERE c.workflow_id=? GROUP BY cs.seg", wid)
        total = sum(r["n"] for r in rows) or 1
        return {r["seg"]: r["n"] / total for r in rows}

    def _conclude_did(self, exp: dict, spec: dict, config: dict, rows, comps: dict, winners: list[str], control: list[str], now: int) -> None:
        wid = exp["workflow_id"]
        current = co.effective(config, ch.DEFAULT, "caller_id")
        keep = {k: v for k, v in current.items() if k in control}
        passed = [w for w in winners if self._guardrail_ok(spec, rows, "caller_id", w, control, exp_kpi="pickup_rate")[0]]
        share = 1.0 / (len(keep) + len(passed)) if keep or passed else 0
        dist = {k: share for k in list(keep) + passed}
        if not dist:
            return
        names = ", ".join(passed) if passed else "none"
        self.gov.enqueue(wid, "did_promote", 55, [{"op": "set_did_shares", "dist": dist}],
                         {"exp_id": exp["exp_id"], "dims": ["caller_id"], "promotions": [],
                          "summary": f"End caller-ID trial. Numbers that beat the incumbents: {names}",
                          "rationale": "Arms compared with pooled incumbents on pickup, Holm across arms. "
                                       "Trial numbers without evidence are removed rather than left running.",
                          "value_per_day": 0.0, "confidence": 0.5}, now, exp["exp_id"] + ":end")
        self.store.audit(now, wid, "experiment_concluded", f"caller_id: winners {passed}",
                         {"exp_id": exp["exp_id"], "arms": {a: _fmt(c) for a, c in comps.items()}})

    def _check_decay(self, promo: dict, now: int) -> None:
        wid = promo["workflow_id"]
        day = now // 1440
        rows = self._rows(wid, promo["cohort_id"], promo["version"], day - cfg.DECAY_WINDOW_DAYS)
        c = self._compare(rows, promo["dim"], promo["winner"], [promo["holdout"]], promo["kpi"])
        if c is None or c.n_c < cfg.DECAY_MIN_HOLDOUT_CONNECTED or c.se == 0:
            return
        lift_then = promo["lift_at_promotion"]
        diff, se, source = self._best_lift_estimate(promo, c, day)
        z_vs_control = diff / se
        z_decay = (diff - lift_then * cfg.DECAY_LIFT_FRACTION) / se
        worse = z_vs_control < -cfg.DECAY_Z
        faded = z_decay < -cfg.DECAY_Z and diff < lift_then * 0.25
        self.store.audit(now, wid, "decay_check", f"{promo['dim']}={promo['winner']}: lift now {diff:+.3f}, at promotion {lift_then:+.3f}",
                         {"promo_id": promo["promo_id"], "control_source": source, "z_vs_control": round(z_vs_control, 2),
                          "z_decay": round(z_decay, 2), "worse": worse, "faded": faded, "concurrent": _fmt(c)})
        if not (worse or faded):
            return
        why = "now worse than the holdout" if worse else "lost most of its lift"
        summary = f"Roll back {promo['dim']}={promo['winner']} for {promo['cohort_id']}: {why}"
        key = promo["promo_id"]
        self.gov.enqueue(wid, "rollback", 80, [{"op": "set_alloc", "cohort": promo["cohort_id"], "dim": promo["dim"],
                                                "dist": {promo["holdout"]: 1.0}}],
                         {"promo_id": promo["promo_id"], "dims": [promo["dim"]], "summary": summary,
                          "rationale": f"Over {cfg.DECAY_WINDOW_DAYS} days ({source}) lift is {diff:+.3f} against {lift_then:+.3f} "
                                       f"at promotion (z vs control {z_vs_control:.2f}, z vs half of old lift {z_decay:.2f}).",
                          "value_per_day": abs(c.diff) * c.n_t / cfg.DECAY_WINDOW_DAYS, "confidence": 0.9}, now, key)
        self.store.x("UPDATE promotions SET status='rollback_requested' WHERE promo_id=?", promo["promo_id"])
        self.store.audit(now, wid, "decay_detected", summary, {"promo_id": promo["promo_id"], **_fmt(c)})

    def _best_lift_estimate(self, promo: dict, c: stats.Comparison, day: int) -> tuple[float, float, str]:
        """Pools control's long-run rate into the estimate, but only if the holdout agrees with it."""
        col = DIM_COL[promo["dim"]]
        num, den = KPI_COLS[promo["kpi"]]
        if promo["cohort_id"] != ch.DEFAULT:
            return c.diff, c.se, "concurrent holdout"  # a new cohort has no long-run history of its own
        r = self.store.one(f"SELECT SUM({num}) x, SUM({den}) n FROM fact_arm WHERE workflow_id=? AND {col}=? AND day>=? AND day<?",
                           promo["workflow_id"], promo["holdout"], day - cfg.DECAY_POOL_DAYS, day)
        if not r["n"]:
            return c.diff, c.se, "concurrent holdout"
        p_pool = r["x"] / r["n"]
        var_pool = p_pool * (1 - p_pool) / r["n"]
        var_holdout = c.rate_c * (1 - c.rate_c) / c.n_c
        if var_pool + var_holdout == 0 or abs(c.rate_c - p_pool) / (var_pool + var_holdout) ** 0.5 > cfg.DECAY_POOL_AGREEMENT_Z:
            return c.diff, c.se, "concurrent holdout (long-run control disagreed)"
        var_winner = c.rate_t * (1 - c.rate_t) / c.n_t
        se = (var_winner + var_pool) ** 0.5
        return c.rate_t - p_pool, se, f"holdout agrees with {cfg.DECAY_POOL_DAYS}-day pooled control"

    # --- supervisor edits ---------------------------------------------------------------------
    def on_supervisor_edit(self, wid: str, version: int, dims: list[str], now: int) -> None:
        """A supervisor's edit stands. Experiments it touches stop; others continue, stratified."""
        for exp in self.store.q(f"SELECT * FROM experiments WHERE workflow_id=? AND status IN {RUNNING}", wid):
            if exp["dim"] in dims or "cohorts" in dims:
                exp_id = exp["exp_id"]
                self.store.x("UPDATE experiments SET status='invalidated', end_minute=? WHERE exp_id=?", now, exp_id)
                self.gov.cancel_intents(wid, lambda e: e.get("exp_id") == exp_id, now, f"supervisor changed {dims} in v{version}")
                self.store.audit(now, wid, "experiment_invalidated", f"{exp['dim']} test ended: supervisor edit v{version}",
                                 {"exp_id": exp_id, "dims": dims})
            else:
                self.store.audit(now, wid, "experiment_continues", f"{exp['dim']} test continues: strata isolate supervisor edit v{version}",
                                 {"exp_id": exp["exp_id"], "dims": dims})
        for promo in self.store.q("SELECT * FROM promotions WHERE workflow_id=? AND status='active'", wid):
            if promo["dim"] in dims or "cohorts" in dims:
                self.store.x("UPDATE promotions SET status='superseded', closed_minute=? WHERE promo_id=?", now, promo["promo_id"])
                self.store.audit(now, wid, "promotion_superseded", f"{promo['dim']} no longer ours to monitor after supervisor edit v{version}",
                                 {"promo_id": promo["promo_id"]})


def _fmt(c: stats.Comparison) -> dict:
    return {"rate_t": round(c.rate_t, 4), "rate_c": round(c.rate_c, 4), "n_t": c.n_t, "n_c": c.n_c, "diff": round(c.diff, 4),
            "z": round(c.z, 3), "p": round(c.p_two_sided, 6), "lift": round(c.lift, 4)}
