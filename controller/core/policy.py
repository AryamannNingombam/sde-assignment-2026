"""Pure decision logic (no I/O): config diffing, caller-ID allocation, cohort experiments, hallucination detection.

Statistical design (see SUBMISSION.md for the reasoning):
  * Allocation is randomised per call inside each cohort, so within a segment options are directly comparable.
  * Experiments use Thompson sampling over Beta posteriors with a pooled-option prior (partial pooling): thin cells
    borrow strength from the workflow-wide rate of the same option, so they do not over-react to noise, and
    "probability of being best" handles multiple comparisons without a p-value per pair.
  * Data is exponentially down-weighted (half-life) so a winner that decays loses share within ~1-2 days.
"""
import copy
import math

import numpy as np

AGENT_DIMS = ("welcome_message", "voice", "caller_id")
CHANGE_DIMS = ("cohorts", "welcome_message", "voice", "caller_id", "prompt_version", "schedule")


# ------------------------------------------------------------------ config diffing (mirrors docs/SIMULATOR.md s4)
def dist(cfg: dict, cohort: str, dim: str) -> dict:
    return (cfg["allocations"].get(cohort) or {}).get(dim) or cfg["allocations"]["default"][dim]


def tv(a: dict, b: dict) -> float:
    return 0.5 * sum(abs(a.get(o, 0) - b.get(o, 0)) for o in set(a) | set(b))


def changed_dims(old: dict, new: dict, strict: bool = False) -> list[str]:
    """strict=True emulates what the server will see: weights re-normalised, then compared exactly."""
    if strict:
        new = copy.deepcopy(new)
        for dims in new["allocations"].values():
            for dim, w in dims.items():
                s = float(sum(w.values()))
                dims[dim] = {o: float(v) / s for o, v in w.items() if v > 0}
    ch = set()
    if old.get("cohorts", []) != new.get("cohorts", []):
        ch.add("cohorts")
    keys = set(old["allocations"]) | set(new["allocations"])
    for dim in AGENT_DIMS:
        if any(not (_same(dist(old, k, dim), dist(new, k, dim)) if not strict else dist(old, k, dim) == dist(new, k, dim)) for k in keys):
            ch.add(dim)
    if old["prompt_version"] != new["prompt_version"]:
        ch.add("prompt_version")
    if old.get("schedule") != new.get("schedule"):
        ch.add("schedule")
    return [d for d in CHANGE_DIMS if d in ch]


def _same(a: dict, b: dict) -> bool:
    return all(abs(a.get(o, 0) - b.get(o, 0)) < 1e-9 for o in set(a) | set(b))


def max_shift(old: dict, new: dict) -> float:
    keys = {"default"} | {c["id"] for c in old.get("cohorts", [])} | {c["id"] for c in new.get("cohorts", [])}
    return max((tv(dist(old, k, d), dist(new, k, d)) for k in keys for d in AGENT_DIMS), default=0.0)


def step_toward(old: dict, new: dict, max_tv: float) -> dict:
    """Move allocations from old toward new by the largest fraction t that keeps every TV shift <= max_tv."""
    s = max_shift(old, new)
    if s <= max_tv or s == 0:
        return new
    t = max_tv * 0.95 / s
    out = copy.deepcopy(new)
    keys = {"default"} | {c["id"] for c in new.get("cohorts", [])}
    for k in keys:
        for d in AGENT_DIMS:
            a, b = dist(old, k, d), dist(new, k, d)
            if _same(a, b):
                continue
            mix = {o: (1 - t) * a.get(o, 0) + t * b.get(o, 0) for o in set(a) | set(b)}
            out["allocations"].setdefault(k, {})[d] = _norm(mix)
    return out


def _norm(w: dict, q: int = 1024) -> dict:
    """Normalise to multiples of 1/q (largest-remainder). Dyadic weights sum to EXACTLY 1.0 in floating point, so the
    simulator's server-side re-normalisation is a no-op and unchanged distributions are not reported as changed."""
    tot = sum(w.values()) or 1.0
    raw = {o: v / tot * q for o, v in w.items()}
    base = {o: int(math.floor(x)) for o, x in raw.items()}
    rem = q - sum(base.values())
    for o in sorted(raw, key=lambda o: raw[o] - base[o], reverse=True)[:max(rem, 0)]:
        base[o] += 1
    return {o: n / q for o, n in base.items() if n > 0}


# ------------------------------------------------------------------ caller ID
def did_target(rows: dict, options: list[str], min_dials: float = 300, prior_n: float = 40,
               explore_cap: float = 0.15, floor: float = 0.03, seen: dict | None = None):
    """Allocation proportional to (shrunk pickup rate)^4, so a degraded number is drained quickly but smoothly.
    Unexplored IDs are capped so one unknown (possibly spam-flagged) number never takes a big share blind.
    Returns (alloc, stats) or None if there is not enough data."""
    tot_d = sum(r[0] for r in rows.values())
    tot_c = sum(r[1] for r in rows.values())
    if tot_d < min_dials:
        return None
    rbar = tot_c / tot_d
    mean, unexplored, stats = {}, set(), {}
    for d in options:
        r = rows.get("did|" + d)
        dd, cc = (r[0], r[1]) if r is not None else (0.0, 0.0)
        mean[d] = (cc + prior_n * rbar) / (dd + prior_n)
        stats[d] = {"dials": round(float(dd), 1), "pickup": round(float(cc / dd), 4) if dd else None, "shrunk": round(float(mean[d]), 4)}
        sr = seen.get("did|" + d) if seen is not None else r
        if (sr[0] if sr is not None else 0.0) < 100:   # judged on ALL-TIME dials: decay must not turn a known-bad number back into "unexplored"
            unexplored.add(d)
    w = {d: mean[d] ** 4 for d in options}
    cap = {d: explore_cap for d in unexplored} if len(unexplored) < len(options) else {}
    fixed: dict = {}
    for _ in range(len(options)):
        rest = [d for d in options if d not in fixed]
        rem = 1 - sum(fixed.values())
        sw = sum(w[d] for d in rest)
        a = {d: rem * w[d] / sw for d in rest}
        viol = [d for d in rest if d in cap and a[d] > cap[d]]
        if not viol:
            break
        for d in viol:
            fixed[d] = cap[d]
    a.update(fixed)
    a = {d: max(v, floor) for d, v in a.items()}
    for d in options:
        stats[d]["unexplored"] = d in unexplored
    return _norm(a), stats


def did_improve_prob(rows: dict, options: list[str], cur: dict, alloc: dict, prior_n: float = 40,
                     seed: int = 0, draws: int = 4000) -> float:
    """P(expected pickup under `alloc` > under `cur`), from the same shrunk Beta posteriors the target is built on.
    Gate for non-urgent rebalances: a shift between numbers that differ only by noise has P ~ 0.5-0.7 and is not applied."""
    tot_d = sum(r[0] for r in rows.values())
    tot_c = sum(r[1] for r in rows.values())
    rbar = tot_c / tot_d if tot_d else 0.25
    a, b = [], []
    for d in options:
        r = rows.get("did|" + d)
        dd, cc = (float(r[0]), float(r[1])) if r is not None else (0.0, 0.0)
        a.append(cc + prior_n * rbar + 1e-3)
        b.append(max(dd - cc, 0.0) + prior_n * (1 - rbar) + 1e-3)
    s = np.random.default_rng(seed).beta(a, b, size=(draws, len(options)))
    new = np.array([alloc.get(d, 0.0) for d in options])
    old = np.array([cur.get(d, 0.0) for d in options])
    return float(np.mean(s @ new > s @ old))


# ------------------------------------------------------------------ cohorts + experiments
def make_groups(cells: set, max_cohorts: int = 20) -> dict:
    """cells = {(age, lang)}. One cohort per (age x lang) if it fits in 20, else per age band."""
    ages = sorted({a for a, _ in cells})
    langs = sorted({l for _, l in cells})
    if len(ages) * len(langs) <= max_cohorts:
        return {f"c_{a.replace('+', 'p')}_{l}": {"where": {"age_band": [a], "lang": [l]}, "cells": {(a, l)}}
                for a in ages for l in langs if (a, l) in cells}
    return {f"c_{a.replace('+', 'p')}": {"where": {"age_band": [a]}, "cells": {c for c in cells if c[0] == a}} for a in ages}


def engage_targets(rows: dict, groups: dict, options: dict, prompt: str, seed: int, prior_n: float = 30,
                   draws: int = 3000, explore: float = 0.10):
    """Thompson-sampling allocation per (group, dim in voice/welcome_message).
    Returns {dim: {gid: alloc}}, {dim: {gid: {opt: mean}}}, volume {gid: connected}, total (pooled) per dim."""
    rng = np.random.default_rng(seed)
    pooled = {d: {} for d in ("voice", "welcome_message")}
    cellc = {d: {} for d in pooled}
    for key, r in rows.items():
        _, dim, opt, age, lang, prm = key.split("|")
        if prm != prompt:
            continue
        p = pooled[dim].setdefault(opt, [0.0, 0.0]); p[0] += r[1]; p[1] += r[2]
        c = cellc[dim].setdefault((age, lang), {}).setdefault(opt, [0.0, 0.0]); c[0] += r[1]; c[1] += r[2]
    alloc, means, volume, post = {}, {}, {}, {}
    for dim in pooled:
        opts = options[dim]
        seen = {o: (v[1] + 1) / (v[0] + 2) for o, v in pooled[dim].items() if v[0] >= 30}
        gmean = sum(seen.values()) / len(seen) if seen else 0.5   # unseen options start at parity with what we have observed
        prior = {o: seen.get(o, gmean) for o in opts}
        alloc[dim], means[dim], post[dim] = {}, {}, {}
        for gid, g in list(groups.items()) + [("default", {"cells": None})]:
            conn = {o: 0.0 for o in opts}; eng = {o: 0.0 for o in opts}
            for cell, per in cellc[dim].items():
                if g["cells"] is None or cell in g["cells"]:
                    for o, (c, e) in per.items():
                        if o in conn:
                            conn[o] += c; eng[o] += e
            al = np.array([prior[o] * prior_n + eng[o] for o in opts]) + 1e-3
            be = np.array([(1 - prior[o]) * prior_n + conn[o] - eng[o] for o in opts]) + 1e-3
            s = rng.beta(al, be, size=(draws, len(opts)))
            pbest = np.bincount(s.argmax(axis=1), minlength=len(opts)) / draws
            a = (1 - explore) * pbest + explore / len(opts)
            alloc[dim][gid] = _norm(dict(zip(opts, a)))
            means[dim][gid] = dict(zip(opts, (al / (al + be)).tolist()))
            post[dim][gid] = (al, be)
            volume[gid] = max(volume.get(gid, 0.0), sum(conn.values()))
    return alloc, means, volume, post


def unseen_options(rows: dict, options: dict, prompt: str, min_conn: float = 30) -> dict:
    """Per dim, options with fewer than `min_conn` connected calls under the current prompt (no evidence either way)."""
    conn = {d: {} for d in ("voice", "welcome_message")}
    for key, r in rows.items():
        _, dim, opt, _age, _lang, prm = key.split("|")
        if prm == prompt:
            conn[dim][opt] = conn[dim].get(opt, 0.0) + r[1]
    return {d: {o for o in options[d] if conn[d].get(o, 0.0) < min_conn} for d in conn}


def exp_improve_prob(cfg: dict, alloc: dict, post: dict, volume: dict, options: dict, gl: list, seed: int = 0,
                     draws: int = 3000) -> float:
    """P(volume-weighted expected engagement of the proposed allocations > the current ones) over the Beta posteriors,
    summed over voice + welcome. Thompson sampling re-draws every cycle; this stops us applying a draw that is
    only a noise-level move away from what is live."""
    rng = np.random.default_rng(seed)
    total = np.zeros(draws)
    for dim, opts in (("voice", options["voice"]), ("welcome_message", options["welcome_message"])):
        for g in gl:
            al, be = post[dim][g]
            s = rng.beta(al, be, size=(draws, len(opts)))
            new = np.array([alloc[dim][g].get(o, 0.0) for o in opts])
            old = np.array([dist(cfg, g if g in cfg["allocations"] else "default", dim).get(o, 0.0) for o in opts])
            total += max(volume.get(g, 0.0), 1e-9) * (s @ new - s @ old)
    return float(np.mean(total > 0))


def expected_rate(alloc: dict, means: dict) -> float:
    return sum(alloc.get(o, 0) * m for o, m in means.items())


# ------------------------------------------------------------------ guardrails
def guardrail_status(ref_n: float, ref_k: float, cur_n: float, cur_k: float, limit: float, prev: str = "ok",
                     min_n: float = 300, hold_frac: float = 0.5, release_frac: float = 0.25) -> dict:
    """KPI = k/n, drop = reference - current. A drop only counts if it is statistically real (lower confidence bound > 0, so noise
    cannot trip it); then, on the point estimate: drop > limit -> breach, drop > hold_frac*limit -> hold (act BEFORE the limit is
    reached). Once on hold/breach it releases only when the drop falls below release_frac*limit (hysteresis)."""
    if ref_n < min_n or cur_n < min_n:
        return {"state": "unknown", "drop": None, "lb": None}
    pr, pc = ref_k / ref_n, cur_k / cur_n
    se = math.sqrt(pr * (1 - pr) / ref_n + pc * (1 - pc) / cur_n)
    drop = pr - pc
    lb = drop - 1.64 * se
    if lb > 0 and drop > limit:
        state = "breach"
    elif (lb > 0 and drop > hold_frac * limit) or (prev in ("hold", "breach") and drop > release_frac * limit):
        state = "hold"
    else:
        state = "ok"
    return {"state": state, "drop": round(drop, 4), "lb": round(lb, 4), "ref": round(pr, 4), "cur": round(pc, 4)}


def prompt_candidate_check(by_prompt: dict, cand: str, current: str, min_conn: float = 300, max_eng_drop: float = 0.03,
                           max_adh_shift: float = 0.05):
    """by_prompt: {prompt: {conn, eng, fla_n, fla_sum}} (all-time). A fix that stops hallucination but makes the bot robotic
    ('nobody hallucinated, nobody stayed') must not be proposed: compare the candidate's HISTORICAL engagement and flow adherence
    with the other well-observed prompts. Returns ('ok'|'reject'|'unknown', details)."""
    c = by_prompt.get(cand)
    others = {p: v for p, v in by_prompt.items() if p not in (cand, current) and v["conn"] >= min_conn}
    if c is None or c["conn"] < min_conn:
        return "unknown", {"reason": "no history for candidate"}
    if not others:
        return "ok", {"reason": "no comparison prompt"}
    o_conn = sum(v["conn"] for v in others.values())
    ref_eng = max(v["eng"] / v["conn"] for v in others.values())
    ref_adh = sum(v["fla_sum"] for v in others.values()) / max(sum(v["fla_n"] for v in others.values()), 1)
    c_eng = c["eng"] / c["conn"]
    c_adh = c["fla_sum"] / max(c["fla_n"], 1)
    d = {"cand_engagement": round(c_eng, 4), "best_other_engagement": round(ref_eng, 4), "cand_adherence": round(c_adh, 4),
         "other_adherence": round(ref_adh, 4)}
    if c_eng < ref_eng - max_eng_drop:
        return "reject", {**d, "reason": "engagement below the best known prompt"}
    if abs(c_adh - ref_adh) > max_adh_shift:
        return "reject", {**d, "reason": "flow adherence differs from the known prompts"}
    return "ok", d


# ------------------------------------------------------------------ hallucination
def prompt_incident(recent: dict, hist: dict, current: str, recently_changed: bool, min_conn: float = 120):
    """recent: prm|P rows over the last few hours; hist: all-time prm|P rows.
    Returns None, or a dict describing the incident for the CURRENT prompt vs the best known baseline."""
    r = recent.get("prm|" + current)
    if r is None or r[1] < min_conn:
        return None
    n, k = float(r[1]), float(r[3])
    base = {p.split("|")[1]: v[3] / v[1] for p, v in hist.items() if v[1] >= 300}
    best_prompt = min(base, key=base.get) if base else None
    p0 = max(base.get(best_prompt, 0.006), 0.004) if best_prompt else 0.006
    z = (k - n * p0) / math.sqrt(n * p0 * (1 - p0))
    rate = k / n
    # a prompt change in the last 8h is a causal reason to be sensitive; otherwise demand much stronger evidence
    # (we look every 15 min, so a loose z-test would fire on noise).
    z_min, mult, floor = (3.5, 2.5, 0.02) if recently_changed else (5.5, 3.5, 0.03)
    if rate >= max(floor, mult * p0) and z >= z_min:
        return {"current": current, "rate": round(rate, 4), "n": int(n), "flags": int(k), "baseline_rate": round(p0, 4),
                "baseline_prompt": best_prompt, "z": round(z, 1), "known_good": [p for p, b in base.items() if b < 0.02 and p != current]}
    return None
