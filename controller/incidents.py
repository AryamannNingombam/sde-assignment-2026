"""Hallucination incident response (C8): detect -> pick a fix cheapest-first -> validate -> propose -> verify.

Candidates are validated one at a time in a pre-declared order and the FIRST that passes is proposed:
  1. revert to the previous prompt (it has a known track record),
  2. the grounded catalogue prompt(s),
  3. LLM suggestions (3 credits), only if 1-2 fail.
Picking the best of several validation runs would select for noise, so we never do that. Catalogue entries known
to kill engagement ('strict', 'near-verbatim') are skipped.

Credit-costing calls are not idempotent: each one gets an intent row in `credit_ops` before the call, is never
retried, and an unknown outcome counts the credits as spent (SUBMISSION §9).
"""
from __future__ import annotations

import json
import math
import re
import sqlite3

from . import configs, governance, impact, metrics, settings, stats, store
from .detectors import hallu_baseline, hallu_verdict
from .sim_client import SimClient

OWNER = "incidents"
ACTIVE = ("OPEN", "PROPOSED", "VERIFYING")


class Incidents:
    def __init__(self, conn: sqlite3.Connection, client: SimClient, specs: dict[str, dict]):
        self.conn, self.client, self.specs = conn, client, specs

    # ================================================================== open
    def open_hallucination(self, wf: str, prompt: str, evidence: dict, minute: int) -> None:
        if self.conn.execute(f"SELECT 1 FROM incidents WHERE wf=? AND state IN ({_q(ACTIVE)})", (wf,)).fetchone():
            return
        gave_up = self.conn.execute("SELECT 1 FROM incidents WHERE wf=? AND state='NO_FIX' AND closed_minute>?"
                                    " AND json_extract(context_json, '$.bad_prompt')=?",
                                    (wf, minute - settings.NO_FIX_COOLDOWN_MIN, prompt)).fetchone()
        if gave_up:
            return                                  # a human has been paged; don't burn credits in a loop
        queue = self._initial_candidates(wf, prompt)
        ctx = {"bad_prompt": prompt, "detector": evidence, "queue": queue, "tried": [], "suggested": False}
        cur = self.conn.execute("INSERT INTO incidents(wf, kind, opened_minute, state, context_json, timeline_json)"
                                " VALUES(?, 'hallucination', ?, 'OPEN', ?, '[]')", (wf, minute, json.dumps(ctx)))
        iid = cur.lastrowid
        self._event(iid, minute, f"opened: {prompt} flagged rate {evidence['rate']} vs baseline {evidence['baseline']}"
                                 f" (p={evidence['p']}); candidates {queue}")
        store.record_decision(self.conn, minute, wf, "incident", "hallucination spike held for consecutive windows",
                              {**evidence, "candidates": queue}, "incident opened", incident_id=iid)
        store.raise_alert(self.conn, minute, "page", wf, f"hallucination incident #{iid} on prompt {prompt}")

    def _initial_candidates(self, wf: str, bad: str) -> list[str]:
        catalog = self.specs[wf]["prompt_catalog"]
        out = []
        prev = self._previous_prompt(wf, bad)
        if prev:
            out.append(prev)
        out += [p for p, s in catalog.items() if any(w in s.lower() for w in settings.HALLU_PREFER_WORDS)]
        return _dedupe([p for p in out if p != bad and not _risky(catalog.get(p, ""))])

    def _previous_prompt(self, wf: str, bad: str) -> str | None:
        for r in self.conn.execute("SELECT config_json FROM config_versions WHERE wf=? AND config_json IS NOT NULL"
                                   " ORDER BY version DESC", (wf,)):
            p = json.loads(r[0])["prompt_version"]
            if p != bad:
                return p
        return None

    # ================================================================== tick
    def step(self, minute: int) -> None:
        self._settle_unknown_credit_ops(minute)
        for inc in self.conn.execute("SELECT * FROM incidents WHERE state IN ('OPEN','VERIFYING')").fetchall():
            if inc["state"] == "OPEN":
                self._advance(inc, minute)          # manages its own transactions around credit calls
            else:
                with store.tx(self.conn):
                    self._verify(inc, minute)

    def _advance(self, inc: sqlite3.Row, minute: int) -> None:
        """Validate candidates in order until one passes, the queue is empty, or credits stop us."""
        wf = inc["wf"]
        while True:
            inc = self._row(inc["id"])
            ctx = json.loads(inc["context_json"])
            if not ctx["queue"]:
                if not ctx["suggested"] and self._affordable(inc, settings.SUGGEST_COST, optional=True):
                    self._suggest(inc, ctx, minute)
                    continue
                again = next((t for t in ctx["tried"] if t.get("run") and t["run"].get("passes")
                              and _asks(ctx, t["prompt"]) < settings.INCIDENT_MAX_ASKS), None)
                if again:
                    with store.tx(self.conn):           # every candidate is exhausted: ask once more, saying so
                        self._event(inc["id"], minute, f"no other candidate; asking again for {again['prompt']}")
                        self._propose(self._row(inc["id"]), again["prompt"], again["run"], minute)
                    return
                with store.tx(self.conn):
                    self._close(inc, "NO_FIX", minute, "no candidate passed validation within the credit cap")
                    store.raise_alert(self.conn, minute, "page", wf, f"incident #{inc['id']}: no validated fix; "
                                                                      "needs a human")
                return
            cand = ctx["queue"][0]
            cost = math.ceil(settings.VALIDATION_N / 100)
            reuse = self._previous_validation(wf, cand)
            if reuse is None and not self._affordable(inc, cost):
                with store.tx(self.conn):
                    self._close(inc, "NO_FIX", minute, f"credit cap reached before validating {cand}")
                    store.raise_alert(self.conn, minute, "page", wf, f"incident #{inc['id']}: out of incident credits")
                return
            run = reuse or self._credit_op(inc, "validate", {"prompt_version": cand, "n": settings.VALIDATION_N}, cost,
                                           lambda: self.client.validate(wf, cand, settings.VALIDATION_N), minute)
            with store.tx(self.conn):
                ctx = json.loads(self._row(inc["id"])["context_json"])
                ctx["queue"].pop(0)
                ctx["tried"].append({"prompt": cand, "run": run})
                if run is None:
                    self._save(inc["id"], ctx)
                    continue
                ok, rule = validation_passes(run["pass_rate"], run["n"],
                                             self.specs[wf]["governance"]["min_validation_pass_rate"])
                run["passes"] = ok
                self._save(inc["id"], ctx)
                self._event(inc["id"], minute, f"validated {cand}: pass_rate {run['pass_rate']} ({rule}) -> "
                                               f"{'PASS' if ok else 'fail'}")
                if ok:
                    self._propose(self._row(inc["id"]), cand, run, minute)
                    return

    def _suggest(self, inc, ctx, minute) -> None:
        wf = inc["wf"]
        problem = (f"Prompt {ctx['bad_prompt']} hallucination flag rate {ctx['detector']['rate']} vs baseline "
                   f"{ctx['detector']['baseline']}; need a prompt that stays grounded in policy facts.")
        res = self._credit_op(inc, "suggest", {"problem": problem}, settings.SUGGEST_COST,
                              lambda: self.client.suggest_fixes(wf, problem), minute)
        with store.tx(self.conn):
            ctx = json.loads(self._row(inc["id"])["context_json"])
            ctx["suggested"] = True
            tried = {t["prompt"] for t in ctx["tried"]} | {ctx["bad_prompt"]}
            for s in (res or {}).get("suggestions", []):
                if s["prompt_version"] not in tried and not _risky(s.get("summary", "")):
                    ctx["queue"].append(s["prompt_version"])
            ctx["queue"] = _dedupe(ctx["queue"])
            self._save(inc["id"], ctx)
            self._event(inc["id"], minute, f"LLM suggestions -> queue {ctx['queue']}")

    def _propose(self, inc, cand: str, run: dict, minute: int) -> None:
        ctx = json.loads(inc["context_json"])
        det = ctx["detector"]
        sup = self.conn.execute("SELECT version FROM config_versions WHERE wf=? AND actor='supervisor'"
                                " ORDER BY version DESC LIMIT 1", (inc["wf"],)).fetchone()
        named = f" This reverses supervisor edit v{sup[0]}; we are asking, not overwriting." if sup else ""
        payload = {
            "change_summary": f"Switch prompt {ctx['bad_prompt']} -> {cand} to stop a hallucination spike",
            "rationale": f"{ctx['bad_prompt']} is flagging {det['rate']} of connected calls vs a {det['baseline']} "
                         f"baseline (Poisson p={det['p']}, {det['connected']} calls, held for consecutive windows). "
                         f"{cand} passed validation run {run['validation_run_id']} at {run['pass_rate']} on n={run['n']}"
                         f", above the bar with margin for noise.{named}",
            "impact_score": impact.score_harm_avoided(max(0.0, det["rate"] - det["baseline"]), 1.0),
            "evidence": {"validation_run_id": run["validation_run_id"]},
            "dry_run_extra": {"incident": inc["id"], "detector": det, "validation": run},
        }
        did = store.record_decision(self.conn, minute, inc["wf"], "incident", "first candidate to pass validation",
                                    {"candidate": cand, "validation": run}, "propose", incident_id=inc["id"])
        pid = governance.draft(self.conn, minute, inc["wf"], "incident_fix", {"prompt_version": cand}, payload,
                               owner=OWNER, refs={"incident": inc["id"]}, decision_id=did, urgent=True)
        self.conn.execute("UPDATE decisions SET proposal_id=? WHERE id=?", (pid, did))
        ctx.update(candidate=cand, validation=run, proposal_id=pid)
        ctx.setdefault("asks", {})[cand] = _asks(ctx, cand) + 1
        self._save(inc["id"], ctx)
        self.conn.execute("UPDATE incidents SET state='PROPOSED' WHERE id=?", (inc["id"],))
        self._event(inc["id"], minute, f"proposed {cand} as {pid}")

    # ================================================================== verify after apply
    def _verify(self, inc, minute: int) -> None:
        ctx = json.loads(inc["context_json"])
        wf, cand = inc["wf"], ctx["candidate"]
        since = ctx["applied_minute"] // 60 + 1
        c = metrics.total(self.conn, wf, since_hour=since, until_hour=minute // 60, prompt=cand)
        if c.connected < settings.HALLU_MIN_CONNECTED or minute - ctx["applied_minute"] < settings.VERIFY_AFTER_MIN:
            return
        base, src = hallu_baseline(self.conn, wf, cand)
        v = hallu_verdict(c.halluc, c.connected, base, settings.HALLU_MIN_CONNECTED)
        pre = metrics.total(self.conn, wf, until_hour=0)
        p_eng = stats.p_less(c.concluded, c.connected, pre.concluded, pre.connected)
        inputs = {"hallucination": v, "baseline_source": src, "engagement_after": _r(c.rate("engagement_rate")),
                  "engagement_history": _r(pre.rate("engagement_rate")), "p_engagement_lower": _r(p_eng, 6)}
        if v["fire"]:
            store.record_decision(self.conn, minute, wf, "incident", "verify: rate still above band", inputs,
                                  "fix failed: try next candidate", incident_id=inc["id"])
            self.conn.execute("UPDATE incidents SET state='OPEN' WHERE id=?", (inc["id"],))
            ctx["bad_prompt"] = cand
            self._save(inc["id"], ctx)
            return
        if p_eng < settings.HARM_ALPHA:
            store.record_decision(self.conn, minute, wf, "incident", "verify: engagement below pre-incident baseline",
                                  inputs, "fix holds on safety but costs engagement: flagged for review",
                                  incident_id=inc["id"])
            store.raise_alert(self.conn, minute, "summary", wf,
                              f"incident #{inc['id']} fix {cand} lowered engagement; review (not auto-reverted)")
        self._close(inc, "RESOLVED", minute, "verified: hallucination rate back within band", inputs)

    # ================================================================== governance callbacks
    def revalidate(self, conn, p, minute) -> tuple[bool, str]:
        inc = self._row(json.loads(p["refs_json"])["incident"])
        if inc["state"] != "PROPOSED":
            return False, f"incident is {inc['state']}"
        _, cur = configs.current(conn, p["wf"])
        if cur["prompt_version"] != json.loads(inc["context_json"])["bad_prompt"]:
            return False, "the flagged prompt is no longer live"
        return True, "flagged prompt still live"

    def on_applied(self, conn, p, version, minute) -> None:
        inc = self._row(json.loads(p["refs_json"])["incident"])
        ctx = json.loads(inc["context_json"])
        ctx.update(applied_minute=minute, applied_version=version)
        self._save(inc["id"], ctx)
        conn.execute("UPDATE incidents SET state='VERIFYING' WHERE id=?", (inc["id"],))
        store.set_meta(conn, f"hallu_streak:{p['wf']}", 0)
        self._event(inc["id"], minute, f"fix live{f' as v{version}' if version else ''}; verifying")

    def on_terminal(self, conn, p, state, minute) -> None:
        inc = self._row(json.loads(p["refs_json"])["incident"])
        if inc["state"] != "PROPOSED":
            return
        ctx = json.loads(inc["context_json"])
        if state == "REJECTED":       # client said no to this content: move to the next candidate
            self._event(inc["id"], minute, f"{p['proposal_id']} rejected ({p['reasons']}); next candidate")
            conn.execute("UPDATE incidents SET state='OPEN' WHERE id=?", (inc["id"],))
            return
        _, cur = configs.current(conn, p["wf"])
        if cur["prompt_version"] == ctx["candidate"]:        # the fix is live anyway (e.g. a human applied it)
            self._event(inc["id"], minute, f"{p['proposal_id']} {state.lower()}; {ctx['candidate']} already live")
            self.on_applied(conn, p, None, minute)
            return
        if cur["prompt_version"] != ctx["bad_prompt"]:       # someone else replaced the flagged prompt
            self._close(inc, "SUPERSEDED", minute, f"flagged prompt {ctx['bad_prompt']} no longer live")
            return
        if state != "DROPPED" and _asks(ctx, ctx["candidate"]) < settings.INCIDENT_MAX_ASKS:
            # expired / lapsed / stale: a non-decision; the validation still holds, ask again on the current base
            self._event(inc["id"], minute, f"{p['proposal_id']} {state.lower()}; re-proposing")
            self._propose(inc, ctx["candidate"], ctx["validation"], minute)
            return
        self._event(inc["id"], minute, f"{p['proposal_id']} {state.lower()}; asks for {ctx['candidate']} used up,"
                                       " next candidate")
        conn.execute("UPDATE incidents SET state='OPEN' WHERE id=?", (inc["id"],))

    def on_supervisor_prompt_change(self, wf: str, version: int, minute: int) -> None:
        for inc in self.conn.execute(f"SELECT * FROM incidents WHERE wf=? AND state IN ({_q(ACTIVE)})", (wf,)).fetchall():
            self._close(inc, "SUPERSEDED", minute, f"supervisor changed the prompt (v{version})")

    # ================================================================== credits
    def _previous_validation(self, wf: str, prompt: str) -> dict | None:
        """A validation run for this workflow and prompt is reusable evidence: never pay for it twice."""
        row = self.conn.execute(
            "SELECT o.result_json FROM credit_ops o JOIN incidents i ON i.id=o.incident_id WHERE i.wf=? AND"
            " o.kind='validate' AND o.state='DONE' AND json_extract(o.request_json, '$.prompt_version')=?"
            " ORDER BY o.id DESC LIMIT 1", (wf, prompt)).fetchone()
        return json.loads(row[0]) if row else None

    def _affordable(self, inc, cost: float, optional: bool = False) -> bool:
        """Per-incident cap always applies. Optional spend (LLM suggestions, a fallback) must also leave the
        reserve intact; validating a known candidate is the incident's essential spend and may use the reserve."""
        remaining = store.get_meta(self.conn, "credits_remaining", 0)
        floor = store.get_meta(self.conn, "credits_start", 0) * settings.CREDIT_RESERVE_FRAC if optional else 0
        return inc["credits_spent"] + cost <= settings.CREDIT_CAP_PER_INCIDENT and remaining - cost >= floor

    def _credit_op(self, inc, kind: str, request: dict, cost: float, call, minute: int) -> dict | None:
        with store.tx(self.conn):           # intent first: if we die mid-call the cost is counted as spent
            op = self.conn.execute("INSERT INTO credit_ops(incident_id, kind, state, request_json, cost, minute)"
                                   " VALUES(?,?,'REQUESTED',?,?,?)", (inc["id"], kind, json.dumps(request), cost, minute)
                                   ).lastrowid
        r = call()
        with store.tx(self.conn):
            if r.ok:
                state, spent, result = "DONE", cost, r.json
                store.set_meta(self.conn, "credits_remaining", r.json.get("credits_remaining", 0))
            elif r.status is None:
                state, spent, result = "UNKNOWN", cost, None
            else:
                state, spent, result = "FAILED", 0, None
                if r.status == 402:
                    store.raise_alert(self.conn, minute, "page", inc["wf"], "out of credits during an incident")
            self.conn.execute("UPDATE credit_ops SET state=?, result_json=? WHERE id=?",
                              (state, json.dumps(r.json), op))
            self.conn.execute("UPDATE incidents SET credits_spent=credits_spent+? WHERE id=?", (spent, inc["id"]))
            store.record_decision(self.conn, minute, inc["wf"], "credits", f"{kind} ({cost} credits)",
                                  {"request": request, "status": r.status}, state, incident_id=inc["id"])
        return result

    def _settle_unknown_credit_ops(self, minute: int) -> None:
        """After a crash: a credit op still REQUESTED has an unknown outcome. Count it, never repeat it."""
        with store.tx(self.conn):
            for op in self.conn.execute("SELECT * FROM credit_ops WHERE state='REQUESTED'").fetchall():
                self.conn.execute("UPDATE credit_ops SET state='UNKNOWN' WHERE id=?", (op["id"],))
                self.conn.execute("UPDATE incidents SET credits_spent=credits_spent+? WHERE id=?",
                                  (op["cost"], op["incident_id"]))
                ctx = json.loads(self._row(op["incident_id"])["context_json"])
                req = json.loads(op["request_json"])
                if op["kind"] == "validate" and ctx["queue"] and ctx["queue"][0] == req["prompt_version"]:
                    ctx["queue"].pop(0)
                    ctx["tried"].append({"prompt": req["prompt_version"], "run": None, "note": "unknown outcome"})
                if op["kind"] == "suggest":
                    ctx["suggested"] = True
                self._save(op["incident_id"], ctx)
                store.record_decision(self.conn, minute, None, "credits", "restart: credit op with unknown outcome",
                                      {"op": op["id"], "kind": op["kind"]}, f"{op['cost']} credits counted as spent",
                                      incident_id=op["incident_id"])

    # ================================================================== helpers
    def _close(self, inc, state: str, minute: int, rule: str, inputs: dict | None = None) -> None:
        self.conn.execute("UPDATE incidents SET state=?, closed_minute=? WHERE id=?", (state, minute, inc["id"]))
        store.record_decision(self.conn, minute, inc["wf"], "incident", rule, inputs or {}, state, incident_id=inc["id"])
        self._event(inc["id"], minute, f"{state}: {rule}")

    def _event(self, iid: int, minute: int, text: str) -> None:
        tl = json.loads(self._row(iid)["timeline_json"])
        tl.append({"minute": minute, "event": text})
        self.conn.execute("UPDATE incidents SET timeline_json=? WHERE id=?", (json.dumps(tl), iid))

    def _save(self, iid: int, ctx: dict) -> None:
        self.conn.execute("UPDATE incidents SET context_json=? WHERE id=?", (json.dumps(ctx), iid))

    def _row(self, iid: int) -> sqlite3.Row:
        return self.conn.execute("SELECT * FROM incidents WHERE id=?", (iid,)).fetchone()


def validation_passes(pass_rate: float, n: int, min_rate: float) -> tuple[bool, str]:
    """Margin for noise: the approver's raw check could pass on a lucky run, ours should not."""
    se = math.sqrt(max(pass_rate * (1 - pass_rate), 1e-9) / n)
    lower = pass_rate - settings.VALIDATION_Z * se
    bar = min_rate - settings.VALIDATION_SLACK
    return pass_rate >= min_rate and lower >= bar, f"lower {lower:.4f} vs bar {bar:.4f}"


def _asks(ctx: dict, prompt: str) -> int:
    asks = ctx.get("asks") or {}
    return asks.get(prompt, 0) if isinstance(asks, dict) else 0


def _risky(summary: str) -> bool:
    """Whole words only: 'restricted' must not match 'strict'."""
    return any(re.search(rf"\b{re.escape(w)}\b", summary.lower()) for w in settings.HALLU_SKIP_WORDS)


def _dedupe(xs: list[str]) -> list[str]:
    return list(dict.fromkeys(xs))


def _q(states) -> str:
    return ",".join(f"'{s}'" for s in states)


def _r(x, nd: int = 4):
    return None if x is None else round(float(x), nd)
