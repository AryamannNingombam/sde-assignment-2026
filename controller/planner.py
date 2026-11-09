"""Learning + planning: turns aggregates into a *desired config* and the evidence behind it.

Levers and how each is learned
------------------------------
caller_id   multiplicative-weights toward equal pickup across IDs (C5). The ID's health falls with its own load,
            so the optimum is never "all traffic on the best ID"; it is the allocation where pickup equalises.
call time   per-person preferred hour (C4), assigned from an (age x tier) hour-of-day pickup profile learned from
            history + live data, capacity-aware (an auction over hours, so no hour is overbooked).
welcome/voice
            randomised exploration inside a fixed control share; per-slice two-proportion tests on decay-weighted
            counts; Benjamini-Hochberg FDR across all slice x option tests; promotion keeps a control holdout so
            decay is measurable; losers are pruned per slice. No LLM is involved in picking winners.
"""
from __future__ import annotations

import copy
import math
from collections import defaultdict

import numpy as np

from .common import CUSTOMER_DIMS, FEATURES, person_id_of
from .learn import Learn
from .stats import benjamini_hochberg, norm_sf, two_prop

# ---- statistical knobs (see SUBMISSION.md section 5 for the reasoning and the speed/false-winner trade-off)
N_MIN = 80            # min effective connected calls per arm per slice before a test is run
P_MAX_SECONDARY = 0.004   # same, when engagement is not the workflow's primary KPI
P_MAX = 0.015          # and each discovery must also clear p<=0.01 on its own (overlapping slices inflate BH ranks)
FDR_Q = 0.10           # expected share of false discoveries among promotions
MIN_LIFT = 0.03        # practical significance: relative lift below this is not worth a customer-facing change
Z_PRUNE, Z_PRUNE_SLICE, N_PRUNE = 1.65, 2.7, 100   # slice prunes are many tests: demand more
EXPLORE_CTRL = {"engagement_rate": 0.50, "pickup_rate": 0.85}   # control share while exploring
EXPLOIT = (0.67, 0.25, 0.08)                                      # winner / control holdout / other arms
DECAY_HALF_LIFE_DAYS = 6.0   # variant tests need volume; decay is caught separately by check_decay's short windows
HOLD_AFTER_SUPERVISOR_EDIT_DAYS = 2
# Clients that asked for caution get a larger control share (memo 02, Northwind compliance: "slow and right").
TENANT_MIN_CONTROL = {"northwind_life": 0.65}


def tv(a: dict, b: dict) -> float:
    return 0.5 * sum(abs(a.get(o, 0.0) - b.get(o, 0.0)) for o in set(a) | set(b))


def norm(d: dict, nd: int = 3) -> dict:
    s = sum(d.values())
    out = {k: round(v / s, nd) for k, v in d.items() if v > 0}
    # put rounding residue on the largest entry so the weights sum to exactly 1
    big = max(out, key=out.get)
    out[big] = round(out[big] + (1 - sum(out.values())), nd)
    return out


class Planner:
    def __init__(self, store, ing, learn: Learn):
        self.s, self.ing, self.learn = store, ing, learn

    # ================================================================== helpers
    def active_idx(self, wf: str, today: int, cadence_len: int):
        P = self.ing.persons.get(wf)
        if P is None or len(P) == 0:
            return np.zeros(0, dtype=np.int64)
        plast = np.frombuffer(P.plast, dtype=np.int16)
        pconcl = np.frombuffer(P.pconcl, dtype=np.int16)
        code = np.frombuffer(P.code, dtype=np.uint16)
        m = (plast >= today - (cadence_len - 1)) & (pconcl < plast) & (code > 0)
        return np.flatnonzero(m)

    def affected_leads(self, spec, today, feature=None, levels=None) -> int:
        idx = self.active_idx(spec["workflow_id"], today, len(spec["cadence"]))
        if feature is None or not len(idx):
            return int(len(idx))
        wf = spec["workflow_id"]
        fi = FEATURES.index(feature)
        P = self.ing.persons[wf]
        codes = np.frombuffer(P.code, dtype=np.uint16)[idx]
        ck = self.ing.cell_keys[wf]
        ok = np.array([ck[c - 1][fi] in levels for c in range(1, len(ck) + 1)] + [False])
        return int(sum(ok[c - 1] for c in codes))

    @staticmethod
    def default_dist(cfg: dict, dim: str) -> dict:
        return cfg["allocations"]["default"][dim]

    # ================================================================== caller ID (C5)
    def caller_target(self, spec, live_cfg, now, max_shift=None, bad=None):
        wf = spec["workflow_id"]
        bad = dict(bad or {})
        opts = spec["options"]["caller_id"]
        x = {d: live_cfg["allocations"]["default"]["caller_id"].get(d, 0.0) for d in opts}
        stats = self.learn.did_stats(wf, now)
        tot_n = sum(v[0] for v in stats.values())
        if tot_n < 150:
            return None
        pbar0 = sum(v[1] for v in stats.values()) / tot_n
        M = 20.0
        seen = {d: stats.get(d, [0, 0, 0, 0, 0])[2] >= 30 for d in opts}      # raw dials in the last 7 days
        phat = {d: ((stats[d][1] + M * pbar0) / (stats[d][0] + M)) if d in stats else pbar0 for d in opts}
        xs = sum(x[d] for d in opts if seen[d])
        pbar = sum(x[d] * phat[d] for d in opts if seen[d]) / max(xs, 1e-9)
        # fast view: a sudden drop (spam flag) must not wait for the slow average to catch up
        fast_n = sum(v[3] for v in stats.values())
        fast_bar = sum(v[4] for v in stats.values()) / fast_n if fast_n else pbar0
        ratios, new, severe = {}, {}, False
        # ---- an ID flagged as degraded stays at the floor until a probe on POST-flag data shows it recovered.
        #      (Without this memory the slow average, still holding pre-incident data, re-promotes it and the
        #      fast signal flags it again: a flip-flop every few hours.)
        for d in list(bad):
            win = self.learn.did_window(wf, bad[d]["since"] // 60 + 1, now // 60)
            others_n = sum(v[0] for k, v in win.items() if k != d)
            others_k = sum(v[1] for k, v in win.items() if k != d)
            n_d, k_d = win.get(d, (0, 0))
            if n_d >= 150 and others_n >= 500 and (k_d / n_d) / max(others_k / others_n, 1e-9) >= 0.85:
                del bad[d]                                 # probe passed: it may earn traffic back
        for d in opts:
            if not seen[d]:
                new[d] = max(x[d], 0.08)          # never measured: a small, measurable share, nothing more
                continue
            r = phat[d] / max(pbar, 1e-9)
            n_f, k_f = stats[d][3], stats[d][4]
            if n_f >= 80 and x[d] > 0.05:
                r_fast = (k_f / n_f) / max(fast_bar, 1e-9)
                if r_fast < 0.6 and r_fast < r:
                    r, severe = r_fast, True
                    bad.setdefault(d, {"since": now})
            if r < 0.7 and stats[d][0] >= 300:
                bad.setdefault(d, {"since": now})
            ratios[d] = round(r, 3)
            if d in bad:
                new[d] = 0.02
                continue
            kappa = 1.0 if 0.75 <= r <= 1.33 else 3.0     # damp near the optimum: health responds with a 2-day lag
            new[d] = max(x[d], 0.04) * (r ** kappa)
        new = norm({d: max(v, 0.02) for d, v in new.items()})
        # health falls with an ID's own load (diminishing returns): blend with an even spread over IDs that are
        # measured and healthy. Never-measured and known-bad IDs are excluded from the even spread.
        def r_low(d):    # lower confidence bound of the ratio: a small sample must not look healthy by luck
            n = max(stats[d][0], 1.0)
            se = math.sqrt(max(phat[d] * (1 - phat[d]), 1e-6) / n)
            return (phat[d] - 1.28 * se) / max(pbar, 1e-9)
        healthy = [d for d in opts if seen[d] and d not in bad and ratios.get(d, 1.0) >= 0.8 and r_low(d) >= 0.8]
        if healthy:
            new = norm({d: 0.5 * new[d] + 0.5 * (1.0 / len(healthy) if d in healthy else 0.0) for d in opts})
            new = norm({d: (0.02 if d in bad else max(v, 0.02)) for d, v in new.items()})
        if max_shift is not None and tv(x, new) > max_shift:     # honour the policy's per-change shift limit
            t = max_shift / tv(x, new)
            new = norm({d: x[d] + t * (new[d] - x[d]) for d in opts})
        info = {"phat": {d: round(phat[d], 4) for d in opts},
                "n_eff": {d: round(stats.get(d, [0])[0]) for d in opts},
                "ratio_to_mean": ratios, "before": norm(x), "after": new, "tv": round(tv(x, new), 3),
                "severe": severe, "bad": bad}
        return new, info

    # ================================================================== call time (C4)
    def prefs_target(self, spec, live_cfg, today):
        wf = spec["workflow_id"]
        lo, hi = spec["dialling_window"]
        prof, hours = self.learn.hour_profiles(wf, today)
        if not prof:
            return None
        win = [h for h in range(lo, hi)]
        idx = self.active_idx(wf, today, len(spec["cadence"]))
        if len(idx) < 50:
            return None
        ai, ti = FEATURES.index("age_band"), FEATURES.index("city_tier")
        ck = self.ing.cell_keys[wf]
        P = self.ing.persons[wf]
        codes = np.frombuffer(P.code, dtype=np.uint16)[idx]
        H = len(win)
        cell_gain = np.zeros((len(ck) + 1, H))
        allp = np.array([prof["all"].get(h, 0.0) for h in win])
        for c, tup in enumerate(ck, start=1):
            g = prof["grp"].get((tup[ai], tup[ti])) or prof["age"].get(tup[ai])
            cell_gain[c] = [g.get(h, 0.0) for h in win] if g else allp
        G = cell_gain[codes]                                 # (persons, hours)
        spread = float((G.max(axis=1) - G.min(axis=1)).mean() / max(G.mean(), 1e-9))
        if spread < 0.15:
            return None                                       # profile is flat: nothing to gain, change nothing
        cap = spec["dials_per_hour"] * 0.9
        lam = np.zeros(H)
        scale = float(G.mean()) * 0.05
        best, best_over = None, 1e18
        for _ in range(80):
            asg = np.argmax(G - lam, axis=1)
            load = np.bincount(asg, minlength=H).astype(float)
            over = float(np.maximum(load - cap, 0).sum())
            if over < best_over:
                best, best_over = asg.copy(), over
            if over == 0:
                break
            lam += scale * (load - cap) / cap
        asg = best
        # repair pass: move the cheapest-to-move people out of any still-overbooked hour
        load = np.bincount(asg, minlength=H)
        for h in np.argsort(-(load - cap)):
            ex = int(load[h] - cap)
            if ex <= 0:
                continue
            members = np.flatnonzero(asg == h)
            regret = G[members, h] - np.where(np.arange(H)[None, :] == h, -1e9, G[members]).max(axis=1)
            for j in members[np.argsort(regret, kind="stable")][:ex]:
                alt = [(G[j, k], k) for k in range(H) if k != h and load[k] < cap]
                if alt:
                    k = max(alt)[1]
                    asg[j] = k
                    load[h] -= 1
                    load[k] += 1
        prefs = {person_id_of(wf, int(i)): int(win[a]) for i, a in zip(idx, asg)}
        cur = live_cfg["schedule"].get("lead_preferred_hour", {})
        changed = sum(1 for k, v in prefs.items() if cur.get(k) != v)
        base = float(G.mean(axis=1).sum())
        got = float(G[np.arange(len(idx)), asg].sum())
        info = {"persons": int(len(idx)), "changed_entries": changed, "profile_spread": round(spread, 3),
                "expected_pickup_rel_gain": round(got / base - 1, 4), "peak_hour_load": int(load.max()),
                "capacity_per_hour": int(cap)}
        return prefs, info

    # ================================================================== variants (C6, C7)
    @staticmethod
    def fresh_dim_state(spec, dim, ctrl):
        c = max(EXPLORE_CTRL.get(spec["objective"]["primary"], 0.55), TENANT_MIN_CONTROL.get(spec["tenant_id"], 0.0))
        return {"feature": "all", "map": {}, "promoted": {}, "prunes": {}, "blocked": {},
                "explore_ctrl": c, "strength": {}}

    def init_state(self, spec, live_cfg, st):
        if "control" in st:
            return st
        st["control"] = {}
        st["v"] = {}
        st["epoch"] = {}
        st["hold"] = {}
        for dim in CUSTOMER_DIMS:
            d = self.default_dist(live_cfg, dim)
            st["control"][dim] = max(d, key=d.get)
            st["v"][dim] = self.fresh_dim_state(spec, dim, st["control"][dim])
            st["epoch"][dim] = 10 ** 6          # no challenger exposure yet
        st["our_cohort_ids"] = []
        st["applied_any"] = False
        return st

    def dist_for(self, spec, dim, vs, ctrl, feature, level, frozen):
        """Allocation for one (dim, slice): winner+holdout, or control+unpruned challengers."""
        opts = spec["options"][dim]
        key = f"{feature}={level}"
        pruned = {o for o, lv in vs["prunes"].items() if key in lv or "all=all" in lv}
        win = vs["map"].get(level) if vs["feature"] == feature else None
        others = [o for o in opts if o != ctrl and o not in pruned]
        if win and win in opts and win != ctrl:
            rest = [o for o in others if o != win]
            d = {win: EXPLOIT[0], ctrl: EXPLOIT[1]}
            if rest and not frozen:
                for o in rest:
                    d[o] = EXPLOIT[2] / len(rest)
            return norm(d)
        if frozen or not others:
            return {ctrl: 1.0}
        c = vs["explore_ctrl"]
        d = {ctrl: c}
        for o in others:
            d[o] = (1 - c) / len(others)
        return norm(d)

    def overrides(self, spec, dim, vs, ctrl, frozen):
        """{level: dist} for slices that differ from the default (winners and per-slice prunes)."""
        levels = set(vs["map"]) if vs["feature"] != "all" else set()
        feat = vs["feature"]
        if feat == "all":
            keys = [k for lv in vs["prunes"].values() for k in lv if k != "all=all"]
            fs = {k.split("=", 1)[0] for k in keys}
            feat = sorted(fs)[0] if fs else "all"
        if feat == "all":
            return "all", {}
        for lv in vs["prunes"].values():
            for k in lv:
                f, l = k.split("=", 1)
                if f == feat:
                    levels.add(l)
        default = self.dist_for(spec, dim, vs, ctrl, "all", "all", frozen)
        out = {}
        for l in sorted(levels):
            d = self.dist_for(spec, dim, vs, ctrl, feat, l, frozen)
            if tv(d, default) > 0.02:
                out[l] = d
        return feat, out

    def build_variant_config(self, spec, live_cfg, st, frozen=False, foreign=False):
        """Full desired config for welcome/voice from the (proposed) variant state. Leaves everything else alone."""
        cfg = copy.deepcopy(live_cfg)
        defaults = {}
        feats, ovr = {}, {}
        for dim in CUSTOMER_DIMS:
            vs, ctrl = st["v"][dim], st["control"][dim]
            if vs["feature"] == "all" and vs["map"].get("all"):
                win = vs["map"]["all"]
                rest = [o for o in spec["options"][dim] if o not in (win, ctrl) and o not in
                        {o2 for o2, lv in vs["prunes"].items() if "all=all" in lv}]
                d = {win: EXPLOIT[0], ctrl: EXPLOIT[1]}
                if rest and not frozen:
                    for o in rest:
                        d[o] = EXPLOIT[2] / len(rest)
                defaults[dim] = norm(d)
            else:
                defaults[dim] = self.dist_for(spec, dim, vs, ctrl, "all", "all", frozen)
            feats[dim], ovr[dim] = self.overrides(spec, dim, vs, ctrl, frozen)
        for dim in CUSTOMER_DIMS:
            cfg["allocations"]["default"][dim] = defaults[dim]
        if foreign:
            return cfg, []
        cohorts, allocs = [], {}
        fv, fw = feats["voice"], feats["welcome_message"]
        V, W = ovr["voice"], ovr["welcome_message"]
        strength = {d: st["v"][d]["strength"] for d in CUSTOMER_DIMS}

        def trim(dim_map, other_n, key):
            levels = sorted(dim_map, key=lambda l: -strength[key].get(l, 0))
            return levels
        vl, wl = trim(V, len(W), "voice"), trim(W, len(V), "welcome_message")
        if fv != "all" and fw != "all" and fv != fw:
            while len(vl) * len(wl) + len(vl) + len(wl) > 20 and (vl or wl):
                (vl if len(vl) >= len(wl) else wl).pop()
            for a in vl:
                for b in wl:
                    cid = f"{fv}={a}&{fw}={b}"
                    cohorts.append({"id": cid, "where": {fv: [a], fw: [b]}})
                    allocs[cid] = {"voice": V[a], "welcome_message": W[b]}
            for a in vl:
                cid = f"{fv}={a}"
                cohorts.append({"id": cid, "where": {fv: [a]}})
                allocs[cid] = {"voice": V[a]}
            for b in wl:
                cid = f"{fw}={b}"
                cohorts.append({"id": cid, "where": {fw: [b]}})
                allocs[cid] = {"welcome_message": W[b]}
        else:
            for dim, feat, M in (("voice", fv, V), ("welcome_message", fw, W)):
                for l, d in M.items():
                    if feat == "all":
                        continue
                    cid = f"{feat}={l}"
                    if cid not in allocs:
                        cohorts.append({"id": cid, "where": {feat: [l]}})
                        allocs[cid] = {}
                    allocs[cid][dim] = d
            cohorts = cohorts[:20]
            allocs = {c["id"]: allocs[c["id"]] for c in cohorts}
        cfg["cohorts"] = cohorts
        keep = {"default": cfg["allocations"]["default"]}
        keep.update(allocs)
        cfg["allocations"] = keep
        return cfg, [c["id"] for c in cohorts]

    # ---------------------------------------------------------------- analysis
    def analyse_dim(self, spec, dim, st, today):
        wf = spec["workflow_id"]
        vs, ctrl = st["v"][dim], st["control"][dim]
        G = self.learn.group_counts(wf, dim, st["epoch"][dim], today, DECAY_HALF_LIFE_DAYS)
        tests = []
        for (feat, level), counts in G.items():
            c = counts.get(ctrl)
            if not c or c[0] < N_MIN:
                continue
            for opt in spec["options"][dim]:
                if opt == ctrl or opt not in counts:
                    continue
                o = counts[opt]
                if o[0] < N_MIN:
                    continue
                diff, z, se = two_prop(o[1], o[0], c[1], c[0])
                pc = c[1] / c[0]
                tests.append({"feature": feat, "level": level, "opt": opt, "n_opt": round(o[0], 1),
                              "n_ctrl": round(c[0], 1), "p_opt": round(o[1] / o[0], 4), "p_ctrl": round(pc, 4),
                              "diff": round(diff, 4), "rel_lift": round(diff / pc, 4) if pc else 0.0,
                              "z": round(z, 3), "p": norm_sf(z), "se": se})
        rej = benjamini_hochberg([t["p"] for t in tests], FDR_Q) if tests else []
        # engagement is only a guardrail on pickup-primary workflows: demand much stronger evidence before touching
        # what customers hear there, because thin data (15% exploration) cannot reveal a fading effect
        pmax = P_MAX if spec["objective"]["primary"] == "engagement_rate" else P_MAX_SECONDARY
        for t, r in zip(tests, rej):
            t["discovery"] = bool(r and t["p"] <= pmax and t["diff"] > 0 and t["rel_lift"] >= MIN_LIFT)
            zlim = Z_PRUNE if t["feature"] == "all" else Z_PRUNE_SLICE
            t["harm"] = bool(t["z"] <= -zlim and t["n_opt"] >= N_PRUNE)
        return tests

    def decide_dim(self, spec, dim, st, today, tests, blocked):
        """Return the proposed per-dim variant state plus human-readable decisions."""
        old = st["v"][dim]
        vs = copy.deepcopy(old)
        ctrl = st["control"][dim]
        decisions = []
        # ---- promotions
        usable = [t for t in tests if t["discovery"] and f"{t['feature']}={t['level']}:{t['opt']}" not in blocked
                  and f"*:{t['opt']}" not in blocked and self._still_holding(spec, dim, ctrl, t, today)]
        feats = ["all"] + list(FEATURES)
        if vs["map"]:
            feats = [vs["feature"]]
        best_f, best_score, best_map = None, 0.0, {}
        for f in feats:
            m = {}
            for t in usable:
                if t["feature"] != f:
                    continue
                cur = m.get(t["level"])
                if cur is None or t["diff"] > cur["diff"]:
                    m[t["level"]] = t
            score = sum(t["n_opt"] * t["diff"] for t in m.values())
            if score > best_score:
                best_f, best_score, best_map = f, score, m
        if best_f is not None:
            vs["feature"] = best_f
            for level, t in best_map.items():
                if level in vs["map"]:
                    continue                      # keep a standing winner; decay checks decide when it goes
                vs["map"][level] = t["opt"]
                vs["promoted"][level] = {"day": -1, "rel_lift": t["rel_lift"], "diff": t["diff"], "opt": t["opt"],
                                         "p_ctrl": t["p_ctrl"], "se": t["se"]}
                vs["strength"][level] = t["n_opt"] * t["diff"]
                decisions.append({"action": "promote", "dim": dim, "feature": best_f, "level": level,
                                  "option": t["opt"], "control": ctrl, "evidence": t})
        # ---- per-slice pruning of clearly losing arms (harm control)
        pf = vs["feature"] if vs["feature"] != "all" else None
        harm = [t for t in tests if t["harm"]]
        glob = [t for t in harm if t["feature"] == "all"]
        for t in glob:
            vs["prunes"].setdefault(t["opt"], [])
            if "all=all" not in vs["prunes"][t["opt"]]:
                vs["prunes"][t["opt"]].append("all=all")
                decisions.append({"action": "prune", "dim": dim, "slice": "all", "option": t["opt"], "evidence": t})
        if pf is None:
            cnt = defaultdict(int)
            for t in harm:
                if t["feature"] != "all":
                    cnt[t["feature"]] += 1
            pf = max(cnt, key=lambda f: (cnt[f], -FEATURES.index(f))) if cnt else None
            if pf and not vs["map"]:
                vs["feature"] = "all"
        for t in harm:
            if pf and t["feature"] == pf:
                key = f"{pf}={t['level']}"
                lst = vs["prunes"].setdefault(t["opt"], [])
                if key not in lst and "all=all" not in lst:
                    lst.append(key)
                    vs["strength"][t["level"]] = max(vs["strength"].get(t["level"], 0), t["n_opt"] * abs(t["diff"]) * 0.5)
                    decisions.append({"action": "prune", "dim": dim, "slice": key, "option": t["opt"], "evidence": t})
        # a prune keyed to a feature different from the chosen promotion feature would need two cohort schemes: drop it
        if vs["feature"] != "all":
            for o in list(vs["prunes"]):
                vs["prunes"][o] = [k for k in vs["prunes"][o] if k == "all=all" or k.startswith(vs["feature"] + "=")]
                if not vs["prunes"][o]:
                    del vs["prunes"][o]
        # ---- stop paying for exploration only when the data RULES OUT a gain (upper 95% bound <= +1pt for every arm)
        allg = [t for t in tests if t["feature"] == "all"]
        live_arms = [o for o in spec["options"][dim] if o != ctrl and "all=all" not in vs["prunes"].get(o, [])]
        if allg and not vs["map"] and len(allg) >= len(live_arms) and \
                all(t["diff"] + 1.64 * t["se"] <= 0.01 and t["n_opt"] >= 300 for t in allg if t["opt"] in live_arms):
            vs["explore_ctrl"] = 0.85
        return vs, decisions

    def _still_holding(self, spec, dim, ctrl, t, today):
        """Stability gate before promoting: the decay-weighted test can be carried by days that are already over
        (an effect that is fading looks like a winner for a week). Require the last ~36h, on their own, to show the
        same sign and at least half the lift. Costs about a day of speed; saves promoting a variant that has decayed."""
        rec = self.learn.window_counts(spec["workflow_id"], dim, today - 1, today, t["feature"], t["level"])
        o, c = rec.get(t["opt"]), rec.get(ctrl)
        if not o or not c or o[0] < 40 or c[0] < 40:
            return True            # too little recent data to contradict the main test
        recent = o[1] / o[0] - c[1] / c[0]
        return recent >= 0.5 * t["diff"]

    def check_decay(self, spec, dim, st, today):
        """Winner vs its own control holdout and vs its own early performance. Returns levels to revert."""
        wf = spec["workflow_id"]
        vs = st["v"][dim]
        ctrl = st["control"][dim]
        out = []
        for level, pr in vs["promoted"].items():
            if pr["day"] < 0 or today - pr["day"] < 2:
                continue
            feat = vs["feature"]
            win = vs["map"].get(level)
            if not win:
                continue
            rec = self.learn.window_counts(wf, dim, today - 1, today, feat, level)
            early = self.learn.window_counts(wf, dim, pr["day"], pr["day"] + 1, feat, level)
            w, c = rec.get(win, [0, 0]), rec.get(ctrl, [0, 0])
            ev = {"level": level, "winner": win, "recent_days": [today - 1, today], "promoted_day": pr["day"],
                  "lift_at_promotion": pr["rel_lift"]}
            decayed = False
            zA = None
            if w[0] >= 60 and c[0] >= 40:
                diff, zA, se = two_prop(w[1], w[0], c[1], c[0])
                pc = c[1] / c[0]
                ev.update({"A_recent_rel_lift": round(diff / pc, 4), "A_z": round(zA, 2), "n_w": w[0], "n_c": c[0]})
                if zA <= -1.28:
                    decayed = True
                    ev["trigger"] = "winner is now significantly WORSE than its control holdout"
            e = early.get(win, [0, 0])
            if not decayed and e[0] >= 150 and w[0] >= 150:
                diff, z, se = two_prop(w[1], w[0], e[1], e[0])
                ev.update({"B_drop_vs_own_early": round(diff, 4), "B_z": round(z, 2)})
                if z <= -1.8 and (zA is None or zA < 1.0):
                    decayed = True
                    ev["trigger"] = ("winner's own engagement fell vs its first days after promotion and it no "
                                     "longer clearly beats the control holdout")
            if decayed:
                out.append(ev)
        return out

    def revert_level(self, st_v, dim, level, today):
        vs = st_v["v"][dim]
        opt = vs["map"].pop(level, None)
        vs["promoted"].pop(level, None)
        vs["strength"].pop(level, None)
        if opt:
            vs["blocked"][f"{vs['feature']}={level}:{opt}"] = today + 5     # do not re-promote for 5 days
            # a decaying effect is decaying everywhere: block the option in every slice, since the decay-weighted
            # history that "proved" it elsewhere still contains its pre-decay days
            vs["blocked"][f"*:{opt}"] = today + 5
            vs["prunes"].setdefault(opt, [])
            k = f"{vs['feature']}={level}"
            if k not in vs["prunes"][opt]:
                vs["prunes"][opt].append(k)
        if not vs["map"]:
            vs["feature"] = vs["feature"]
        return opt

    # ---------------------------------------------------------------- guardrail
    def guardrail(self, spec, today):
        wf = spec["workflow_id"]
        base = self.learn.kpi(wf, -7, -1)
        rec = self.learn.kpi(wf, today - 2, today)
        obj = spec["objective"]
        g = obj["guardrail"]
        (name, drop), = g.items()
        if name.startswith("pickup"):
            b, r, nb, nr = base["pickup"], rec["pickup"], base["dials"], rec["dials"]
            kb, kr = base["connected"], rec["connected"]
        else:
            b, r, nb, nr = base["engagement"], rec["engagement"], base["connected"], rec["connected"]
            kb, kr = base["engaged"], rec["engaged"]
        if b is None or r is None or nr < 300:
            return {"breach": False, "metric": name, "baseline": b, "recent": r}
        diff, z, se = two_prop(kr, nr, kb, nb)
        breach = (-diff) > drop and z <= -2.0
        return {"breach": bool(breach), "metric": name, "baseline": round(b, 4), "recent": round(r, 4),
                "drop": round(-diff, 4), "allowed_drop": drop, "z": round(z, 2)}

    # ---------------------------------------------------------------- reporting numbers
    def variant_dry_run(self, spec, st, vs_new, today, tests_by_dim):
        """Replay of logged aggregates: what the promoted rules would have earned on the observed window."""
        levels, gain_num = [], 0.0
        for dim, vs in vs_new.items():
            for level, opt in vs["map"].items():
                t = next((x for x in tests_by_dim.get(dim, []) if x["feature"] == vs["feature"] and
                          x["level"] == level and x["opt"] == opt), None)
                if not t:
                    continue
                share = self._level_share(spec, vs["feature"], level, dim, st, today)
                ci = 1.96 * t["se"]
                levels.append({"dim": dim, "slice": f"{vs['feature']}={level}", "winner": opt,
                               "control": st["control"][dim], "p_winner": t["p_opt"], "p_control": t["p_ctrl"],
                               "n_winner": t["n_opt"], "n_control": t["n_ctrl"], "abs_lift": t["diff"],
                               "ci95": [round(t["diff"] - ci, 4), round(t["diff"] + ci, 4)],
                               "traffic_share": round(share, 3), "z": t["z"]})
                gain_num += share * EXPLOIT[0] * t["diff"]
        return levels, gain_num

    def _level_share(self, spec, feature, level, dim, st, today):
        G = self.learn.group_counts(spec["workflow_id"], dim, st["epoch"][dim], today, DECAY_HALF_LIFE_DAYS)
        tot = G.get(("all", "all"), {})
        n_all = sum(v[0] for v in tot.values()) or 1.0
        g = G.get((feature, level), {})
        return sum(v[0] for v in g.values()) / n_all if feature != "all" else 1.0
