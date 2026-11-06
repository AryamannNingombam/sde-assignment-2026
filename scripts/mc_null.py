"""Monte Carlo of the C6 decision rule: false-winner rate under the null and power at 10% / 15% true lifts.

Applies exactly the controller's rule (``controller.exp_rules.daily_look`` + ``controller.exp_alloc``): entry shares,
daily ramp/drop, <= 4 O'Brien-Fleming looks, Holm across arms, point lift >= 3%, recent-24h agreement, pickup
non-inferiority, and a workflow scope plus two analysis groups that share the familywise alpha. Per-lead clustering
comes from a Beta lead-propensity model (intra-lead correlation 0.10); leads connect ~1.6 times over the run.
The 4-hourly harm-stop only ever removes arms, so leaving it out is conservative for the false-winner rate.

usage: python scripts/mc_null.py [--runs 1000] [--power-runs 400] [--out reports/mc_null.md]
"""
from __future__ import annotations

import argparse
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from controller import exp_alloc, exp_rules as er, settings  # noqa: E402

DIALS_PER_DAY = 3000
PICKUP = 0.30
ENGAGE = 0.50
DAYS = 8
LEADS = 4500
ICC = 0.10
MAX_DROP = 0.02
CHALLENGERS = ("A", "B")
CONTROL = "C"


def _day_rows(rng, shares, lifts, propensity, group, n_leads):
    """One day of dials -> {arm: (engaged rows, pickup rows)} overall and per group."""
    arms = [CONTROL, *CHALLENGERS]
    probs = np.array([shares.get(a, 0.0) for a in arms])
    probs[0] = 1.0 - probs[1:].sum()
    arm_idx = rng.choice(len(arms), size=DIALS_PER_DAY, p=probs)
    lead = rng.integers(0, n_leads, size=DIALS_PER_DAY)
    connected = rng.random(DIALS_PER_DAY) < PICKUP
    mult = np.array([1.0 + lifts.get(a, 0.0) for a in arms])[arm_idx]
    engaged = connected & (rng.random(DIALS_PER_DAY) < np.minimum(1.0, propensity[lead] * mult))
    out: dict[str, dict[str, tuple[dict, dict]]] = {}
    for scope in ("all", "g0", "g1"):
        sel = np.ones(DIALS_PER_DAY, bool) if scope == "all" else group[lead] == int(scope[1])
        per_arm = {}
        for k, arm in enumerate(arms):
            m = sel & (arm_idx == k)
            eng, pick = {}, {}
            for l, c, e in zip(lead[m].tolist(), connected[m].tolist(), engaged[m].tolist()):
                a, b = pick.get(l, (0, 0)), eng.get(l, (0, 0))
                pick[l] = (a[0] + 1, a[1] + c)
                if c:
                    eng[l] = (b[0] + 1, b[1] + e)
            per_arm[arm] = (eng, pick)
        out[scope] = per_arm
    return out


def _merge(dst: dict, src: dict) -> None:
    for l, (n, x) in src.items():
        a = dst.get(l, (0, 0))
        dst[l] = (a[0] + n, a[1] + x)


def simulate(seed: int, lifts: dict[str, float]) -> dict:
    rng = np.random.default_rng(seed)
    a = b = (1 - ICC) / ICC / 2  # symmetric Beta(a, b): mean 0.5, intra-lead correlation 1 / (a + b + 1) = ICC
    propensity = rng.beta(a, b, size=LEADS)
    group = rng.integers(0, 2, size=LEADS)
    shares = exp_alloc.entry_shares(CHALLENGERS)
    active, ramped, dropped = list(CHALLENGERS), [], []
    scopes = {"all": settings.EXP_ALPHA_WORKFLOW, "g0": settings.EXP_ALPHA_GROUP, "g1": settings.EXP_ALPHA_GROUP}
    cum = {s: {arm: ({}, {}) for arm in (CONTROL, *CHALLENGERS)} for s in scopes}
    st = {s: {"arm_t": {}, "looks": 0} for s in scopes}
    for day in range(DAYS):
        rows = _day_rows(rng, shares, lifts, propensity, group, LEADS)
        for s in scopes:
            for arm in (CONTROL, *CHALLENGERS):
                _merge(cum[s][arm][0], rows[s][arm][0])
                _merge(cum[s][arm][1], rows[s][arm][1])
        winners = []
        for s, alpha in scopes.items():
            data = {arm: er.ArmData(cum[s][arm][0], rows[s][arm][0], cum[s][arm][1]) for arm in cum[s]}
            out = er.daily_look(data, CONTROL, active, len(CHALLENGERS), alpha, arm_t=st[s]["arm_t"],
                                looks_taken=st[s]["looks"], ramped=ramped, exposure_days=day + 1,
                                max_drop=MAX_DROP, test_winner=True)
            if out.took_look:
                st[s]["looks"] += 1
                st[s]["arm_t"] = out.arm_t
            if out.winner:
                winners.append((s, out.winner))
            if s == "all":
                drops, ramps = out.drop, out.ramp
        if winners:
            return {"winner": winners[0][1], "scope": winners[0][0], "day": day}
        active = [a_ for a_ in active if a_ not in drops]
        ramped = sorted(set(ramped) | set(ramps))
        shares = exp_alloc.next_shares(shares, ramps, drops)
        if not active:
            break
    return {"winner": None, "day": None}


def _job(args):
    seed, lifts = args
    return simulate(seed, lifts)


def run(label: str, lifts: dict[str, float], runs: int, base_seed: int, pool) -> dict:
    res = list(pool.map(_job, [(base_seed + i, lifts) for i in range(runs)], chunksize=8))
    any_win = sum(r["winner"] is not None for r in res)
    right = sum(r["winner"] == "A" for r in res)
    wrong = sum(r["winner"] == "B" for r in res)
    days = [r["day"] for r in res if r["winner"] == "A"]
    return {"label": label, "runs": runs, "any": any_win / runs, "right": right / runs, "wrong": wrong / runs,
            "median_day": float(np.median(days)) if days else None}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=1000)
    ap.add_argument("--power-runs", type=int, default=400)
    ap.add_argument("--out", default="reports/mc_null.md")
    ns = ap.parse_args()
    with ProcessPoolExecutor() as pool:
        rows = [run("null (both arms 0%)", {}, ns.runs, 10_000, pool),
                run("10% lift on A, B null", {"A": 0.10}, ns.power_runs, 20_000, pool),
                run("15% lift on A, B null", {"A": 0.15}, ns.power_runs, 30_000, pool)]
    lines = ["# Monte Carlo of the experiment decision rule (C6)", "",
             "Generated by `python scripts/mc_null.py`; applies `controller.exp_rules.daily_look` and "
             "`controller.exp_alloc` unchanged.", "",
             f"Setup: {DIALS_PER_DAY} dials/day at pickup {PICKUP} (about {int(DIALS_PER_DAY * PICKUP)} connects/day), "
             f"engagement {ENGAGE}, {DAYS} days, {LEADS} leads with intra-lead correlation {ICC}, one control and two "
             "challengers entering at 7.5% (ramp to 20% after >= 1 day and >= 100 connects when the point estimate is "
             f">= control, drop at z <= -1), one workflow test (alpha {settings.EXP_ALPHA_WORKFLOW}) and two "
             f"pre-registered half-traffic analysis groups (alpha {settings.EXP_ALPHA_GROUP} each; total "
             f"{settings.EXP_ALPHA}). Decision: <= 4 Lan-DeMets O'Brien-Fleming looks at information fractions "
             "0.25/0.5/0.75/1, Holm across the 2 arms, point lift >= 3%, recent-24h lower bound > 0, pickup "
             f"non-inferiority (margin {MAX_DROP}). Looks happen at the end of each day.", "",
             "| scenario | runs | any promotion | promoted A | promoted B | median day of A's promotion |",
             "|---|---|---|---|---|---|"]
    for r in rows:
        md = "-" if r["median_day"] is None else f"{r['median_day']:.0f}"
        lines.append(f"| {r['label']} | {r['runs']} | {r['any']:.1%} | {r['right']:.1%} | {r['wrong']:.1%} | {md} |")
    lines += ["", f"False-winner rate (null, any arm, any scope): **{rows[0]['any']:.1%}** (target <= 5%). "
              "Power is the share of runs promoting the truly better arm A within the 8-day run."]
    Path(ns.out).parent.mkdir(parents=True, exist_ok=True)
    Path(ns.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
