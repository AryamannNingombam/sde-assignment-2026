"""The control loop: ingest -> detect -> hypothesise -> propose/apply -> verify, with every decision written to the audit store.

Order of priority per workflow per tick (at most ONE config change submitted per workflow per tick):
  1. hallucination incident (prompt)      - urgent, needs validation evidence, approval path
  2. caller-ID degradation / rebalancing  - auto-apply when the policy allows it (stepwise within max_shift)
  3. cohort experiments (voice, welcome)  - Thompson sampling, batched into one proposal per cycle
"""
import copy
import hashlib
import json
import os
import signal
import threading
import time

from . import policy as P
from ..api import Api, ApiError, BreakerOpen
from .ingest import Ingestor
from ..observability.alerts import Alerter
from .limits import TokenBucket
from ..observability.logs import emit, record
from ..observability.metrics import Metrics, serve
from ..storage import Store
from ..observability.trace import Tracer, current
from .timeutil import hr_of, label, min_of

RESERVE_CREDITS = 8.0
VALIDATION_N = 400
DID_MIN_PIMPROVE = 0.90   # caller-ID rebalance must beat the live allocation with this probability
EXP_MIN_PIMPROVE = 0.85   # same for voice/welcome allocations
TIGHT_PIMPROVE = 0.95     # while a guardrail is under pressure ('hold'): evidence bar rises, exploration of unseen options stops
GUARD_AFFECTS = {"pickup_rate": ("caller_id",), "engagement_rate": ("voice", "welcome_message")}   # which dims move which KPI
GUARD_WINDOW_H = 48


class Controller:
    def __init__(self, url: str, state_dir: str, log=emit):
        self.st = Store(state_dir)
        self.tracer = Tracer(self.st.span)
        self.metrics = Metrics()
        self.alerts = Alerter(self.log)
        self.limiter = TokenBucket(capacity=6, refill_per_min=1 / 30)   # credit-spending calls per workflow (sim time)
        self._stop = threading.Event()
        self.last_tick_wall = None
        self.tick_no = 0
        self.api = Api(url, tracer=self.tracer, metrics=self.metrics, on_breaker=self._on_breaker)
        self._sink = log
        self.wfs: dict[str, dict] = {}
        self.credits = None
        self.now_ts = ""
        self.now_min = 0
        self.now_hr = 0
        self.tick_events = 0
        self.guard: dict[str, dict] = {}        # workflow -> latest guardrail status
        self._gref: dict = {}
        self.wf_fails: dict[str, int] = {}      # bulkhead: consecutive crashes per workflow
        self.wf_skip: dict[str, int] = {}       # workflow quarantined until this sim minute

    def log(self, msg: str, level: str = "info", **fields):
        """Structured log: JSON record with trace/span ids and sim time; extra keyword args become fields."""
        rec = record(msg, level, **fields)
        if self.now_ts:
            rec["sim_ts"] = self.now_ts
        self._sink(rec)

    def _on_breaker(self, name: str, state: str):
        self.metrics.set("breaker_state", 2 if state == "open" else 0, breaker=name)
        if state == "open":
            self.alerts.fire(f"breaker:{name}", f"circuit breaker '{name}' OPEN: simulator failing", breaker=name)
        else:
            self.log("circuit breaker closed", breaker=name)

    def health(self) -> dict:
        age = None if self.last_tick_wall is None else round(time.time() - self.last_tick_wall, 1)
        quarantined = sorted(w for w, until in self.wf_skip.items() if until > self.now_min)
        ready = (age is not None and age < float(os.environ.get("CTRL_READY_MAX_AGE_S", "120"))
                 and not self._stop.is_set() and not all(b.state == "open" for b in self.api.breakers.values()))
        return {"ready": ready, "tick": self.tick_no, "sim_ts": self.now_ts, "last_tick_age_s": age, "credits": self.credits,
                "breakers": {n: b.state for n, b in self.api.breakers.items()}, "quarantined": quarantined,
                "shutting_down": self._stop.is_set()}

    def _gauges(self):
        m = self.metrics
        for n, b in self.api.breakers.items():
            m.set("breaker_state", {"closed": 0, "half_open": 1, "open": 2}[b.state], breaker=n)
        if self.credits is not None:
            m.set("credits_remaining", self.credits)
        m.set("quarantined_workflows", sum(1 for u in self.wf_skip.values() if u > self.now_min))
        counts: dict = {}
        for p in self.st.proposals():
            counts[p["status"]] = counts.get(p["status"], 0) + 1
        for st, n in counts.items():
            m.set("proposals", n, status=st)
        m.set("tick", self.tick_no)

    def _prune(self):
        hours = float(os.environ.get("CTRL_SPAN_RETENTION_H", "24"))
        n = self.st.prune_spans(time.time() - hours * 3600)
        if n:
            self.log("pruned old spans", rows=n, retention_h=hours)

    # ------------------------------------------------------------------ startup / recovery
    def startup(self):
        state = self.api.get("/sim/state")
        self.wfs = {w["workflow_id"]: w for w in self.api.get("/workflows")}
        prev = self.st.get("sig")
        # A restarted simulator is a NEW world: same scenario name, but time and chunk numbers go backwards relative to what we
        # already processed. Compare against the LIVE progress markers (seen_chunks / now_min), not a signature taken at last startup.
        went_back = state["chunks"] < self.st.get("seen_chunks", 0) or min_of(state["ts"]) < self.st.get("now_min", -10**9)
        if prev and (prev["scenario"] != state["scenario"] or went_back):
            self.log("new world detected; resetting controller state", "warning", prev_scenario=prev["scenario"], scenario=state["scenario"])
            self.st.reset()
        self.st.set("sig", {"scenario": state["scenario"]})
        self.ing = Ingestor(self.st)
        self._time(state)
        self.reconcile()

    def _time(self, state):
        self.now_ts = state["ts"]
        self.now_min = min_of(state["ts"])
        self.now_hr = hr_of(state["ts"])
        self.credits = state["credits_remaining"]
        self.st.set("now_min", self.now_min)

    def _landed(self, p):
        """Ask the simulator whether this proposal_id already reached it. Returns (status, approval_id) or None."""
        wid = p["wf"]
        hist = self.api.get(f"/workflows/{wid}/config/history")
        if any(h.get("proposal_id") == p["proposal_id"] for h in hist):
            return "applied_auto", None
        found = [a for a in self.api.get("/approvals", workflow_id=wid) if a["proposal_id"] == p["proposal_id"]]
        if found:
            return "pending_approval", found[0]["approval_id"]
        return None

    def reconcile(self):
        """After a crash: resolve proposals whose send/apply outcome we do not know, using the simulator as source of truth."""
        for p in self.st.proposals(statuses=("sending",)):
            wid, pid = p["wf"], p["proposal_id"]
            hit = self._landed(p)
            if hit and hit[0] == "applied_auto":
                self.st.set_status(pid, "applied_auto")
                self._audit(wid, "recovered", f"{pid}: auto-apply had reached the simulator before the crash", {})
            elif hit:
                self.st.set_status(pid, "pending_approval", hit[1])
                self._audit(wid, "recovered", f"{pid}: approval request had reached the simulator (apr {hit[1]})", {})
            else:
                self.st.set_status(pid, "abandoned")
                self._audit(wid, "recovered", f"{pid}: send never reached the simulator; will be re-planned", {})

    # ------------------------------------------------------------------ ingestion
    def ingest_new(self) -> int:
        total = 0
        for kind in ("history", "events"):
            after = self.st.get("last_" + kind, -1)
            for ch in self.api.get("/events/chunks", kind=kind, after=after):
                agg, leads, notable, n = self.ing.process(self.api.chunk(ch["chunk"]))
                audits = [a for a in (self._notable_audit(ev) for ev in notable) if a]
                self.st.commit_chunk(agg, leads, {"last_" + kind: ch["chunk"], "max_day": self.ing.max_day,
                                                 "seen_chunks": ch["chunk"] + 1}, audits)
                total += n
        if total:
            self.ing.evict_old()
        return total

    def _notable_audit(self, ev):
        t = ev["type"]
        if t == "config_changed":
            if "prompt_version" in ev["changed_dims"]:
                self.st.set(f"pchg|{ev['workflow_id']}", min_of(ev["ts"]))
            return (ev["ts"], min_of(ev["ts"]), ev["workflow_id"], "config_changed",
                    f"v{ev['version']} by {ev['actor']} changed {ev['changed_dims']}", ev)
        if t == "approval_decided":
            return (ev["ts"], min_of(ev["ts"]), ev["workflow_id"], "approval_decided",
                    f"{ev['approval_id']} {ev['status']} {ev.get('reasons') or ''}", ev)
        return None

    def _audit(self, wf, kind, summary, details):
        c = current()
        if c and isinstance(details, dict):
            details = {**details, "trace_id": c[0], "span_id": c[1]}   # link every audit row to its trace
        self.st.audit(self.now_ts, self.now_min, wf, kind, summary, details)

    # ------------------------------------------------------------------ per-tick decisions
    def decide_all(self):
        try:
            self.poll()
        except BreakerOpen:
            raise
        except (ApiError, ConnectionError) as e:   # a failing poll must not stop new decisions
            self.log("poll failed", "error", error=str(e))
        for wid in self.wfs:
            if self.wf_skip.get(wid, -1) > self.now_min:
                continue                            # bulkhead: workflow quarantined after repeated crashes
            try:
                with self.tracer.span(f"decide:{wid}", wf=wid):
                    self.decide(wid)
                self.wf_fails[wid] = 0
            except BreakerOpen:
                raise                               # simulator unhealthy: stop the whole pass, retry next tick
            except ApiError as e:
                self._audit(wid, "error", f"api error {e.status} {e.code}", {"body": e.body})
                self.log("api error", "error", wf=wid, status=e.status, code=e.code)
            except Exception as e:                  # bulkhead: one workflow's bug/crash must not take down the others
                n = self.wf_fails[wid] = self.wf_fails.get(wid, 0) + 1
                if n >= 3:
                    self.wf_skip[wid] = self.now_min + 60
                    self.wf_fails[wid] = 0
                    self.alerts.fire(f"quarantine:{wid}", f"workflow {wid} quarantined 60 sim-min after 3 crashes: {e!r}", wf=wid)
                self._audit(wid, "error", f"{type(e).__name__}: {e} (crash {n}/3{', quarantined 60 min' if n >= 3 else ''})", {})
                self.log("workflow crashed", "error", wf=wid, error=repr(e), crashes=n)

    def decide(self, wid: str):
        cur = self.api.get(f"/workflows/{wid}/config")
        ver, cfg = cur["version"], cur["config"]
        if self.handle_prompt(wid, ver, cfg):
            return
        g = self.guardrail(wid)
        # an urgent prompt fix is waiting for approval: any other config change would bump the version and make it stale
        if any(p["kind"] == "prompt_fix" for p in self.st.proposals(wid, ("pending_approval", "sending"))):
            return
        did = self.plan_did(wid, cfg, g)
        if did and self.auto_ok(wid, ["caller_id"]):
            tgt = copy.deepcopy(cfg)
            tgt["allocations"]["default"]["caller_id"] = did[0]
            self._strip_cohort_dim(tgt, "caller_id")
            self.submit(wid, "caller_id", tgt, "Rebalance caller IDs by measured pickup",
                        f"Pickup differs by caller ID (recent, half-life 6h): {json.dumps(did[1])}. Allocation proportional to shrunk pickup^4, "
                        f"unexplored IDs capped at 15%.", {"method": "pickup-weighted allocation", "per_did": did[1]},
                        impact=0.4, evidence=None)
            return
        exp = self.plan_exp(wid, cfg, g) if self.exp_due(wid) else None
        if did or exp:
            tgt = copy.deepcopy(exp["target"] if exp else cfg)
            if did:
                tgt["allocations"]["default"]["caller_id"] = did[0]
                self._strip_cohort_dim(tgt, "caller_id")
            kind = "batch" if (did and exp) else ("experiment" if exp else "caller_id")
            if exp:
                self.st.set(f"next_exp|{wid}", self.now_min + (240 if self.auto_ok(wid, ["voice", "welcome_message"]) else 1200))
            self.submit(wid, kind, tgt, exp["summary"] if exp else "Rebalance caller IDs by measured pickup",
                        exp["rationale"] if exp else "Caller-ID pickup differs; see dry_run.",
                        {**(exp["dry_run"] if exp else {}), **({"caller_id": did[1]} if did else {})},
                        impact=exp["impact"] if exp else 0.4, evidence=None, affected=exp["affected"] if exp else None)
        elif self.exp_due(wid):
            self.st.set(f"next_exp|{wid}", self.now_min + 240)

    # ---- prompt / hallucination -------------------------------------------------------------
    # ---- guardrail KPI --------------------------------------------------------------------------
    def guardrail(self, wid) -> dict:
        """Explicit primary-vs-guardrail check, every tick: the workflow's guardrail KPI over the last 48 h versus its
        pre-D0 history, judged by the lower confidence bound of the drop. hold = tighten (evidence bar 0.95, no exploration of
        unseen options on the dims that move that KPI); breach = freeze those dims (urgent fixes still allowed) and alert."""
        gr = self.wfs[wid]["objective"]["guardrail"]
        key, limit = next(iter(gr.items()))
        kpi = key.replace("_max_drop", "")
        prefix = "did|" if kpi == "pickup_rate" else "eng|voice|"
        nk = (lambda r: (r[0], r[1])) if kpi == "pickup_rate" else (lambda r: (r[1], r[2]))   # (n, k) from [dials, conn, eng, flag]
        ref = self._gref.get((wid, kpi))
        if ref is None and self.now_hr > 0:
            ref = self._gref[(wid, kpi)] = nk(self.st.span_sum(wid, prefix, -10**6, 0))   # history is complete once D0 has started
        out = {"state": "unknown", "kpi": kpi, "affects": GUARD_AFFECTS[kpi], "limit": limit}
        if ref:
            rows = self.st.window(wid, self.now_hr, GUARD_WINDOW_H, prefix)
            cn = sum(nk(r)[0] for r in rows.values()); ck = sum(nk(r)[1] for r in rows.values())
            prev = self.guard.get(wid, {}).get("state", "ok")
            out.update(P.guardrail_status(ref[0], ref[1], cn, ck, limit, prev))
            if out["state"] != "unknown":
                self.metrics.set("guardrail_drop", out["drop"], wf=wid, kpi=kpi)
                if out["state"] != prev:
                    self._audit(wid, f"guardrail_{out['state']}", f"{kpi} {out['cur']:.3f} vs history {out['ref']:.3f} "
                                f"(drop {out['drop']:.3f}, lower bound {out['lb']:.3f}, limit {limit}): {prev} -> {out['state']}", dict(out))
                    self.log("guardrail state change", "warning" if out["state"] != "ok" else "info", wf=wid, kpi=kpi, state=out["state"], drop=out["drop"])
                    if out["state"] == "breach":
                        self.alerts.fire(f"guardrail:{wid}", f"{wid}: {kpi} dropped {out['drop']:.3f} vs history (limit {limit}); "
                                         f"voice/welcome/caller-ID changes on that KPI frozen", wf=wid, kpi=kpi)
        self.guard[wid] = out
        return out

    def _prompt_stats(self, wid) -> dict:
        """All-time per-prompt engagement and flow adherence: {prompt: {conn, eng, fla_n, fla_sum}}."""
        out: dict = {}
        for key, r in self.st.alltime(wid, "eng|voice|").items():
            p = key.rsplit("|", 1)[1]
            o = out.setdefault(p, {"conn": 0.0, "eng": 0.0, "fla_n": 0.0, "fla_sum": 0.0})
            o["conn"] += r[1]; o["eng"] += r[2]
        for key, r in self.st.alltime(wid, "fla|").items():
            o = out.setdefault(key.split("|", 1)[1], {"conn": 0.0, "eng": 0.0, "fla_n": 0.0, "fla_sum": 0.0})
            o["fla_n"] += r[0]; o["fla_sum"] += r[1]
        return out

    def handle_prompt(self, wid, ver, cfg) -> bool:
        recent = self.st.window(wid, self.now_hr, 4, "prm|")
        hist = self.st.alltime(wid, "prm|")
        recently = self.now_min - self.st.get(f"pchg|{wid}", -99999) < 480
        inc = P.prompt_incident(recent, hist, cfg["prompt_version"], recently)
        self.verify_prompt_fixes(wid, cfg)
        if not inc:
            return False
        busy = [p for p in self.st.proposals(wid) if p["kind"] == "prompt_fix" and
                (p["status"] in ("sending", "pending_approval") or (p["status"] in ("applied", "applied_auto") and p["created_min"] > self.now_min - 240))]
        if busy:
            return False
        key = f"inc|{wid}|prompt|{cfg['prompt_version']}"
        if self.st.get(key, -9999) > self.now_min - 120:
            return False
        self.st.set(key, self.now_min)
        self._audit(wid, "incident", f"hallucination spike on {inc['current']}: flag rate {inc['rate']:.1%} vs baseline {inc['baseline_rate']:.1%} "
                    f"({inc['flags']}/{inc['n']} connected calls, z={inc['z']})", inc)
        gov = self.wfs[wid]["governance"]
        need = gov.get("min_validation_pass_rate", 0.97)
        options = self.wfs[wid]["options"]["prompt_version"]
        cands = [p for p in inc["known_good"] if p in options and p != cfg["prompt_version"]]
        tried = []
        for attempt in range(2):
            if not cands:
                if self.credits < 3 + RESERVE_CREDITS:
                    break
                if not self._allow_spend(wid, "suggest-fixes"):
                    break
                r = self.api.post("/llm/suggest-fixes", {"workflow_id": wid, "problem":
                                  f"hallucination flag rate {inc['rate']:.1%} on prompt {inc['current']} (baseline {inc['baseline_rate']:.1%})"})
                self.credits = r["credits_remaining"]
                cands = [s["prompt_version"] for s in r["suggestions"]]
                self._audit(wid, "llm_suggest", f"suggest-fixes returned {cands}", r)
            for c in cands:
                verdict, qd = P.prompt_candidate_check(self._prompt_stats(wid), c, cfg["prompt_version"])
                if verdict == "reject":             # before spending credits: engagement / flow-adherence guardrail on the fix itself
                    self._audit(wid, "candidate_rejected", f"{c}: {qd['reason']} (engagement {qd['cand_engagement']:.3f} vs {qd['best_other_engagement']:.3f}, "
                                f"adherence {qd['cand_adherence']:.3f} vs {qd['other_adherence']:.3f})", qd)
                    continue
                if self.credits < VALIDATION_N / 100 + RESERVE_CREDITS:
                    break
                if not self._allow_spend(wid, "validation"):
                    break
                v = self.api.post("/validation/runs", {"workflow_id": wid, "prompt_version": c, "n": VALIDATION_N})
                self.credits = v["credits_remaining"]
                tried.append({"prompt": c, "run": v["validation_run_id"], "pass_rate": v["pass_rate"]})
                self._audit(wid, "validation", f"{c}: pass_rate {v['pass_rate']} (need >= {need}) run {v['validation_run_id']}", v)
                if v["pass_rate"] >= need + 0.005:
                    tgt = copy.deepcopy(cfg)
                    tgt["prompt_version"] = c
                    ok = self.submit(wid, "prompt_fix", tgt, f"Revert prompt {inc['current']} -> {c} (hallucination spike)",
                                     f"Hallucination flag rate on {inc['current']} is {inc['rate']:.1%} vs {inc['baseline_rate']:.1%} on {c} "
                                     f"(z={inc['z']}, n={inc['n']}). {c} passed validation {v['validation_run_id']} with pass_rate {v['pass_rate']}.",
                                     {"before": {inc["current"]: inc["rate"]}, "validated": tried, "quality_check": {"verdict": verdict, **qd},
                                      "note": "expected flag rate falls to baseline" + ("" if verdict == "ok" else "; engagement/adherence of this prompt unverified (no history) - post-apply check will run")},
                                     impact=min(1.0, 0.5 + (inc["rate"] - inc["baseline_rate"]) * 8),
                                     evidence={"validation_run_id": v["validation_run_id"]}, urgent=True,
                                     affected=int(self.wfs[wid]["daily_batch"]["size"] * 3))
                    return ok
            cands = []
        self._audit(wid, "blocked", "could not find a validated replacement prompt (credits or pass-rate)", {"tried": tried})
        return False

    def _allow_spend(self, wid, what) -> bool:
        """Token bucket per workflow on credit-spending calls; denied calls are audited, not silently dropped."""
        if self.limiter.take(wid, self.now_min):
            return True
        self.metrics.inc("rate_limited_total", what=what)
        self._audit(wid, "rate_limited", f"{what} skipped: per-workflow credit-spend budget exhausted", {"what": what})
        return False

    def verify_prompt_fixes(self, wid, cfg):
        for p in self.st.proposals(wid, ("applied", "applied_auto")):
            m = p.get("meta") or {}
            if p["kind"] != "prompt_fix" or m.get("verified") or not m.get("applied_min"):
                continue
            if self.now_min < m["applied_min"] + 180:
                continue
            rows = self.st.window(wid, self.now_hr, 3, "prm|")
            r = rows.get("prm|" + cfg["prompt_version"])
            if r is None or r[1] < 80:
                continue
            rate = float(r[3] / r[1])
            self._verify_quality(wid, cfg["prompt_version"], p["proposal_id"])
            m["verified"] = True
            self.st.put_proposal({**p, "meta": m})
            self._audit(wid, "verified", f"after fix, flag rate on {cfg['prompt_version']} is {rate:.1%} over {int(r[1])} calls "
                        f"({'resolved' if rate < 0.02 else 'STILL HIGH'})", {"proposal_id": p["proposal_id"], "rate": rate})

    def _verify_quality(self, wid, prompt, pid):
        """After a prompt fix: engagement and flow adherence on the new prompt (last 3 h) vs the other known prompts."""
        stats = self._prompt_stats(wid)
        others = [v for k, v in stats.items() if k != prompt and v["conn"] >= 300]
        e = self.st.window(wid, self.now_hr, 3, "eng|voice|")
        cn = sum(r[1] for k, r in e.items() if k.endswith("|" + prompt)); ck = sum(r[2] for k, r in e.items() if k.endswith("|" + prompt))
        fl = self.st.window(wid, self.now_hr, 3, "fla|" + prompt)
        fn = sum(r[0] for r in fl.values()); fs = sum(r[1] for r in fl.values())
        if not others or cn < 80 or fn < 80:
            return
        ref_n = sum(v["conn"] for v in others); ref_k = sum(v["eng"] for v in others)
        res = P.guardrail_status(ref_n, ref_k, cn, ck, 0.03, min_n=80)
        ref_adh = sum(v["fla_sum"] for v in others) / max(sum(v["fla_n"] for v in others), 1)
        adh = fs / fn
        bad = res["state"] == "breach" or abs(adh - ref_adh) > 0.05
        self._audit(wid, "quality_regression" if bad else "quality_ok",
                    f"after fix to {prompt}: engagement {ck / cn:.3f} vs {ref_k / ref_n:.3f} on other prompts, flow adherence {adh:.3f} vs {ref_adh:.3f}"
                    + (" - REGRESSION: review/revert the prompt" if bad else ""), {"proposal_id": pid, "engagement": res, "adherence": [round(adh, 4), round(ref_adh, 4)]})
        if bad:
            self.alerts.fire(f"quality:{wid}", f"{wid}: prompt {prompt} after the fix has worse engagement/flow adherence than known prompts", wf=wid)

    # ---- caller ID ----------------------------------------------------------------------------
    def plan_did(self, wid, cfg, guard=None):
        """Returns (alloc, stats, urgent) or None. Dead-band + cooldown keep us from churning config versions, which
        would also invalidate our own pending approvals (stale_base_version)."""
        last = self.st.get(f"did_last|{wid}", -9999)
        if self.now_min < last + 60:
            return None
        pending = bool(self.st.proposals(wid, ("pending_approval", "sending")))
        rows = self.st.window(wid, self.now_hr, 12, "did|", halflife=6)
        seen = self.st.alltime(wid, "did|")
        res = P.did_target(rows, self.wfs[wid]["options"]["caller_id"], prior_n=80, seen=seen)
        if not res:
            return None
        alloc, stats = res
        cur = cfg["allocations"]["default"]["caller_id"]
        best = max(s["shrunk"] for s in stats.values())
        # urgent = a number carrying real traffic that is clearly worse than the best one (spam-flagged / degraded)
        urgent = any(share >= 0.10 and stats[d]["shrunk"] < 0.75 * best for d, share in cur.items() if d in stats)
        shift = P.tv(cur, alloc)
        if shift < (0.08 if urgent else 0.15):
            return None
        if not urgent and (pending or self.now_min < last + 240):
            return None
        # evidence gate: a rebalance must be better with high probability, not merely different. Deliberate exploration of a
        # genuinely unseen number (capped at 15%) and urgent drains of a degraded number are exempt.
        tight = bool(guard) and guard["state"] in ("hold", "breach") and "caller_id" in guard["affects"]
        if tight and guard["state"] == "breach" and not urgent:
            return None                             # guardrail breached: only urgent drains of a degraded ID may move pickup
        exploring = (not tight) and any(stats[d].get("unexplored") and alloc.get(d, 0) > cur.get(d, 0) + 0.02 for d in alloc)
        if not urgent and not exploring:
            pi = P.did_improve_prob(rows, self.wfs[wid]["options"]["caller_id"], cur, alloc, prior_n=80, seed=self.now_min)
            if pi < (TIGHT_PIMPROVE if tight else DID_MIN_PIMPROVE):
                self.metrics.inc("changes_suppressed_total", kind="caller_id")
                if self.st.get(f"sup_did|{wid}", -9999) < self.now_min - 240:   # at most one audit row per 4h
                    self.st.set(f"sup_did|{wid}", self.now_min)
                    self._audit(wid, "suppressed", f"caller-ID rebalance not applied: P(better than live) = {pi:.2f} < {DID_MIN_PIMPROVE}",
                                {"p_improve": round(pi, 3), "target": alloc, "stats": stats})
                return None
            for s_ in stats.values():
                s_["p_improve"] = round(pi, 3)
        return alloc, stats, urgent

    # ---- experiments --------------------------------------------------------------------------
    def exp_due(self, wid) -> bool:
        if self.now_min < self.st.get(f"next_exp|{wid}", 0):
            return False
        if self.st.proposals(wid, ("pending_approval", "sending")):
            return False
        if self.auto_ok(wid, ["voice", "welcome_message"]):
            return True
        a, b = self.wfs[wid]["governance"]["approver_hours"]
        hour = (self.now_min // 60) % 24
        return a <= hour < b - 1

    def plan_exp(self, wid, cfg, guard=None):
        obj = self.wfs[wid]["objective"]
        w = self.wfs[wid]
        rows = self.st.window(wid, self.now_hr, 96, "eng|", halflife=24)
        if not rows:
            return None
        cells = set()
        for k in rows:
            _, _, _, age, lang, _ = k.split("|")
            cells.add((age, lang))
        ours = all(c["id"].startswith("c_") for c in cfg["cohorts"])
        groups = P.make_groups(cells) if ours else {}
        alloc, means, volume, post = P.engage_targets(rows, groups, w["options"], cfg["prompt_version"], seed=self.now_min)
        tgt = copy.deepcopy(cfg)
        if ours and groups:
            tgt["cohorts"] = [{"id": g, "where": groups[g]["where"]} for g in sorted(groups)]
            for g in list(tgt["allocations"]):
                if g != "default" and g.startswith("c_") and g not in groups:
                    del tgt["allocations"][g]
        for dim in ("voice", "welcome_message"):
            tgt["allocations"]["default"][dim] = alloc[dim]["default"]
            for g in groups:
                tgt["allocations"].setdefault(g, {})[dim] = alloc[dim][g]
        if P.changed_dims(cfg, tgt) == []:
            return None
        # honest impact: relative change in expected engagement per dimension, weighted by connected volume
        lifts, big = {}, 0.0
        gl = list(groups) or ["default"]
        vol = {g: max(volume.get(g, 0.0), 1e-9) for g in gl}
        for dim in ("voice", "welcome_message"):
            old_e = new_e = 0.0
            for g in gl:
                old_e += vol[g] * P.expected_rate(P.dist(cfg, g if g in cfg["allocations"] else "default", dim), means[dim][g])
                new_e += vol[g] * P.expected_rate(alloc[dim][g], means[dim][g])
                big = max(big, P.tv(P.dist(cfg, g if g in cfg["allocations"] else "default", dim), alloc[dim][g]))
            lifts[dim] = new_e / old_e - 1 if old_e else 0.0
        lift = (1 + lifts["voice"]) * (1 + lifts["welcome_message"]) - 1
        if big < 0.10 and abs(lift) < 0.003:
            self.st.set(f"next_exp|{wid}", self.now_min + 240)
            return None
        pimp = P.exp_improve_prob(cfg, alloc, post, volume, w["options"], gl, seed=self.now_min)
        # Exploration of an option we have (almost) never observed cannot have evidence yet: allow it, bounded by max_shift stepping
        # and the 10% exploration floor. Re-weighting between options we HAVE observed must clear the evidence bar.
        unseen = P.unseen_options(rows, w["options"], cfg["prompt_version"])
        exploring = any(alloc[dim][g].get(o, 0) > P.dist(cfg, g if g in cfg["allocations"] else "default", dim).get(o, 0) + 0.02
                        for dim in unseen for g in gl for o in unseen[dim])
        tight = bool(guard) and guard["state"] in ("hold", "breach") and bool(set(guard["affects"]) & {"voice", "welcome_message"})
        if tight and guard["state"] == "breach":
            self.st.set(f"next_exp|{wid}", self.now_min + 240)
            return None                             # guardrail breached: freeze voice/welcome experimentation
        if tight:
            exploring = False
        if pimp < (TIGHT_PIMPROVE if tight else EXP_MIN_PIMPROVE) and not exploring:
            self.metrics.inc("changes_suppressed_total", kind="experiment")
            self._audit(wid, "suppressed", f"experiment not proposed: P(better than live) = {pimp:.2f} < {EXP_MIN_PIMPROVE} "
                        f"(expected lift {lift:+.2%}, max cohort shift {big:.2f})", {"p_improve": round(pimp, 3), "lift": round(lift, 4), "max_shift": round(big, 3)})
            self.st.set(f"next_exp|{wid}", self.now_min + 240)
            return None
        sel = sum(1 for g in gl if g in cfg["allocations"])
        leads = [v for v in self.ing.leads.values() if v[0] >= self.ing.max_day - 2]
        affected = len(leads)
        dry = {"method": "replay against last 96h of connected calls (half-life 24h), posterior means per cohort x option",
               "expected_engagement_lift": {k: round(v, 4) for k, v in lifts.items()}, "combined": round(lift, 4),
               "max_cohort_tv_shift": round(big, 3), "p_improve": round(pimp, 3), "exploring_unseen": exploring, "cohorts": len(groups),
               "connected_calls_used": int(sum(volume.values()) / max(len(gl), 1)) if volume else 0,
               "note": "exploration share kept at >=10% so decay of a winner is detectable"}
        return {"target": tgt, "summary": f"Cohort-aware voice/welcome allocation for {wid} ({len(groups) or 1} cohorts)",
                "rationale": f"Thompson sampling on engagement-given-connected per cohort x option under prompt {cfg['prompt_version']}; "
                             f"expected engagement lift ~{lift:+.1%} (primary KPI: {obj['primary']}); pickup unaffected by voice/welcome.",
                "dry_run": dry, "impact": max(0.05, min(1.0, abs(lift) * 15)), "affected": affected}

    # ------------------------------------------------------------------ governance client
    def auto_ok(self, wid, dims) -> bool:
        aa = self.wfs[wid]["governance"]["auto_apply"]
        return bool(aa.get("enabled")) and set(dims) <= set(aa.get("allowed_dims", []))

    @staticmethod
    def _strip_cohort_dim(cfg, dim):
        for k, v in cfg["allocations"].items():
            if k != "default":
                v.pop(dim, None)

    def submit(self, wid, kind, target, summary, rationale, dry_run, impact, evidence=None, urgent=False, affected=None) -> bool:
        cur = self.api.get(f"/workflows/{wid}/config")
        ver, cfg = cur["version"], cur["config"]
        dims = P.changed_dims(cfg, target)
        if not dims:
            return False
        gov = self.wfs[wid]["governance"]
        aa = gov["auto_apply"]
        stepped = False
        t2 = P.step_toward(cfg, target, aa["max_shift"]) if aa.get("enabled") else target
        sdims = P.changed_dims(cfg, t2, strict=True)
        if aa.get("enabled") and sdims and set(sdims) <= set(aa.get("allowed_dims", [])):
            stepped = t2 is not target
            tgt = t2
            pid = self._pid(wid, ver, tgt, kind)
            body = {"proposal_id": pid, "base_version": ver, "proposed_config": tgt,
                    "rationale": rationale + (" (stepped toward target to respect max_shift)" if stepped else ""), "evidence": evidence}
            self.st.put_proposal({"proposal_id": pid, "wf": wid, "kind": kind, "status": "sending", "base_version": ver,
                                  "created_min": self.now_min, "dims": dims, "config": tgt,
                                  "meta": {"summary": summary, "route": "auto", "stepped": stepped}})
            try:
                r = self.api.put(f"/workflows/{wid}/config", body)
            except ApiError as e:
                if e.code == "duplicate_proposal_id":  # idempotent retry: an earlier send already landed
                    hit = self._landed({"wf": wid, "proposal_id": pid})
                    if hit:
                        self.st.set_status(pid, hit[0], hit[1])
                        self._audit(wid, "recovered", f"{pid}: duplicate send; already {hit[0]} at simulator", {})
                        return True
                self.st.set_status(pid, "failed")
                self._audit(wid, "auto_apply_refused", f"{e.status} {e.code}: {e.body}", {"proposal_id": pid, "dims": dims})
                if e.code == "stale_base_version":
                    return False
                aa = {"enabled": False}
            else:
                self.st.set_status(pid, "applied_auto")
                self._mark_applied(pid, r["version"])
                if kind == "caller_id" or kind == "batch":
                    self.st.set(f"did_last|{wid}", self.now_min)
                self._audit(wid, "applied", f"auto-applied v{r['version']} ({kind}): {summary}",
                            {"proposal_id": pid, "dims": dims, "stepped": stepped, "rationale": rationale, "dry_run": dry_run,
                             "evidence": evidence, "base_version": ver})
                self.log("auto-applied", wf=wid, version=r["version"], kind=kind, dims=dims, stepped=stepped, proposal_id=pid)
                return True
        # approval path
        if self.st.proposals(wid, ("pending_approval", "sending")):
            return False
        used = self.st.requests_in_last_24h(wid, self.now_min)
        cap = gov["max_requests_per_24h"] - (0 if urgent else 1)  # keep one request in reserve for incidents
        if used >= cap:
            recent = [p["created_min"] for p in self.st.proposals(wid) if p.get("approval_id") and p["created_min"] > self.now_min - 1440]
            retry = (min(recent) + 1440 + 15) if recent else self.now_min + 180
            if self.st.get(f"defer|{wid}") != retry:
                self.st.set(f"defer|{wid}", retry)
                self._audit(wid, "deferred", f"approval budget {used}/{gov['max_requests_per_24h']} in 24h (1 kept for incidents); "
                            f"will batch and retry at {label(retry)}", {"kind": kind, "retry_min": retry})
            self.st.set(f"next_exp|{wid}", retry)
            return False
        pid = self._pid(wid, ver, target, kind)
        self.st.put_proposal({"proposal_id": pid, "wf": wid, "kind": kind, "status": "sending", "base_version": ver,
                              "created_min": self.now_min, "dims": dims, "config": target,
                              "meta": {"summary": summary, "route": "approval"}})
        body = {"proposal_id": pid, "workflow_id": wid, "base_version": ver, "proposed_config": target,
                "change_summary": summary[:200], "diff": self._diff(cfg, target, dims), "affected_leads": int(affected or 0),
                "dry_run": dry_run or {"note": "n/a"}, "impact_score": round(float(impact), 3), "rationale": rationale}
        if evidence:
            body["evidence"] = evidence
        try:
            a = self.api.post("/approvals", body)
        except ApiError as e:
            if e.code == "duplicate_proposal_id":  # idempotent retry: an earlier send already landed
                hit = self._landed({"wf": wid, "proposal_id": pid})
                if hit:
                    self.st.set_status(pid, hit[0], hit[1])
                    self._audit(wid, "recovered", f"{pid}: duplicate send; already {hit[0]} at simulator", {})
                    return True
            self.st.set_status(pid, "failed")
            self._audit(wid, "proposal_refused", f"{e.status} {e.code}: {e.body}", {"proposal_id": pid})
            return False
        self.st.set_status(pid, "pending_approval", a["approval_id"])
        self._audit(wid, "proposed", f"{a['approval_id']} ({kind}): {summary}",
                    {"proposal_id": pid, "approval_id": a["approval_id"], "dims": dims, "rationale": rationale, "dry_run": dry_run,
                     "impact_score": impact, "affected_leads": affected, "evidence": evidence, "base_version": ver})
        self.log("proposed", wf=wid, approval_id=a["approval_id"], kind=kind, dims=dims, proposal_id=pid)
        return True

    @staticmethod
    def _pid(wid, ver, cfg, kind):
        h = hashlib.sha1(json.dumps(cfg, sort_keys=True).encode()).hexdigest()[:10]
        return f"ctl-{wid}-v{ver}-{kind}-{h}"

    @staticmethod
    def _diff(old, new, dims):
        d = {"changed_dims": dims}
        if "cohorts" in dims:
            d["cohorts_after"] = [c["id"] for c in new["cohorts"]]
        for dim in ("voice", "welcome_message", "caller_id"):
            if dim in dims:
                d[dim] = {"default": {"from": old["allocations"]["default"][dim], "to": new["allocations"]["default"][dim]}}
        if "prompt_version" in dims:
            d["prompt_version"] = {"from": old["prompt_version"], "to": new["prompt_version"]}
        return d

    def _mark_applied(self, pid, version):
        for p in self.st.proposals():
            if p["proposal_id"] == pid:
                m = p.get("meta") or {}
                m.update({"applied_min": self.now_min, "applied_version": version})
                self.st.put_proposal({**p, "meta": m})

    def poll(self):
        for p in self.st.proposals(statuses=("pending_approval",)):
            wid = p["wf"]
            a = self.api.get(f"/approvals/{p['approval_id']}")
            s = a["status"]
            if s == "approved":
                try:
                    r = self.api.post(f"/workflows/{wid}/apply", {"approval_id": p["approval_id"]})
                except ApiError as e:
                    self.st.set_status(p["proposal_id"], "stale" if e.code == "stale_base_version" else "lapsed")
                    self._audit(wid, "apply_failed", f"{p['approval_id']}: {e.status} {e.code} - will re-plan from the current config",
                                {"proposal_id": p["proposal_id"], "body": e.body})
                    self.st.set(f"next_exp|{wid}", self.now_min)
                    self.st.set(f"did_last|{wid}", -9999)
                    continue
                self.st.set_status(p["proposal_id"], "applied")
                self._mark_applied(p["proposal_id"], r["version"])
                if p["kind"] in ("caller_id", "batch"):
                    self.st.set(f"did_last|{wid}", self.now_min)
                self._audit(wid, "applied", f"{p['approval_id']} applied as v{r['version']} ({p['kind']})",
                            {"proposal_id": p["proposal_id"], "dims": p["dims"], "approval": a})
                self.log("applied", wf=wid, approval_id=p["approval_id"], version=r["version"], proposal_id=p["proposal_id"])
            elif s in ("rejected", "expired", "lapsed"):
                self.st.set_status(p["proposal_id"], s)
                self._audit(wid, s, f"{p['approval_id']} {s}: {a.get('reasons')}", {"proposal_id": p["proposal_id"], "approval": a})
                self.st.set(f"next_exp|{wid}", self.now_min + 360)
            elif s == "applied":
                self.st.set_status(p["proposal_id"], "applied")

    # ------------------------------------------------------------------ main loop
    def _install_signals(self):
        """First SIGINT/SIGTERM: finish the current tick, then exit. Second one: default behaviour (hard stop)."""
        if threading.current_thread() is not threading.main_thread():
            return

        def handler(signum, _frame):
            self.log("shutdown requested; finishing current tick", "warning", signal=signal.Signals(signum).name)
            self._stop.set()
            signal.signal(signal.SIGINT, signal.default_int_handler)
            signal.signal(signal.SIGTERM, signal.SIG_DFL)
        signal.signal(signal.SIGINT, handler)
        signal.signal(signal.SIGTERM, handler)

    def run(self):
        self._install_signals()
        port = int(os.environ.get("CTRL_HTTP_PORT", "9100"))
        srv = None
        if port:
            try:
                srv = serve(port, self.metrics, self.health)
                self.log("http endpoints up", port=port, paths=["/healthz", "/readyz", "/metrics"])
            except OSError as e:
                self.log("could not start http endpoints", "warning", port=port, error=str(e))
        try:
            self._run()
        finally:
            if srv:
                srv.shutdown()

    def _run(self):
        self.startup()
        self._prune()
        self.last_tick_wall = time.time()
        tick = self.st.get("tick", 0)
        while not self._stop.is_set():
            self.tick_no = tick
            with self.tracer.span("tick", tick=tick):
                t0 = time.time()
                try:
                    if self.st.proposals(statuses=("sending",)):   # a send was interrupted by an outage: resolve it first
                        with self.tracer.span("reconcile"):
                            self.reconcile()
                    state = self.api.get("/sim/state")
                    self._time(state)
                    with self.tracer.span("ingest"):
                        n = self.ingest_new()
                    t1 = time.time()
                    with self.tracer.span("decide_all"):
                        self.decide_all()
                    t2 = time.time()
                except ConnectionError as e:            # incl. BreakerOpen: fail fast, do not advance the sim, state stays consistent
                    self.log("simulator unavailable; skipping tick", "warning", error=str(e))
                    self._gauges()
                    self._stop.wait(5)
                    continue
                self.st.metric(tick, state["ts"], n, (t1 - t0) * 1000, (t2 - t1) * 1000, self.credits)
                self.metrics.observe("tick_seconds", t2 - t0)
                self.metrics.inc("ticks_total")
                self.last_tick_wall = time.time()
                if tick % 96 == 0:
                    self.log("tick", tick=tick, events=n, ingest_ms=round(1000 * (t1 - t0)), decide_ms=round(1000 * (t2 - t1)), credits=self.credits)
                    self._prune()
                if state["finished"]:
                    break
                self.api.post("/sim/advance", {"minutes": state["tick_minutes"]})
                tick += 1
                self.tick_no = tick
                self.st.set("tick", tick)
                self._gauges()
        self.log("controller stopped" if self._stop.is_set() else "scenario finished", db=self.st.path, tick=tick)
