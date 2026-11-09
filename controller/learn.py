"""Read-side queries over the aggregate tables. All windows are decay-weighted, in sim days / hours."""
from __future__ import annotations

from collections import defaultdict

from .common import FEATURES
from .ingest import Ingestor
from .store import Store


def w_day(today: int, day: int, half_life: float) -> float:
    return 0.5 ** (max(today - day, 0) / half_life)


class Learn:
    def __init__(self, store: Store, ing: Ingestor):
        self.s, self.ing = store, ing

    # -------------------------------------------------- caller-ID health (C5), hourly resolution
    def did_stats(self, wf: str, now_min: int, half_life_h: float = 36.0, window_h: int = 168):
        """{did: [n_eff, k_eff, raw_dials_in_window, n_fast, k_fast]}.
        Slow weights (36h half-life) give the steady-state view (health follows load with a ~2 day lag);
        the fast view (raw last 3 hours) exists so a sudden flag is noticed within hours."""
        h_now = now_min // 60
        out: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0, 0.0])
        for hidx, did, dials, conn in self.s.q(
                "SELECT hidx, did, dials, conn FROM agg_did WHERE wf=? AND hidx>=?", (wf, h_now - window_h)):
            age = max(h_now - hidx, 0)
            w = 0.5 ** (age / half_life_h)
            a = out[did]
            a[0] += w * dials
            a[1] += w * conn
            a[2] += dials
            if age <= 2:                      # fast view: the last ~3 hours, undecayed, so pre-incident data cannot mask a flag
                a[3] += dials
                a[4] += conn
        return dict(out)

    def did_window(self, wf: str, h_lo: int, h_hi: int):
        """{did: (dials, conn)} over an absolute hour range (used to judge a flagged ID on post-flag data only)."""
        return {d: (n, k) for d, n, k in self.s.q(
            "SELECT did, SUM(dials), SUM(conn) FROM agg_did WHERE wf=? AND hidx>=? AND hidx<=? GROUP BY did",
            (wf, h_lo, h_hi))}

    # -------------------------------------------------- call time (C4): pickup by (age, tier, hour) with shrinkage
    def hour_profiles(self, wf: str, today: int, half_life: float = 14.0, m: float = 60.0):
        """p_hat[(age, tier)][hour] (hierarchical shrinkage: global shape -> age -> age x tier)."""
        ck = self.ing.cell_keys.get(wf, [])
        ai, ti = FEATURES.index("age_band"), FEATURES.index("city_tier")
        tot = defaultdict(lambda: [0.0, 0.0])
        by_age = defaultdict(lambda: [0.0, 0.0])
        by_grp = defaultdict(lambda: [0.0, 0.0])
        for day, cell, hour, dials, conn in self.s.q(
                "SELECT day, cell, hour, dials, conn FROM agg_hour WHERE wf=? AND day>=?", (wf, today - 30)):
            if cell <= 0 or cell > len(ck):
                continue
            w = w_day(today, day, half_life)
            tup = ck[cell - 1]
            for d, key in ((tot, hour), (by_age, (tup[ai], hour)), (by_grp, ((tup[ai], tup[ti]), hour))):
                a = d[key]
                a[0] += w * dials
                a[1] += w * conn
        hours = sorted({h for h in (k for k in tot)})
        if not hours:
            return {}, hours
        gp = {h: (tot[h][1] + 1e-6) / (tot[h][0] + 1e-6) for h in hours}
        gmean = sum(tot[h][1] for h in hours) / max(sum(tot[h][0] for h in hours), 1e-9)
        shape = {h: gp[h] / max(gmean, 1e-9) for h in hours}
        ages = {k[0] for k in by_age}
        age_p = {}
        for a in ages:
            n_a = sum(by_age[(a, h)][0] for h in hours)
            k_a = sum(by_age[(a, h)][1] for h in hours)
            pbar = k_a / max(n_a, 1e-9)
            age_p[a] = {h: (by_age[(a, h)][1] + m * pbar * shape[h]) / (by_age[(a, h)][0] + m) for h in hours}
        grp_p = {}
        for g in {k[0] for k in by_grp}:
            a = g[0]
            n_g = sum(by_grp[(g, h)][0] for h in hours)
            k_g = sum(by_grp[(g, h)][1] for h in hours)
            pbar = k_g / max(n_g, 1e-9)
            amean = sum(age_p[a][h] for h in hours) / len(hours)
            grp_p[g] = {h: (by_grp[(g, h)][1] + m * pbar * age_p[a][h] / max(amean, 1e-9))
                        / (by_grp[(g, h)][0] + m) for h in hours}
        return {"grp": grp_p, "age": age_p, "all": gp}, hours

    # -------------------------------------------------- variant tables (C6)
    def variant_rows(self, wf: str, dim: str, day_from: int):
        return self.s.q("SELECT day, cell, opt, conn, eng FROM agg_var WHERE wf=? AND dim=? AND day>=?",
                        (wf, dim, day_from))

    def group_counts(self, wf: str, dim: str, day_from: int, today: int, half_life: float = 3.0):
        """{(feature|'all', level|'all'): {option: [n_eff, k_eff]}} decay-weighted from `day_from`."""
        ck = self.ing.cell_keys.get(wf, [])
        out: dict[tuple, dict[str, list[float]]] = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))
        for day, cell, opt, conn, eng in self.variant_rows(wf, dim, day_from):
            if cell <= 0 or cell > len(ck):
                continue
            w = w_day(today, day, half_life)
            tup = ck[cell - 1]
            a = out[("all", "all")][opt]
            a[0] += w * conn
            a[1] += w * eng
            for fi, f in enumerate(FEATURES):
                a = out[(f, tup[fi])][opt]
                a[0] += w * conn
                a[1] += w * eng
        return out

    def window_counts(self, wf: str, dim: str, day_lo: int, day_hi: int, feature: str, level: str):
        """Unweighted [n,k] per option within [day_lo, day_hi] for one group (used for decay checks)."""
        ck = self.ing.cell_keys.get(wf, [])
        fi = FEATURES.index(feature) if feature != "all" else None
        out: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
        for day, cell, opt, conn, eng in self.s.q(
                "SELECT day, cell, opt, conn, eng FROM agg_var WHERE wf=? AND dim=? AND day>=? AND day<=?",
                (wf, dim, day_lo, day_hi)):
            if cell <= 0 or cell > len(ck):
                continue
            if fi is not None and ck[cell - 1][fi] != level:
                continue
            a = out[opt]
            a[0] += conn
            a[1] += eng
        return dict(out)

    # -------------------------------------------------- KPIs
    def kpi(self, wf: str, day_lo: int, day_hi: int):
        r = self.s.q1("SELECT COALESCE(SUM(dials),0), COALESCE(SUM(conn),0), COALESCE(SUM(eng),0) FROM agg_day "
                      "WHERE wf=? AND day>=? AND day<=?", (wf, day_lo, day_hi))
        d, c, e = r
        return {"dials": d, "connected": c, "engaged": e, "pickup": c / d if d else None,
                "engagement": e / c if c else None}

    # -------------------------------------------------- prompt safety
    def prompt_flags(self, wf: str, prompt: str, h_lo: int, h_hi: int):
        r = self.s.q1("SELECT COALESCE(SUM(conn),0), COALESCE(SUM(flags),0) FROM agg_prm "
                      "WHERE wf=? AND prompt=? AND hidx>=? AND hidx<=?", (wf, prompt, h_lo, h_hi))
        return r  # (connected, flagged)

    def prompt_summary(self, wf: str):
        return self.s.q("SELECT prompt, SUM(conn), SUM(flags), MIN(hidx), MAX(hidx) FROM agg_prm WHERE wf=? "
                        "GROUP BY prompt", (wf,))
