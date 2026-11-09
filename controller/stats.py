"""Deterministic statistics. No randomness anywhere: the same data always yields the same decision."""
from __future__ import annotations

from math import erfc, sqrt

DEFF = 1.15  # variance inflation: repeat attempts on the same person are not independent


def norm_sf(z: float) -> float:
    return 0.5 * erfc(z / sqrt(2))


def two_prop(k1: float, n1: float, k0: float, n0: float, deff: float = DEFF):
    """Difference p1 - p0 with z (positive => arm 1 better). Counts may be decay-weighted (n_eff)."""
    if n1 <= 0 or n0 <= 0:
        return 0.0, 0.0, 1.0
    p1, p0 = k1 / n1, k0 / n0
    var = deff * (p1 * (1 - p1) / n1 + p0 * (1 - p0) / n0)
    se = sqrt(max(var, 1e-12))
    return p1 - p0, (p1 - p0) / se, se


def benjamini_hochberg(pvals: list[float], q: float) -> list[bool]:
    """Step-up FDR control. Returns a reject mask in the input order."""
    m = len(pvals)
    order = sorted(range(m), key=lambda i: pvals[i])
    kmax = -1
    for rank, i in enumerate(order, 1):
        if pvals[i] <= q * rank / m:
            kmax = rank
    out = [False] * m
    for rank, i in enumerate(order, 1):
        if rank <= kmax:
            out[i] = True
    return out


def binom_z(k: float, n: float, p0: float) -> float:
    if n <= 0:
        return 0.0
    return (k / n - p0) / sqrt(max(p0 * (1 - p0) / n, 1e-12))
