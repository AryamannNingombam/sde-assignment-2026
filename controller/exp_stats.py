"""Statistics for C6/C7 experiments: per-lead clustered contrasts, Lan-DeMets O'Brien-Fleming looks, Holm.

Everything is a pure, deterministic function of its inputs (R5).

* ``Rows``: per-lead counts of one arm, ``{lid: (n, x)}`` (n = connects, x = engaged; or dials/connects).
* ``contrast``: ratio-estimator difference (or log-ratio) of two arms with a per-lead (sandwich) variance. A lead
  that appears in both arms contributes ONE joint influence term, so the covariance between the arms is accounted for.
* ``obf_boundaries``: one-sided Lan-DeMets spending ``alpha*(t) = 2 (1 - Phi(z_{alpha/2} / sqrt(t)))`` solved by
  numerical integration over the actual information fractions of the looks taken.
* ``holm_order``: Holm step-down over the arms of one family.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from statistics import NormalDist
from typing import Mapping, Sequence

import numpy as np

Rows = Mapping[int, tuple[float, float]]
_N = NormalDist()
_GRID_H = 0.02
_GRID_MAX = 9.0


@dataclass(frozen=True)
class Contrast:
    n_a: float
    n_c: float
    rate_a: float
    rate_c: float
    effect: float  # log(rate_a / rate_c) (scale="log") or rate_a - rate_c (scale="diff")
    se: float
    z: float
    clusters: int

    @property
    def info(self) -> float:
        return 1.0 / (self.se * self.se) if self.se > 0 else 0.0

    @property
    def lift(self) -> float:
        """Relative lift of arm over control (log scale only)."""
        return self.rate_a / self.rate_c - 1.0 if self.rate_c > 0 else 0.0

    def lift_lower(self, z: float) -> float:
        return math.exp(self.effect - z * self.se) - 1.0


def totals(rows: Rows) -> tuple[float, float]:
    return sum(r[0] for r in rows.values()), sum(r[1] for r in rows.values())


def contrast(arm: Rows, control: Rows, scale: str = "log") -> Contrast | None:
    """Arm vs control. ``None`` when either side has no events (nothing to estimate)."""
    n_a, x_a = totals(arm)
    n_c, x_c = totals(control)
    if n_a <= 0 or n_c <= 0 or (scale == "log" and (x_a <= 0 or x_c <= 0)):
        return None
    p_a, p_c = x_a / n_a, x_c / n_c
    leads = set(arm) | set(control)
    sq = 0.0
    for lid in leads:
        na_i, xa_i = arm.get(lid, (0.0, 0.0))
        nc_i, xc_i = control.get(lid, (0.0, 0.0))
        ra, rc = xa_i - p_a * na_i, xc_i - p_c * nc_i
        if scale == "log":
            psi = ra / x_a - rc / x_c
        else:
            psi = ra / n_a - rc / n_c
        sq += psi * psi
    g = len(leads)
    sq *= g / (g - 1) if g > 1 else 1.0
    se = math.sqrt(sq)
    effect = math.log(p_a / p_c) if scale == "log" else p_a - p_c
    z = effect / se if se > 0 else 0.0
    return Contrast(n_a, n_c, p_a, p_c, effect, se, z, g)


# ------------------------------------------------------------------ Lan-DeMets O'Brien-Fleming
def obf_spend(t: float, alpha: float) -> float:
    """Cumulative one-sided alpha spent at information fraction ``t``."""
    if t <= 0:
        return 0.0
    if t >= 1:
        return alpha
    return 2.0 * (1.0 - _N.cdf(_N.inv_cdf(1.0 - alpha / 2.0) / math.sqrt(t)))


def _norm_sf_vec(x: np.ndarray) -> np.ndarray:
    from math import erfc
    return 0.5 * np.vectorize(erfc)(x / math.sqrt(2.0))


@lru_cache(maxsize=4096)
def _boundaries(ts: tuple[float, ...], alpha: float) -> tuple[float, ...]:
    """Upper boundaries (z scale) for looks at information fractions ``ts`` (strictly increasing, <= 1)."""
    grid = np.arange(-_GRID_MAX, _GRID_MAX + _GRID_H / 2, _GRID_H)
    out: list[float] = []
    dens = None  # density of B(t_{j-1}) on the grid, restricted to "no crossing yet"
    prev_t, prev_spent = 0.0, 0.0
    for t in ts:
        inc = obf_spend(t, alpha) - prev_spent
        sd = math.sqrt(t - prev_t)
        if dens is None:
            b_z = _N.inv_cdf(1.0 - inc) if inc < 1 else 0.0
            nxt = np.exp(-0.5 * (grid / sd) ** 2) / (sd * math.sqrt(2 * math.pi))
        else:
            def crossing(b: float) -> float:
                z = (b * math.sqrt(t) - grid) / sd
                return float(np.sum(dens * _norm_sf_vec(z)) * _GRID_H)
            lo, hi = 0.0, 12.0
            for _ in range(48):
                mid = 0.5 * (lo + hi)
                if crossing(mid) > inc:
                    lo = mid
                else:
                    hi = mid
            b_z = 0.5 * (lo + hi)
            kern = np.exp(-0.5 * ((grid[:, None] - grid[None, :]) / sd) ** 2) / (sd * math.sqrt(2 * math.pi))
            nxt = (dens[None, :] * kern).sum(axis=1) * _GRID_H
        out.append(b_z)
        dens = np.where(grid < b_z * math.sqrt(t), nxt, 0.0)
        prev_t, prev_spent = t, obf_spend(t, alpha)
    return tuple(out)


def obf_boundary(ts: Sequence[float], alpha: float) -> float:
    """Boundary of the LAST look in ``ts`` given the earlier looks' information fractions."""
    clean: list[float] = []
    for t in ts:
        t = min(1.0, max(float(t), 1e-4))
        if not clean or t > clean[-1] + 1e-4:
            clean.append(round(t, 4))
    if not clean:
        return math.inf
    if clean[-1] >= 1.0 and len(clean) > 1 and clean[-2] >= 1.0:
        return math.inf
    return _boundaries(tuple(clean), round(alpha, 8))[-1]


# ------------------------------------------------------------------ Holm
def holm_order(zs: Mapping[str, float], family_size: int, alpha: float, boundary) -> dict[str, dict]:
    """Holm step-down on the arms' z. ``boundary(alpha_adj, arm) -> z threshold``.

    Arms are tested in decreasing z; rank r (1-based) uses ``alpha / (family_size - r + 1)``; the first failure
    stops the procedure. Returns ``{arm: {"rank", "alpha_adj", "boundary", "z", "rejected"}}``.
    """
    out: dict[str, dict] = {}
    stopped = False
    for rank, arm in enumerate(sorted(zs, key=lambda a: (-zs[a], a)), start=1):
        a_adj = alpha / max(1, family_size - rank + 1)
        b = boundary(a_adj, arm)
        ok = (not stopped) and zs[arm] >= b
        stopped = stopped or not ok
        out[arm] = {"rank": rank, "alpha_adj": round(a_adj, 6), "boundary": b if math.isfinite(b) else None,
                    "z": zs[arm], "rejected": ok}
    return out
