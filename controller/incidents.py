"""Population-level detectors, and the hallucination fix workflow.

An incident's phase lives in its row, so a restart continues from the same step:

    selecting -> proposed -> verifying -> resolved
        ^            |            |
        +------------+------------+   (rejected, dropped, or the fix failed verification)
"""
from __future__ import annotations

import json
import logging

from . import cohorts as ch
from . import config as cfg
from . import configops as co
from . import stats
from .client import SimError
from .evidence import daily_connected
from .store import Store

log = logging.getLogger("controller.incidents")


class Incidents:
    def __init__(self, store: Store, client, governance, specs: dict[str, dict]):
        self.store, self.client, self.gov, self.specs = store, client, governance, specs
        governance.on_applied["incident_fix"] = self._fix_applied
        governance.on_dropped["incident_fix"] = self._fix_dropped
        self.baseline: dict[str, float] = {}

    def compute_baselines(self) -> None:
        """Per-workflow flag rate from pre-D0 history. The detector is imperfect, so the baseline
        is the detector's own rate rather than an assumed true rate."""
        for wid in self.specs:
            r = self.store.one("SELECT SUM(qa) q, SUM(halluc) h FROM fact_hour WHERE workflow_id=? AND hour_idx<0", wid)
            self.baseline[wid] = r["h"] / r["q"] if r["q"] else cfg.HALLUC_DEFAULT_BASELINE

    # --- hallucination ------------------------------------------------------------------------
    def step(self, wid: str, config: dict, now: int) -> None:
        open_row = self.store.one("SELECT * FROM incidents WHERE workflow_id=? AND kind='hallucination' AND status='open'", wid)
        if open_row:
            self._progress(dict(open_row), config, now)
        else:
            self._detect_hallucination(wid, config, now)
        self._detect_did(wid, config, now)
        if now % 60 == 0:
            self._detect_drift(wid, now)

    def _window(self, wid: str, prompt: str, since_hour: int):
        return self.store.one("SELECT COALESCE(SUM(qa),0) q, COALESCE(SUM(halluc),0) h, COALESCE(SUM(connected),0) c, "
                              "COALESCE(SUM(engaged),0) e FROM fact_hour WHERE workflow_id=? AND prompt=? AND hour_idx>=?",
                              wid, prompt, since_hour)

    def _detect_hallucination(self, wid: str, config: dict, now: int) -> None:
        prompt = config["prompt_version"]
        r = self._window(wid, prompt, now // 60 - cfg.HALLUC_WINDOW_HOURS)
        if r["q"] < cfg.HALLUC_MIN_QA:
            return
        base = self.baseline[wid]
        rate = r["h"] / r["q"]
        if rate < base * cfg.HALLUC_MIN_RATIO or rate - base < cfg.HALLUC_MIN_ABS_DELTA:
            return
        p_value = stats.binomial_tail(r["h"], r["q"], base)
        if p_value >= cfg.HALLUC_P:
            return
        incident_id = f"{wid}:hallucination:{now}"
        detail = {"phase": "selecting", "prompt": prompt, "baseline": round(base, 5), "rate": round(rate, 5), "qa_calls": r["q"], "p_value": p_value,
                  "failed": [prompt], "credits_spent": 0, "llm_asked": False}
        with self.store.tx():
            self.store.x("INSERT INTO incidents VALUES(?,?, 'hallucination','open',?,?,NULL,?)", incident_id, wid, prompt, now, json.dumps(detail))
            self.store.audit(now, wid, "incident_opened", f"Hallucination flags on {prompt}: {rate:.1%} vs baseline {base:.1%} over {r['q']} calls",
                             {"incident_id": incident_id, **detail})
        self._progress({"incident_id": incident_id, "workflow_id": wid, "detail": json.dumps(detail), "subject": prompt, "opened_minute": now}, config, now)

    def _save(self, incident: dict, detail: dict) -> None:
        self.store.x("UPDATE incidents SET detail=? WHERE incident_id=?", json.dumps(detail), incident["incident_id"])

    def _close(self, incident: dict, detail: dict, status: str, now: int, summary: str) -> None:
        with self.store.tx():
            self.store.x("UPDATE incidents SET status=?, closed_minute=?, detail=? WHERE incident_id=?", status, now, json.dumps(detail), incident["incident_id"])
            self.store.audit(now, incident["workflow_id"], f"incident_{status}", summary, {"incident_id": incident["incident_id"], **detail})

    def _progress(self, incident: dict, config: dict, now: int) -> None:
        detail = json.loads(incident["detail"])
        wid = incident["workflow_id"]
        if detail["phase"] != "verifying" and config["prompt_version"] != detail["prompt"]:
            self.gov.cancel_intents(wid, lambda e: e.get("incident_id") == incident["incident_id"], now, "prompt already changed by someone else")
            self._close(incident, detail, "superseded", now, f"Prompt moved off {detail['prompt']} without us; nothing further to do")
            return
        if detail["phase"] == "selecting":
            self._select_fix(incident, detail, now)
        elif detail["phase"] == "verifying":
            self._verify(incident, detail, now)

    def _can_act_now(self, wid: str, now: int) -> bool:
        spec = self.specs[wid]
        return self.gov.can_send(spec, now, urgent=True) or self.gov.auto_allowed(spec, "prompt_version")

    def _known_good(self, wid: str, detail: dict) -> list[str]:
        """Prompts with real traffic here and a clean record. This is the free option: no LLM,
        and engagement on these prompts has been observed rather than guessed."""
        base = self.baseline[wid]
        options = set(self.specs[wid]["options"]["prompt_version"])
        rows = self.store.q("SELECT prompt, SUM(qa) q, SUM(halluc) h, MAX(hour_idx) last_seen FROM fact_hour WHERE workflow_id=? GROUP BY prompt ORDER BY last_seen DESC", wid)
        return [r["prompt"] for r in rows if r["prompt"] in options and r["prompt"] not in detail["failed"] and r["q"] >= cfg.KNOWN_GOOD_MIN_QA
                and r["h"] / r["q"] <= max(base * 1.5, base + 0.005)]

    def _spend_ok(self, detail: dict, cost: float) -> bool:
        return detail["credits_spent"] + cost <= cfg.MAX_CREDITS_PER_INCIDENT

    def _validate(self, incident: dict, detail: dict, prompt: str, n: int, now: int) -> dict | None:
        wid = incident["workflow_id"]
        cost = (n + 99) // 100
        if not self._spend_ok(detail, cost):
            return None
        try:
            result = self.client.validate(wid, prompt, n)
        except SimError as e:
            self.store.audit(now, wid, "validation_failed", str(e), {"incident_id": incident["incident_id"], "prompt": prompt})
            return None
        detail["credits_spent"] += cost
        with self.store.tx():
            self.store.x("INSERT INTO credit_ledger(minute,workflow_id,purpose,cost,ref) VALUES(?,?,?,?,?)", now, wid, "validation", cost, result["validation_run_id"])
            self._save(incident, detail)
            self.store.audit(now, wid, "validation_run", f"{prompt}: pass rate {result['pass_rate']:.3f} on {n}", {"incident_id": incident["incident_id"], **result})
        return result

    def _select_fix(self, incident: dict, detail: dict, now: int) -> None:
        wid = incident["workflow_id"]
        if not self._can_act_now(wid, now):
            return  # validate just before sending so the evidence is fresh when the approver reads it
        spec = self.specs[wid]
        min_pass = spec["governance"]["min_validation_pass_rate"]
        for prompt in self._known_good(wid, detail):
            result = self._validate(incident, detail, prompt, cfg.VALIDATION_N, now)
            if result is None:
                break
            if result["pass_rate"] >= min_pass:
                self._queue_fix(incident, detail, prompt, result, "known_good", now)
                return
            detail["failed"].append(prompt)
            self._save(incident, detail)
        if detail["llm_asked"]:
            self._stuck(incident, detail, now, "no candidate prompt passed validation")
            return
        if not self._spend_ok(detail, 3 + (cfg.VALIDATION_N_LLM + 99) // 100):
            self._stuck(incident, detail, now, "incident credit budget exhausted")
            return
        try:
            resp = self.client.suggest_fixes(wid, f"Hallucination flag rate on {detail['prompt']} is {detail['rate']:.1%} against a baseline of {detail['baseline']:.1%}.")
        except SimError as e:
            self._stuck(incident, detail, now, f"LLM unavailable: {e}")
            return
        detail["llm_asked"], detail["credits_spent"] = True, detail["credits_spent"] + 3
        suggestions = [s for s in resp["suggestions"] if s["prompt_version"] not in detail["failed"]]
        with self.store.tx():
            self.store.x("INSERT INTO credit_ledger(minute,workflow_id,purpose,cost,ref) VALUES(?,?,?,?,?)", now, wid, "llm_suggest", 3, incident["incident_id"])
            self._save(incident, detail)
            self.store.audit(now, wid, "llm_suggested", f"{len(suggestions)} candidate prompts", {"incident_id": incident["incident_id"], "suggestions": suggestions})
        best, best_result = None, None
        for s in suggestions:
            result = self._validate(incident, detail, s["prompt_version"], cfg.VALIDATION_N_LLM, now)
            if result is None:
                break
            if result["pass_rate"] >= min_pass and (best_result is None or result["pass_rate"] > best_result["pass_rate"]):
                best, best_result = s["prompt_version"], result
        if best is None:
            self._stuck(incident, detail, now, "no LLM suggestion passed validation")
            return
        # The LLM only nominated candidates. Validation chose among them, and live verification
        # checks engagement, which validation cannot see.
        self._queue_fix(incident, detail, best, best_result, "llm_candidate", now)

    def _stuck(self, incident: dict, detail: dict, now: int, reason: str) -> None:
        detail["phase"] = "stuck"
        detail["stuck_reason"] = reason
        with self.store.tx():
            self._save(incident, detail)
            self.store.audit(now, incident["workflow_id"], "incident_stuck", reason, {"incident_id": incident["incident_id"]})

    def _queue_fix(self, incident: dict, detail: dict, prompt: str, result: dict, source: str, now: int) -> None:
        wid = incident["workflow_id"]
        detail.update({"phase": "proposed", "candidate": prompt, "candidate_source": source, "validation_run_id": result["validation_run_id"], "validation_pass_rate": result["pass_rate"]})
        was_supervisor = self.store.one("SELECT actor FROM config_versions WHERE workflow_id=? ORDER BY version DESC LIMIT 1", wid)
        origin = " This reverses a supervisor's prompt edit, so please check with them." if was_supervisor and was_supervisor["actor"] == "supervisor" else ""
        excess = max(detail["rate"] - detail["baseline"], 0)
        with self.store.tx():
            self.gov.enqueue(wid, "incident_fix", 100, [{"op": "set_prompt", "prompt": prompt}],
                             {"incident_id": incident["incident_id"], "dims": ["prompt_version"], "validation_run_id": result["validation_run_id"],
                              "summary": f"Move prompt from {detail['prompt']} to {prompt}: hallucination flags at {detail['rate']:.1%}, normal is {detail['baseline']:.1%}",
                              "rationale": f"{detail['qa_calls']} recent calls flagged at {detail['rate']:.1%} (exact binomial p={detail.get('p_value', 0):.1e}). {prompt} ({source}) passed validation at "
                                           f"{result['pass_rate']:.3f} on {result['n']} conversations. Validation measures safety only, so engagement is verified live after applying." + origin,
                              "value_per_day": daily_connected(self.store, wid, now) * excess * 5, "confidence": 0.9},
                             now, f"{incident['incident_id']}:{len(detail['failed'])}")
            self._save(incident, detail)
            self.store.audit(now, wid, "fix_selected", f"{prompt} via {source}", {"incident_id": incident["incident_id"], **detail})

    def _fix_applied(self, intent: dict, version: int, now: int) -> None:
        evidence = json.loads(intent["evidence"])
        row = self.store.one("SELECT * FROM incidents WHERE incident_id=?", evidence["incident_id"])
        if not row or row["status"] != "open":
            return
        detail = json.loads(row["detail"])
        wid = row["workflow_id"]
        pre = self.store.one("SELECT SUM(connected) c, SUM(engaged) e FROM fact_hour WHERE workflow_id=? AND hour_idx<? AND prompt NOT IN (" + ",".join("?" * len(detail["failed"])) + ")",
                             wid, row["opened_minute"] // 60, *detail["failed"])
        detail.update({"phase": "verifying", "applied_minute": now, "fix_hour": now // 60 + 1, "version": version,
                       "pre_engagement": (pre["e"] / pre["c"]) if pre["c"] else None})
        self.store.x("UPDATE incidents SET detail=? WHERE incident_id=?", json.dumps(detail), row["incident_id"])

    def _fix_dropped(self, intent: dict, now: int) -> None:
        evidence = json.loads(intent["evidence"])
        row = self.store.one("SELECT * FROM incidents WHERE incident_id=?", evidence["incident_id"])
        if not row or row["status"] != "open":
            return
        detail = json.loads(row["detail"])
        detail["phase"] = "stuck"
        detail["stuck_reason"] = "fix was not approved after repeated attempts"
        self.store.x("UPDATE incidents SET detail=? WHERE incident_id=?", json.dumps(detail), row["incident_id"])

    def _verify(self, incident: dict, detail: dict, now: int) -> None:
        wid = incident["workflow_id"]
        r = self._window(wid, detail["candidate"], detail["fix_hour"])
        if r["q"] < cfg.FIX_VERIFY_MIN_QA:
            return
        base = detail["baseline"]
        rate = r["h"] / r["q"]
        engagement = r["e"] / r["c"] if r["c"] else 0.0
        pre = detail.get("pre_engagement")
        safe = rate <= max(base * cfg.HALLUC_MIN_RATIO, base + cfg.HALLUC_MIN_ABS_DELTA)
        kept = pre is None or engagement >= pre * (1 - cfg.FIX_MAX_ENGAGEMENT_DROP)
        detail["verification"] = {"rate": round(rate, 5), "engagement": round(engagement, 4), "pre_engagement": pre, "safe": safe, "kept_engagement": kept, "qa": r["q"]}
        if safe and kept:
            self._close(incident, detail, "resolved", now, f"Fix {detail['candidate']} verified: flags {rate:.1%}, engagement {engagement:.1%}")
            return
        why = "still hallucinating" if not safe else "engagement collapsed"
        detail["failed"].append(detail["candidate"])
        detail.update({"phase": "selecting", "prompt": detail["candidate"], "rate": round(rate, 5)})
        with self.store.tx():
            self._save(incident, detail)
            self.store.audit(now, wid, "fix_failed_verification", f"{detail['candidate']} {why}", {"incident_id": incident["incident_id"], **detail["verification"]})

    # --- caller ID ----------------------------------------------------------------------------
    def _detect_did(self, wid: str, config: dict, now: int) -> None:
        hour = now // 60
        rows = self.store.q("SELECT did, SUM(dials) d, SUM(connected) c FROM fact_hour WHERE workflow_id=? AND hour_idx>=? GROUP BY did", wid, hour - cfg.DID_WINDOW_HOURS)
        quarantined = {r["did"] for r in self.store.q("SELECT did FROM did_status WHERE workflow_id=?", wid)}
        current = co.effective(config, ch.DEFAULT, "caller_id")
        live = [r for r in rows if r["did"] in current and r["did"] not in quarantined]
        total_d = sum(r["d"] for r in live)
        total_c = sum(r["c"] for r in live)
        for r in live:
            if r["d"] < cfg.DID_MIN_DIALS:
                continue
            peers_d, peers_c = total_d - r["d"], total_c - r["c"]
            if peers_d >= cfg.DID_MIN_DIALS:
                reference, method = peers_c / peers_d, "concurrent peer numbers"
                comp = stats.compare_stratified([(r["c"], r["d"], peers_c, peers_d)])
                z = -comp.z if comp else 0.0
            else:
                reference, z = self._did_vs_own_history(wid, r, hour)
                method = "this number's history at the same hours"
            if reference <= 0:
                continue
            ratio = (r["c"] / r["d"]) / reference
            if z >= cfg.DID_Z and ratio <= cfg.DID_MAX_PICKUP_RATIO:
                self._quarantine(wid, r, ratio, z, method, config, now)

    def _did_vs_own_history(self, wid: str, row, hour: int) -> tuple[float, float]:
        """For a workflow's only number. Compares against the same hours of day, because time
        of day alone moves pickup enough to look like an incident."""
        recent = self.store.q("SELECT hour_idx, SUM(dials) d FROM fact_hour WHERE workflow_id=? AND did=? AND hour_idx>=? GROUP BY hour_idx", wid, row["did"], hour - cfg.DID_WINDOW_HOURS)
        expected = variance = 0.0
        for rec in recent:
            hod = rec["hour_idx"] % 24
            base = self.store.one("SELECT SUM(dials) d, SUM(connected) c FROM fact_hour WHERE workflow_id=? AND did=? AND hour_idx<? AND ((hour_idx % 24 + 24) % 24)=?", wid, row["did"], hour - cfg.DID_WINDOW_HOURS, hod)
            if base["d"]:
                p = base["c"] / base["d"]
                expected += rec["d"] * p
                variance += rec["d"] * p * (1 - p)
        if expected == 0:
            return 0.0, 0.0
        return expected / row["d"], -stats.poisson_binomial_z(row["c"], expected, variance)

    def _quarantine(self, wid: str, row, ratio: float, z: float, method: str, config: dict, now: int) -> None:
        did = row["did"]
        spec = self.specs[wid]
        known = {r["did"] for r in self.store.q("SELECT did FROM did_status WHERE workflow_id=?", wid)} | {did}
        replacements = [o for o in spec["options"]["caller_id"] if o not in known]
        evidence = {"dims": ["caller_id"], "summary": f"Move calls off caller ID {did}: pickup is {ratio:.0%} of normal",
                    "rationale": f"{row['c']}/{row['d']} connected in {cfg.DID_WINDOW_HOURS}h, compared with {method} (z={z:.1f}). Population-level, not single calls.",
                    "value_per_day": 0.0, "confidence": 0.9}
        with self.store.tx():
            self.store.x("INSERT OR IGNORE INTO did_status VALUES(?,?, 'quarantined', ?)", wid, did, now)
            self.gov.enqueue(wid, "did_quarantine", 90, [{"op": "quarantine_did", "did": did, "replacements": replacements}], evidence, now, did)
            self.store.audit(now, wid, "did_degraded", evidence["summary"], {"did": did, "ratio": round(ratio, 3), "z": round(z, 2), "method": method, "dials": row["d"]})

    # --- drift (visibility only: drift names a symptom, a detector above names the cause) -----
    def _detect_drift(self, wid: str, now: int) -> None:
        hour = now // 60
        window_start = hour - 6
        recent = self.store.one("SELECT SUM(dials) d, SUM(connected) c, SUM(engaged) e FROM fact_hour WHERE workflow_id=? AND hour_idx>=?", wid, window_start)
        if (recent["d"] or 0) < cfg.DRIFT_MIN_DIALS:
            return
        base = self.store.q("SELECT ((hour_idx % 24 + 24) % 24) hod, SUM(dials) d, SUM(connected) c, SUM(engaged) e FROM fact_hour WHERE workflow_id=? AND hour_idx<? AND hour_idx>=? GROUP BY hod", wid, window_start, window_start - 24 * 7)
        by_hod = {r["hod"]: r for r in base}
        hours = self.store.q("SELECT hour_idx, SUM(dials) d, SUM(connected) c FROM fact_hour WHERE workflow_id=? AND hour_idx>=? GROUP BY hour_idx", wid, window_start)
        for kpi, num, den in (("pickup_rate", "c", "d"), ("engagement_rate", "e", "c")):
            expected = variance = 0.0
            for h in hours:
                b = by_hod.get(h["hour_idx"] % 24)
                if not b or not b[den]:
                    continue
                p = b[num] / b[den]
                n = h["d"] if den == "d" else h["c"]
                expected += n * p
                variance += n * p * (1 - p)
            if expected <= 0:
                continue
            z = stats.poisson_binomial_z(recent[num], expected, variance)
            relative = recent[num] / expected - 1
            key = f"drift:{wid}:{kpi}"
            if abs(z) >= cfg.DRIFT_Z and abs(relative) >= cfg.DRIFT_MIN_RELATIVE:
                self.store.x("INSERT INTO alerts VALUES(?,'ticket',?,?,?,0) ON CONFLICT(alert_key) DO UPDATE SET message=excluded.message,last_minute=excluded.last_minute,closed=0",
                             key, f"{wid} {kpi} is {relative:+.0%} against the same hours last week", now, now)
                if self.store.get_meta(f"drift_day:{key}") != now // 1440:
                    self.store.set_meta(f"drift_day:{key}", now // 1440)
                    self.store.audit(now, wid, "drift", f"{kpi} {relative:+.1%} vs the same hours last week", {"z": round(z, 2), "kpi": kpi})
            else:
                self.store.x("UPDATE alerts SET closed=1 WHERE alert_key=?", key)
