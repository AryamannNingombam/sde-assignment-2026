"""Hallucination incident response (C8): detect -> choose fix -> validate -> propose with evidence -> verify.

Detection is population-based. The automated detector is imperfect (about 80% recall, about 1% false positives per
the contract), so we never act on single flags: we need >=120 connected calls on the *current* prompt and a one-sided
binomial z >= 3.6 against the baseline flag rate measured in history, confirmed twice >=30 minutes apart.
Expected false positives: P(z>=3.6)=1.6e-4 per check, and the elevation must persist >=30 min, i.e. roughly 0.1-0.3% per workflow-day; a false incident only costs 3 credits and one reversible, validated proposal.

Fix selection spends as few credits as possible (CTO memo): first choice is the last prompt that ran cleanly in our
own data (no LLM needed); the LLM is asked only when no such prompt exists. The LLM never decides: a validation run
(pass_rate vs the workflow's threshold) does, and 'verbatim compliance script' candidates are ranked last because the
Kestrel supervisor warned that they kill engagement.
"""
from __future__ import annotations

import copy
import json

from .common import fmt_minute
from .simclient import ApiError
from .stats import binom_z

MIN_CALLS, Z_DETECT = 120, 3.6
VAL_N = 300


class Incidents:
    def __init__(self, store, sim, learn, gov):
        self.s, self.sim, self.learn, self.gov = store, sim, learn, gov

    # ---------------------------------------------------------------- baseline from history
    def baseline(self, wf: str):
        r = self.s.q1("SELECT COALESCE(SUM(conn),0), COALESCE(SUM(flags),0) FROM agg_prm WHERE wf=? AND hidx<0", (wf,))
        n, k = r
        return (k / n if n >= 500 else 0.015), n

    def open_incident(self, wf):
        r = self.s.q1("SELECT id, state, js FROM incident WHERE wf=? AND kind='hallucination' AND state NOT IN "
                      "('verified','failed','closed') ORDER BY id DESC LIMIT 1", (wf,))
        return (r[0], r[1], json.loads(r[2])) if r else None

    def _save(self, iid, state, js, now=None):
        if state in ("verified", "failed", "closed"):
            self.s.x("UPDATE incident SET state=?, js=?, closed_min=? WHERE id=?", (state, json.dumps(js), now, iid))
        else:
            self.s.x("UPDATE incident SET state=?, js=? WHERE id=?", (state, json.dumps(js), iid))

    # ---------------------------------------------------------------- main entry, called every tick per workflow
    def tick(self, spec, now, live_cfg, version, credits, outstanding):
        wf = spec["workflow_id"]
        inc = self.open_incident(wf)
        if inc is None:
            self._detect(spec, now, live_cfg)
            inc = self.open_incident(wf)
            if inc is None:
                return
        iid, state, js = inc
        if state == "detected":
            self._choose_fix(spec, now, iid, js, live_cfg, credits)
            inc = self.open_incident(wf)
            if inc is None or inc[1] != "fix_ready":
                return
            iid, state, js = inc
        if state == "fix_ready":
            self._propose(spec, now, iid, js, live_cfg, version, outstanding)
        elif state == "proposed":
            self._follow(spec, now, iid, js)
        elif state == "applied":
            self._verify(spec, now, iid, js, live_cfg)

    # ---------------------------------------------------------------- detection
    def _prompt_active_since_h(self, wf, prompt, live_cfg):
        r = self.s.q1("SELECT minute FROM cfgchg WHERE wf=? AND dims LIKE '%prompt_version%' ORDER BY minute DESC LIMIT 1",
                      (wf,))
        return (r[0] // 60) if r else -100000

    def _detect(self, spec, now, live_cfg):
        wf = spec["workflow_id"]
        P = live_cfg["prompt_version"]
        h_lo = self._prompt_active_since_h(wf, P, live_cfg)
        n, k = self.learn.prompt_flags(wf, P, h_lo, now // 60)
        b, _ = self.baseline(wf)
        if n < MIN_CALLS:
            self.s.kv_set(f"suspect:{wf}", None)
            return
        z = binom_z(k, n, b)
        rate = k / n
        hot = z >= Z_DETECT and rate >= max(1.5 * b, b + 0.008)
        sus = self.s.kv_get(f"suspect:{wf}")
        if not hot:
            if sus:
                self.s.kv_set(f"suspect:{wf}", None)
            return
        if not sus or sus.get("prompt") != P:
            self.s.kv_set(f"suspect:{wf}", {"first_min": now, "prompt": P})
            return
        if now - sus["first_min"] < 30:
            return
        edit = self.s.q1("SELECT minute, actor FROM cfgchg WHERE wf=? AND dims LIKE '%prompt_version%' "
                         "ORDER BY minute DESC LIMIT 1", (wf,))
        js = {"prompt": P, "connected": n, "flagged": k, "rate": round(rate, 4), "baseline_rate": round(b, 4),
              "z": round(z, 2), "detected_min": now, "first_suspect_min": sus["first_min"],
              "prompt_changed_min": edit[0] if edit else None, "prompt_changed_by": edit[1] if edit else None,
              "attempts": 0}
        cur = self.s.x("INSERT INTO incident(wf,kind,state,opened_min,js) VALUES(?,?,?,?,?)",
                       (wf, "hallucination", "detected", now, json.dumps(js)))
        self.s.kv_set(f"suspect:{wf}", None)
        self.s.decision(now, wf, "incident_detected",
                        f"hallucination-flag rate {rate:.1%} on {P} vs {b:.1%} baseline (n={n}, z={z:.1f})",
                        inputs=js)
        self.s.alert(now, wf, "page", "hallucination_spike",
                     f"{wf}: flagged-hallucination rate {rate:.1%} on prompt {P} (baseline {b:.1%}, n={n}). "
                     f"Fix is being validated automatically; check /view for the proposal.")

    # ---------------------------------------------------------------- choose + validate a fix
    def _validate(self, wf, prompt, n, now):
        r = self.sim.post("/validation/runs", {"workflow_id": wf, "prompt_version": prompt, "n": n})
        self.s.x("INSERT INTO credit_log(minute,wf,what,credits,js) VALUES(?,?,?,?,?)",
                 (now, wf, "validation_run", -(-n // 100), json.dumps({"prompt": prompt, "n": n, "run": r["validation_run_id"],
                                                                       "pass_rate": r["pass_rate"]})))
        return r

    def _known_good(self, wf, current, baseline):
        out = []
        for prompt, conn, flags, hlo, hhi in self.learn.prompt_summary(wf):
            if prompt == current or conn < 400:
                continue
            if flags / conn <= baseline * 1.3 + 0.003:
                out.append((conn, prompt, round(flags / conn, 4)))
        return [(p, r) for c, p, r in sorted(out, reverse=True)]

    def _choose_fix(self, spec, now, iid, js, live_cfg, credits):
        wf = spec["workflow_id"]
        thr = spec["governance"].get("min_validation_pass_rate", 0.97)
        b, _ = self.baseline(wf)
        if credits < 12:
            self.s.alert(now, wf, "page", "credits_low", f"{wf}: only {credits} credits left during a hallucination "
                                                         f"incident; cannot validate a fix")
            return
        tried = js.setdefault("validated", {})
        for prompt, rate in self._known_good(wf, js["prompt"], b):
            if prompt in tried and tried[prompt]["pass_rate"] >= thr:
                break
            if js["attempts"] >= 3:
                break
            js["attempts"] += 1
            r = self._validate(wf, prompt, VAL_N, now)
            tried[prompt] = {"run": r["validation_run_id"], "pass_rate": r["pass_rate"], "n": VAL_N,
                             "source": "last_known_good", "observed_flag_rate": rate}
            self._save(iid, "detected", js)
            if r["pass_rate"] >= thr:
                break
        ok = [p for p, v in tried.items() if v["pass_rate"] >= thr]
        if not ok:
            if "llm" not in js and credits >= 20:
                sg = self.sim.post("/llm/suggest-fixes", {"workflow_id": wf, "problem":
                                   f"hallucination flag rate {js['rate']:.1%} on prompt {js['prompt']} "
                                   f"(baseline {js['baseline_rate']:.1%}); need a safer prompt that keeps engagement"})
                self.s.x("INSERT INTO credit_log(minute,wf,what,credits,js) VALUES(?,?,?,?,?)",
                         (now, wf, "llm_suggest", 3, json.dumps(sg["suggestions"])))
                js["llm"] = sg["suggestions"]
                self._save(iid, "detected", js)
            for sgx in js.get("llm", []):
                p = sgx["prompt_version"]
                if p in tried or p == js["prompt"]:
                    continue
                r = self._validate(wf, p, VAL_N, now)
                tried[p] = {"run": r["validation_run_id"], "pass_rate": r["pass_rate"], "n": VAL_N,
                            "source": "llm", "summary": sgx.get("summary", "")}
            self._save(iid, "detected", js)
            ok = [p for p, v in tried.items() if v["pass_rate"] >= thr]
        if not ok:
            self.s.alert(now, wf, "page", "no_validated_fix",
                         f"{wf}: no candidate prompt passed validation (>= {thr}); human decision needed")
            return

        def rank(p):    # known-good first (observed engagement), then verbatim scripts last, then pass rate
            v = tried[p]
            verbatim = "verbatim" in (v.get("summary", "") + p).lower() or "strict" in v.get("summary", "").lower()
            return (v["source"] != "last_known_good", verbatim, -v["pass_rate"], p)
        pick = sorted(ok, key=rank)[0]
        js["chosen"] = pick
        js["evidence_run"] = tried[pick]["run"]
        self._save(iid, "fix_ready", js)
        self.s.decision(now, wf, "incident_fix_chosen",
                        f"revert/replace {js['prompt']} -> {pick}: validation pass_rate {tried[pick]['pass_rate']} "
                        f"(threshold {thr}); source={tried[pick]['source']}", inputs=tried, outputs={"chosen": pick})

    # ---------------------------------------------------------------- propose
    def _propose(self, spec, now, iid, js, live_cfg, version, outstanding):
        wf = spec["workflow_id"]
        # an incident fix is allowed to queue behind an unrelated routine approval: whichever applies second just goes stale
        # and is re-planned, but waiting for the routine one to resolve could add hours of harm.
        if not self.gov.window_ok(spec, now) or self.gov.request_budget(spec, now, urgent=True) <= 0:
            return
        cfg = copy.deepcopy(live_cfg)
        cfg["prompt_version"] = js["chosen"]
        v = js["validated"][js["chosen"]]
        did = self.s.decision(
            now, wf, "incident_proposal",
            f"propose prompt {js['prompt']} -> {js['chosen']}", inputs=js, outputs={"prompt": js["chosen"]})
        n_aff = self.s.q1("SELECT COUNT(*) FROM person WHERE wf=? AND pconcl<plast", (wf,))[0]
        pid = self.gov.submit_approval(
            spec, now, cfg, version,
            summary=f"Safety fix: switch prompt {js['prompt']} -> {js['chosen']} (hallucination flags {js['rate']:.1%}"
                    f" vs {js['baseline_rate']:.1%} normal)",
            diff={"prompt_version": {"from": js["prompt"], "to": js["chosen"]}},
            affected=n_aff,
            dry_run={"validation_run_id": v["run"], "pass_rate": v["pass_rate"], "n": v["n"],
                     "current_prompt_flag_rate": js["rate"], "calls_observed": js["connected"],
                     "expected_flag_rate_after": v.get("observed_flag_rate", js["baseline_rate"])},
            impact=0.9,
            rationale=f"{js['flagged']} of {js['connected']} connected calls on {js['prompt']} were flagged "
                      f"({js['rate']:.1%}; z={js['z']} vs {js['baseline_rate']:.1%} baseline). {js['chosen']} passed a "
                      f"validation run at {v['pass_rate']} (needs >= {spec['governance'].get('min_validation_pass_rate', 0.97)}). "
                      f"Chosen as the {'last prompt that ran cleanly here' if v['source'] == 'last_known_good' else 'best validated LLM suggestion'}"
                      f"; this restores a prompt whose engagement we have observed. The previous edit is not deleted, "
                      f"it can be re-applied after the supervisor revises it.",
            evidence={"validation_run_id": v["run"]}, state_patch={"incident": iid}, decision_id=did,
            dims=("prompt_version",))
        js["proposal_id"] = pid
        js["proposed_min"] = now
        self._save(iid, "proposed", js)

    def _follow(self, spec, now, iid, js):
        wf = spec["workflow_id"]
        r = self.s.q1("SELECT state, applied_min FROM proposal WHERE proposal_id=?", (js["proposal_id"],))
        if not r:
            return
        st, applied = r
        if st == "applied":
            js["applied_min"] = applied
            self._save(iid, "applied", js)
            self.s.decision(now, wf, "incident_fix_applied", f"{js['chosen']} live at {fmt_minute(applied)}",
                            proposal_id=js["proposal_id"])
        elif st in ("rejected", "expired", "stale", "lapsed", "failed", "void"):
            js["attempts_proposal"] = js.get("attempts_proposal", 0) + 1
            self.s.alert(now, wf, "warn", "incident_proposal_" + st,
                         f"{wf}: incident-fix proposal {st}; re-proposing (attempt {js['attempts_proposal'] + 1})")
            self._save(iid, "fix_ready", js)

    def _verify(self, spec, now, iid, js, live_cfg):
        wf = spec["workflow_id"]
        if live_cfg["prompt_version"] != js["chosen"]:
            # someone changed it again; re-open detection from scratch
            self._save(iid, "closed", js, now)
            return
        n, k = self.learn.prompt_flags(wf, js["chosen"], js["applied_min"] // 60 + 1, now // 60)
        if n < MIN_CALLS:
            return
        z = binom_z(k, n, js["baseline_rate"])
        js["post_fix"] = {"connected": n, "flagged": k, "rate": round(k / n, 4), "z": round(z, 2)}
        if z < 2.5:
            js["mttr_min"] = js["applied_min"] - (js["prompt_changed_min"] or js["detected_min"])
            self._save(iid, "verified", js, now)
            self.s.decision(now, wf, "incident_verified",
                            f"flag rate after fix {k / n:.1%} (n={n}) is back in the normal range", inputs=js["post_fix"])
        elif n >= 400:
            self._save(iid, "failed", js, now)
            self.s.alert(now, wf, "page", "incident_fix_failed",
                         f"{wf}: flag rate still {k / n:.1%} after switching to {js['chosen']} (n={n})")
