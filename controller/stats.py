"""Deterministic statistics. The only place winners are decided (constraint 4).

Conventions: one-sided tests, "1" = challenger, "0" = control. Pure functions, no I/O.
"""
from __future__ import annotations

import math
from statistics import NormalDist

_N = NormalDist()


def z_quantile(p: float) -> float:
    return _N.inv_cdf(p)


def z_two_prop(x1: int, n1: int, x0: int, n0: int) -> float | None:
    """Pooled two-proportion z for p1 - p0. None when either arm is empty or the pooled rate is degenerate."""
    if n1 <= 0 or n0 <= 0:
        return None
    p = (x1 + x0) / (n1 + n0)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n0))
    if se == 0:
        return None
    return (x1 / n1 - x0 / n0) / se


def p_greater(x1: int, n1: int, x0: int, n0: int) -> float:
    """One-sided p-value for H1: p1 > p0. Returns 1.0 when untestable."""
    z = z_two_prop(x1, n1, x0, n0)
    return 1.0 if z is None else 1 - _N.cdf(z)


def p_less(x1: int, n1: int, x0: int, n0: int) -> float:
    """One-sided p-value for H1: p1 < p0 (harm). Returns 1.0 when untestable."""
    z = z_two_prop(x1, n1, x0, n0)
    return 1.0 if z is None else _N.cdf(z)


def holm(pvals: dict[str, float], alpha: float) -> dict[str, bool]:
    """Holm step-down. Ties are ordered by key so the same input always gives the same answer."""
    order = sorted(pvals, key=lambda k: (pvals[k], k))
    m = len(order)
    out = {k: False for k in pvals}
    for i, k in enumerate(order):
        if pvals[k] <= alpha / (m - i):
            out[k] = True
        else:
            break
    return out


def diff_lower_bound(x1: int, n1: int, x0: int, n0: int, z: float = 1.96) -> float | None:
    """Lower bound of the unpooled (Wald) interval for p1 - p0."""
    if n1 <= 0 or n0 <= 0:
        return None
    p1, p0 = x1 / n1, x0 / n0
    se = math.sqrt(p1 * (1 - p1) / n1 + p0 * (1 - p0) / n0)
    return (p1 - p0) - z * se


def noninferior(x1: int, n1: int, x0: int, n0: int, max_drop: float, z: float = 1.96) -> bool:
    """Guardrail: the challenger passes only if lower bound of (p1 - p0) > -max_drop. max_drop is absolute."""
    lb = diff_lower_bound(x1, n1, x0, n0, z)
    return lb is not None and lb > -max_drop


def n_per_arm(p: float, delta: float, alpha: float, power: float) -> int:
    """Equal-allocation sample size for a one-sided two-proportion test at baseline p, effect delta."""
    z = z_quantile(1 - alpha) + z_quantile(power)
    return math.ceil(z * z * 2 * p * (1 - p) / (delta * delta))


def mde(p: float, n1: float, n0: float, alpha: float, power: float) -> float:
    """Smallest absolute effect detectable with arms of size n1 and n0."""
    z = z_quantile(1 - alpha) + z_quantile(power)
    return z * math.sqrt(p * (1 - p) * (1 / n1 + 1 / n0))


def poisson_upper_p(k: int, lam: float) -> float:
    """P(X >= k) for X ~ Poisson(lam). Summed in log space so large lam stays stable."""
    if k <= 0:
        return 1.0
    if lam <= 0:
        return 0.0
    log_term = -lam                      # log P(X=0)
    cdf = math.exp(log_term)
    for i in range(1, k):
        log_term += math.log(lam) - math.log(i)
        cdf += math.exp(log_term)
    return max(0.0, 1.0 - cdf)
