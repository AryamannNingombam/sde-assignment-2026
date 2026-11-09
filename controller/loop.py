"""The always-on loop. One iteration = ingest everything new, reconcile governance, decide, advance 15 sim-minutes.

Restart contract: all durable state lives in SQLite (cursors, aggregates, proposals, per-workflow learning state,
incidents). On start we (1) re-ingest any chunk after the stored cursor, (2) reconcile every non-terminal proposal
against GET /approvals and the config history, (3) carry on. Nothing is decided from in-memory-only state.
"""
from __future__ import annotations

import copy
import json
import os
import time

from .common import CUSTOMER_DIMS, MIN_PER_DAY, fmt_minute
from .governance import Gov
from .incidents import Incidents
from .ingest import Ingestor
from .learn import Learn
from .planner import HOLD_AFTER_SUPERVISOR_EDIT_DAYS, Planner, norm, tv
from .simclient import Sim
from .store import Store

TICK = 15
CALLER_COOLDOWN_MIN = 180


def log(*a):
    print(*a, flush=True)


class Controller:
    def __init__(self, url: str, db_path: str):
        self.sim = Sim(url)
        self.s = Store(db_path)
        self.ing = Ingestor(self.s)
        self.learn = Learn(self.s, self.ing)
        self.pl = Planner(self.s, self.ing, self.learn)
        self.gov = Gov(self.s, self.sim, on_applied=self.on_applied)
        self.inc = Incidents(self.s, self.sim, self.learn, self.gov)
        self.specs: dict[str, dict] = {}
        self.cfg_cache: dict[str, tuple[int, dict]] = {}
        self.credits = 0.0
        self.crash_tick = int(os.environ.get("CRASH_AT_TICK", "0") or 0)   # test hook: hard exit mid-run
        self.ticks_done = 0
        self.t_ingest = 0.0

    # ================================================================== bootstrap + ingestion
    def bootstrap(self):
        for w in self.sim.workflows():
            self.specs[w["workflow_id"]] = w
        self.catch_up()

    def catch_up(self):
        t0 = time.time()
        for kind in ("history", "events"):
            cur = self.s.kv_get(f"cursor_{kind}", -1)
            for ch in self.sim.chunks(kind, after=cur):
                self.ing.ingest(self.sim.chunk_text(ch["chunk"]), kind, ch["chunk"])
        self.t_ingest += time.time() - t0

    def config(self, wf, version):
        c = self.cfg_cache.get(wf)
        if c and c[0] == version:
            return c[1]
        r = self.sim.config(wf)
        self.cfg_cache[wf] = (r["version"], r["config"])
        return r["config"]

    # ================================================================== state patches (applied-only evidence)
    def on_applied(self, wf, pid, now):
        row = self.s.q1("SELECT state_patch, decision_id, applied_version, kind FROM proposal WHERE proposal_id=?", (pid,))
        patch = json.loads(row[0] or "{}")
        day = now // MIN_PER_DAY
        st = self.s.state(wf)
        if patch.get("v") and "v" in st:
            for dim, vs in patch["v"].items():
                for pr in vs["promoted"].values():
                    if pr["day"] == -1:
                        pr["day"] = day
                st["v"][dim] = vs
        for dim in patch.get("epoch_reset", []):
            st["epoch"][dim] = day
        if "cohort_ids" in patch:
            st["our_cohort_ids"] = patch["cohort_ids"]
        if patch.get("caller"):
            st["last_caller_min"] = now
        st["applied_any"] = True
        self.s.save_state(wf, st)
        self.cfg_cache.pop(wf, None)
        self.s.decision(now, wf, "applied", f"{pid} applied as v{row[2]} ({row[3]})",
                        outputs={"version": row[2]}, proposal_id=pid)

    # ================================================================== supervisor edits
    def handle_supervisor_edits(self, spec, now, live_cfg, st):
        wf = spec["workflow_id"]
        rows = self.s.q("SELECT event_id, minute, version, dims FROM cfgchg WHERE wf=? AND actor='supervisor' "
                        "AND handled=0 ORDER BY event_id", (wf,))
        today = now // MIN_PER_DAY
        for eid, minute, ver, dims in rows:
            dims = json.loads(dims)
            adopted = []
            for dim in dims:
                st.setdefault("hold", {})[dim] = today + HOLD_AFTER_SUPERVISOR_EDIT_DAYS
            for dim in dims:
                if dim in CUSTOMER_DIMS and "control" in st:
                    d = live_cfg["allocations"]["default"][dim]
                    st["control"][dim] = max(d, key=d.get)
                    old = st["v"][dim]
                    st["v"][dim] = self.pl.fresh_dim_state(spec, dim, st["control"][dim])
                    # keep what we learned about arms that are clearly bad, and restart exploration gently: the client
                    # just told us what they want as the default.
                    st["v"][dim]["prunes"] = {o: lv for o, lv in old["prunes"].items()
                                              if o != st["control"][dim] and "all=all" in lv}
                    st["v"][dim]["explore_ctrl"] = max(st["v"][dim]["explore_ctrl"], 0.70)
                    st["epoch"][dim] = 10 ** 6
                    adopted.append(f"{dim}: control := {st['control'][dim]} (supervisor's default)")
            self.s.decision(minute, wf, "supervisor_edit",
                            f"supervisor changed {dims} at {fmt_minute(minute)} (config v{ver}). Not reverted. "
                            f"Hold on these dims until D{today + HOLD_AFTER_SUPERVISOR_EDIT_DAYS}; "
                            f"{adopted or 'no learning reset'}; outstanding approvals based on the old version "
                            f"go stale and are re-planned from fresh data.",
                            inputs={"dims": dims, "version": ver}, outputs={"adopted": adopted})
            self.s.x("UPDATE cfgchg SET handled=1 WHERE event_id=?", (eid,))
            self.s.alert(now, wf, "info", "supervisor_edit", f"supervisor edited {dims}; adopted as the new baseline")

    # ================================================================== Track A: operational levers
    @staticmethod
    def auto_ok(spec, dim):
        a = spec["governance"]["auto_apply"]
        return bool(a.get("enabled")) and dim in a.get("allowed_dims", [])

    def track_a(self, spec, now, live_cfg, version, st):
        wf = spec["workflow_id"]
        today = now // MIN_PER_DAY
        if self.gov.outstanding(wf):
            return
        hold = st.get("hold", {})
        new = copy.deepcopy(live_cfg)
        dims, notes, decision_inputs = [], [], {}
        # ---- caller ID (auto-apply only where the policy permits; otherwise it rides in the daily request)
        if self.auto_ok(spec, "caller_id") and hold.get("caller_id", -1) < today:
            ms = spec["governance"]["auto_apply"].get("max_shift")
            res = self.pl.caller_target(spec, live_cfg, now, ms, st.get("bad_dids"))
            if res:
                dist, info = res
                if info["bad"] != st.get("bad_dids", {}):
                    st["bad_dids"] = info["bad"]
                    self.s.save_state(wf, st)
                    self.s.alert(now, wf, "info", "caller_id_degraded",
                                 f"{wf}: caller IDs held at the floor until they recover: {sorted(info['bad'])}")
                cool = CALLER_COOLDOWN_MIN if not info["severe"] else 60
                if info["tv"] >= 0.03 and now - st.get("last_caller_min", -10 ** 9) >= cool:
                    new["allocations"]["default"]["caller_id"] = dist
                    dims.append("caller_id")
                    notes.append(f"caller_id {info['before']} -> {dist} (pickup ratio to mean: {info['ratio_to_mean']})")
                    decision_inputs["caller_id"] = info
        # ---- per-person preferred hour, once per day after the daily batch has been ingested
        at = spec["daily_batch"]["at_hour"] * 60 + 15
        if self.auto_ok(spec, "schedule") and hold.get("schedule", -1) < today and (now % MIN_PER_DAY) >= at \
                and not self.s.q1("SELECT 1 FROM plan_log WHERE wf=? AND day=? AND slot='prefs'", (wf, today)):
            res = self.pl.prefs_target(spec, live_cfg, today)
            self.s.x("INSERT OR IGNORE INTO plan_log VALUES(?,?,?,?)", (wf, today, "prefs", now))
            if res:
                prefs, info = res
                if info["changed_entries"] >= 20 and info["expected_pickup_rel_gain"] > 0.01:
                    new["schedule"]["lead_preferred_hour"] = prefs
                    dims.append("schedule")
                    notes.append(f"preferred hour for {info['persons']} active leads (model-expected pickup "
                                 f"{info['expected_pickup_rel_gain']:+.1%})")
                    decision_inputs["schedule"] = info
        if not dims:
            return
        did = self.s.decision(now, wf, "auto_apply_plan", "; ".join(notes), inputs=decision_inputs,
                              outputs={"dims": dims})
        self.gov.submit_auto(spec, now, new, version, rationale="; ".join(notes), evidence=decision_inputs,
                             state_patch={"caller": "caller_id" in dims}, decision_id=did, dims=dims)
        last = self.s.q1("SELECT proposal_id FROM proposal WHERE wf=? ORDER BY rowid DESC LIMIT 1", (wf,))
        self.s.x("UPDATE decision SET proposal_id=? WHERE id=?", (last[0], did))
        self.cfg_cache.pop(wf, None)

    # ================================================================== daily plan: the approval bundle
    def plan(self, spec, now, live_cfg, version, st, urgent=False):
        wf = spec["workflow_id"]
        today = now // MIN_PER_DAY
        slot = "urgent" if urgent else "plan"
        if self.s.q1("SELECT 1 FROM plan_log WHERE wf=? AND day=? AND slot=?", (wf, today, slot)):
            return
        if self.gov.outstanding(wf) or not self.gov.window_ok(spec, now):
            return
        if self.gov.request_budget(spec, now, urgent=urgent) <= 0:
            return
        self.s.x("INSERT OR IGNORE INTO plan_log VALUES(?,?,?,?)", (wf, today, slot, now))
        pl = self.pl
        hold = st.get("hold", {})
        guard = pl.guardrail(spec, today)
        frozen = guard["breach"]
        if frozen:
            self.s.alert(now, wf, "warn", "guardrail_breach",
                         f"{wf}: guardrail {guard['metric']} dropped {guard['drop']:.3f} "
                         f"(allowed {guard['allowed_drop']}); exploration frozen")
        new_v = copy.deepcopy(st["v"])
        decisions, tests_by_dim, reverts = [], {}, []
        stx = {**st, "v": new_v}
        for dim in CUSTOMER_DIMS:
            if hold.get(dim, -1) >= today:
                continue
            new_v[dim]["blocked"] = {k: e for k, e in new_v[dim]["blocked"].items() if e > today}
            blocked = set(new_v[dim]["blocked"])
            for ev in pl.check_decay(spec, dim, stx, today):
                opt = pl.revert_level(stx, dim, ev["level"], today)
                reverts.append({"dim": dim, **ev})
                decisions.append({"action": "decay_rollback", "dim": dim, "level": ev["level"], "option": opt,
                                  "evidence": ev})
            tests = pl.analyse_dim(spec, dim, stx, today) if st["epoch"][dim] <= today else []
            tests_by_dim[dim] = tests
            vs, dec = pl.decide_dim(spec, dim, stx, today, tests, blocked)
            new_v[dim] = vs
            decisions += dec
        foreign = bool(live_cfg["cohorts"]) and \
            {c["id"] for c in live_cfg["cohorts"]} != set(st.get("our_cohort_ids", []))
        cfg, cohort_ids = pl.build_variant_config(spec, live_cfg, stx, frozen, foreign)
        # ---- operational levers that cannot be auto-applied for this workflow ride in the same request
        extra = []
        caller_info = prefs_info = None
        if not self.auto_ok(spec, "caller_id") and hold.get("caller_id", -1) < today:
            res = pl.caller_target(spec, cfg, now, None, st.get("bad_dids"))
            if res and res[1]["tv"] >= 0.05:
                cfg["allocations"]["default"]["caller_id"] = res[0]
                caller_info = res[1]
                extra.append("caller_id")
        if not self.auto_ok(spec, "schedule") and hold.get("schedule", -1) < today:
            res = pl.prefs_target(spec, cfg, today)
            if res and res[1]["changed_entries"] >= 50 and res[1]["expected_pickup_rel_gain"] > 0.01:
                cfg["schedule"]["lead_preferred_hour"] = res[0]
                prefs_info = res[1]
                extra.append("schedule")
        material, changes = self.material(live_cfg, cfg)
        if not material:
            top = sorted([t for d in tests_by_dim.values() for t in d], key=lambda t: -abs(t["z"]))[:6]
            self.s.decision(now, wf, "plan_no_change", "looked at fresh data; nothing clears the bar for a change",
                            inputs={"top_tests": top, "guardrail": guard, "decisions": decisions})
            return
        # ---- package the proposal (C10): every number comes from logged data
        levels, vgain = pl.variant_dry_run(spec, st, new_v, today, tests_by_dim)
        started = [d for d in CUSTOMER_DIMS if st["epoch"][d] > today and hold.get(d, -1) < today
                   and tv(live_cfg["allocations"]["default"][d], cfg["allocations"]["default"][d]) >= 0.08]
        aff = pl.affected_leads(spec, today)
        primary = spec["objective"]["primary"]
        p_gain = (prefs_info or {}).get("expected_pickup_rel_gain", 0.0)
        p_base = self.learn.kpi(wf, today - 3, today).get("engagement") or 0.5
        e_gain = vgain / max(p_base, 1e-6)
        exp_gain = p_gain if primary == "pickup_rate" else e_gain + 0.3 * p_gain
        impact = max(0.03, min(1.0, exp_gain / 0.05))
        diff = {"changes": changes, "exploration_started": started,
                "decisions": [{k: v for k, v in d.items() if k != "evidence"} for d in decisions]}
        dry = {"method": "replay of logged per-slice aggregates (decay-weighted, concurrent control); no extrapolation",
               "variant_rules": levels, "expected_engagement_rel_gain": round(e_gain, 4),
               "expected_pickup_rel_gain_from_schedule": p_gain,
               "caller_id": caller_info and caller_info["after"], "guardrail": guard}
        if not levels and started:
            dry["note"] = ("exploration start: no winner is claimed and expected engagement change is ~0 by design; "
                           f"non-control arms are capped at {1 - st['v'][started[0]]['explore_ctrl']:.0%} of traffic "
                           "and are pruned automatically if they trail")
        rationale = "; ".join(self.explain(d) for d in decisions) or "; ".join(changes)
        did = self.s.decision(now, wf, "plan_proposal", "; ".join(changes), inputs={
            "tests": {d: sorted(t, key=lambda x: -abs(x["z"]))[:12] for d, t in tests_by_dim.items()},
            "guardrail": guard, "frozen": frozen, "foreign_cohorts": foreign, "reverts": reverts,
            "caller": caller_info, "prefs": prefs_info}, outputs={"decisions": decisions, "cohorts": cohort_ids})
        patch = {"v": new_v, "epoch_reset": started, "cohort_ids": cohort_ids, "caller": "caller_id" in extra}
        pid = self.gov.submit_approval(
            spec, now, cfg, version, summary="; ".join(changes)[:300], diff=diff, affected=aff, dry_run=dry,
            impact=impact, rationale=rationale or "see diff", state_patch=patch, decision_id=did,
            dims=("cohorts", "welcome_message", "voice", "caller_id", "schedule"))
        self.s.x("UPDATE decision SET proposal_id=? WHERE id=?", (pid, did))
        log(f"  [{fmt_minute(now)}] {wf}: proposal {pid} impact={impact:.2f} affected={aff}: {changes}")

    @staticmethod
    def explain(d):
        a = d["action"]
        e = d.get("evidence", {})
        if a == "promote":
            return (f"promote {d['option']} over {d['control']} on {d['dim']} for {d['feature']}={d['level']}: "
                    f"engagement {e['p_opt']:.3f} vs {e['p_ctrl']:.3f} (z={e['z']}, n={e['n_opt']}/{e['n_ctrl']}, "
                    f"BH-FDR 10%)")
        if a == "prune":
            return (f"stop serving {d['option']} on {d['dim']} for {d['slice']}: trails control "
                    f"{e['p_opt']:.3f} vs {e['p_ctrl']:.3f} (z={e['z']})")
        if a == "decay_rollback":
            return (f"roll back {d['option']} on {d['dim']} for {d['level']}: {e.get('trigger')} "
                    f"(promoted lift {e.get('lift_at_promotion')}, recent {e.get('A_recent_rel_lift')})")
        return a

    @staticmethod
    def material(live, new):
        ch = []
        for dim in CUSTOMER_DIMS + ("caller_id",):
            t = tv(live["allocations"]["default"][dim], new["allocations"]["default"][dim])
            if t >= 0.08:
                ch.append(f"default {dim}: {norm(live['allocations']['default'][dim])} -> "
                          f"{new['allocations']['default'][dim]}")
        lc = {c["id"] for c in live["cohorts"]}
        nc = {c["id"] for c in new["cohorts"]}
        if lc != nc:
            ch.append(f"cohorts {sorted(lc)} -> {sorted(nc)}")
        else:
            for cid in nc:
                for dim in CUSTOMER_DIMS:
                    a = live["allocations"].get(cid, {}).get(dim, live["allocations"]["default"][dim])
                    b = new["allocations"].get(cid, {}).get(dim, new["allocations"]["default"][dim])
                    if tv(a, b) >= 0.08:
                        ch.append(f"{cid} {dim}: {a} -> {b}")
        lp, np_ = live["schedule"].get("lead_preferred_hour", {}), new["schedule"].get("lead_preferred_hour", {})
        moved = sum(1 for k, v in np_.items() if lp.get(k) != v)
        if lp != np_ and moved >= 50:
            ch.append(f"preferred call hour for {moved} leads")
        return bool(ch), ch

    # ================================================================== one workflow, one tick
    def step(self, spec, now, version):
        wf = spec["workflow_id"]
        self.gov.reconcile(spec, now)
        live = self.config(wf, version)
        st = self.s.state(wf)
        st = self.pl.init_state(spec, live, st)
        # a reconcile above may have applied something; refresh the live config if the version moved
        cur_v = self.cfg_cache[wf][0]
        self.handle_supervisor_edits(spec, now, live, st)
        self.s.save_state(wf, st)
        self.inc.tick(spec, now, live, cur_v, self.credits, bool(self.gov.outstanding(wf)))
        self.track_a(spec, now, live, cur_v, st)
        st = self.s.state(wf)
        v2 = self.sim.config(wf) if wf not in self.cfg_cache else None
        if v2:
            self.cfg_cache[wf] = (v2["version"], v2["config"])
        live, cur_v = self.cfg_cache[wf][1], self.cfg_cache[wf][0]
        if not self.gov.outstanding(wf):
            self.plan(spec, now, live, cur_v, st)
            if now % 60 == 0 and st.get("applied_any"):
                self.plan_if_decay(spec, now, live, cur_v, st)

    def plan_if_decay(self, spec, now, live, version, st):
        today = now // MIN_PER_DAY
        for dim in CUSTOMER_DIMS:
            if st.get("hold", {}).get(dim, -1) >= today:
                continue
            if self.pl.check_decay(spec, dim, st, today):
                self.plan(spec, now, live, version, st, urgent=True)
                return

    # ================================================================== main loop
    def run(self):
        self.bootstrap()
        log("controller up; workflows:", ", ".join(self.specs))
        last_day = None
        while True:
            self.catch_up()
            s = self.sim.state()
            self.credits = s["credits_remaining"]
            now = s["sim_minute"]
            if s["finished"] or now >= s["end_minute"]:
                break
            versions = {w["workflow_id"]: w["current_version"] for w in self.sim.workflows()}
            t0 = time.time()
            for wf, spec in self.specs.items():
                self.step(spec, now, versions[wf])
            self.record_metrics(now, time.time() - t0)
            if now // MIN_PER_DAY != last_day:
                last_day = now // MIN_PER_DAY
                log(f"D{last_day} credits={self.credits} events={self.ing.events_total}")
            self.ticks_done += 1
            if self.crash_tick and self.ticks_done == self.crash_tick:
                log("CRASH_AT_TICK reached: hard exit")
                os._exit(137)
            self.sim.advance(TICK)
        self.catch_up()
        self.final_report()
        self.print_perf()
        log("scenario finished")

    def print_perf(self):
        import resource
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        rss_mb = rss / (1024 * 1024) if rss > 10 ** 7 else rss / 1024      # macOS reports bytes, Linux KiB
        t = self.s.q("SELECT v FROM metric WHERE name='decide_secs'")
        ds = sorted(x[0] for x in t) or [0]
        eps = self.ing.events_total / max(self.t_ingest, 1e-9)
        log(f"PERF events_ingested={self.ing.events_total} ingest_events_per_sec={eps:,.0f} "
            f"ingest_secs={self.t_ingest:.1f} decide_secs_per_tick_p50={ds[len(ds) // 2]:.2f} "
            f"p99={ds[int(len(ds) * 0.99) - 1]:.2f} max={ds[-1]:.2f} peak_rss_mb={rss_mb:.0f}")

    def record_metrics(self, now, decide_secs):
        self.s.x("INSERT INTO metric VALUES(?,?,?)", (now, "decide_secs", decide_secs))
        self.s.x("INSERT INTO metric VALUES(?,?,?)", (now, "credits", self.credits))
        self.s.x("INSERT INTO metric VALUES(?,?,?)", (now, "ingest_lag_min", now - self.ing.max_event_ts_min))

    def final_report(self):
        from .view import build_view
        os.makedirs("reports", exist_ok=True)
        with open("reports/supervisor_view.json", "w") as f:
            json.dump(build_view(self.s, self.specs, self.ing), f, indent=1, default=str)
