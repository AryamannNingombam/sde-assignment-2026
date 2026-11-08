"""Deterministic statistics. No randomness and no LLM ever reaches a decision made here."""
from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist

_N = NormalDist()


def z_quantile(p: float) -> float:
    return _N.inv_cdf(p)


def one_sided_p(z: float) -> float:
    """P(Z >= z)."""
    return 1.0 - _N.cdf(z)


def two_sided_p(z: float) -> float:
    return 2.0 * one_sided_p(abs(z))


@dataclass(frozen=True)
class Comparison:
    """Treatment minus control, stratified, on a single KPI."""
    diff: float
    se: float
    z: float
    p_two_sided: float
    x_t: int
    n_t: int
    x_c: int
    n_c: int

    @property
    def rate_t(self) -> float:
        return self.x_t / self.n_t if self.n_t else 0.0

    @property
    def rate_c(self) -> float:
        return self.x_c / self.n_c if self.n_c else 0.0

    @property
    def lift(self) -> float:
        return self.diff / self.rate_c if self.rate_c else 0.0


def compare_stratified(strata: list[tuple[int, int, int, int]]) -> Comparison | None:
    """Mantel-Haenszel-weighted risk difference over (x_t, n_t, x_c, n_c) strata.

    Strata are (config_version, prompt). Without them a supervisor's mid-experiment prompt edit
    would be confounded with whichever arm happened to get more traffic afterwards.
    A stratum missing either side carries no contrast, so it is skipped: an arm that never ran
    cannot become evidence.
    """
    sum_w = sum_wd = sum_w2v = 0.0
    tot = [0, 0, 0, 0]
    for x_t, n_t, x_c, n_c in strata:
        if n_t <= 0 or n_c <= 0:
            continue
        p_t, p_c = x_t / n_t, x_c / n_c
        w = n_t * n_c / (n_t + n_c)
        pooled = (x_t + x_c) / (n_t + n_c)
        sum_w += w
        sum_wd += w * (p_t - p_c)
        sum_w2v += w * w * pooled * (1 - pooled) * (1 / n_t + 1 / n_c)
        for i, v in enumerate((x_t, n_t, x_c, n_c)):
            tot[i] += v
    if sum_w == 0:
        return None
    diff = sum_wd / sum_w
    se = math.sqrt(sum_w2v) / sum_w
    if se == 0:
        return Comparison(diff, 0.0, 0.0, 1.0, *tot)
    z = diff / se
    return Comparison(diff, se, z, two_sided_p(z), *tot)


def sample_size_per_arm(p: float, mde_relative: float, alpha: float, power: float) -> int:
    """Two-sided, two-proportion sample size per arm."""
    p = min(max(p, 0.01), 0.99)
    delta = p * mde_relative
    z_a, z_b = z_quantile(1 - alpha / 2), z_quantile(power)
    return math.ceil((z_a + z_b) ** 2 * 2 * p * (1 - p) / delta ** 2)


def obf_alpha_spent(t: float, alpha: float) -> float:
    """Lan-DeMets O'Brien-Fleming spending function: cumulative alpha at information fraction t."""
    t = min(max(t, 1e-9), 1.0)
    return 2.0 * (1.0 - _N.cdf(z_quantile(1 - alpha / 2) / math.sqrt(t)))


def holm_rejections(pvals: dict[str, float], alpha: float) -> set[str]:
    """Holm step-down: strong family-wise control across arms without independence assumptions."""
    rejected: set[str] = set()
    ordered = sorted(pvals.items(), key=lambda kv: (kv[1], kv[0]))
    for i, (key, p) in enumerate(ordered):
        if p <= alpha / (len(ordered) - i):
            rejected.add(key)
        else:
            break
    return rejected


def bh_rejections(pvals: dict, q: float) -> set:
    """Benjamini-Hochberg. Subgroup scans are exploratory, so FDR is the honest control there."""
    m = len(pvals)
    ordered = sorted(pvals.items(), key=lambda kv: (kv[1], str(kv[0])))
    cutoff = -1
    for i, (_, p) in enumerate(ordered):
        if p <= q * (i + 1) / m:
            cutoff = i
    return {key for key, _ in ordered[: cutoff + 1]}


def prob_drop_exceeds(diff: float, se: float, limit: float) -> float:
    """Approximate P(true diff < -limit), used for the guardrail."""
    if se == 0:
        return 1.0 if diff < -limit else 0.0
    return _N.cdf((-limit - diff) / se)


def poisson_binomial_z(observed: float, expected: float, variance: float) -> float:
    return 0.0 if variance <= 0 else (observed - expected) / math.sqrt(variance)


def binomial_tail(successes: int, n: int, p: float) -> float:
    """Exact P(X >= successes). Use this for rare events.

    A normal approximation at 4 expected events understates the tail by orders of magnitude.
    That mistake opened a false hallucination incident on a scenario that has none.
    """
    if successes <= 0:
        return 1.0
    if successes > n or p <= 0:
        return 0.0
    if p >= 1:
        return 1.0
    log_p, log_q = math.log(p), math.log1p(-p)
    log_term = (math.lgamma(n + 1) - math.lgamma(successes + 1) - math.lgamma(n - successes + 1)
                + successes * log_p + (n - successes) * log_q)
    total = term = math.exp(log_term)
    for k in range(successes, n):
        term *= (n - k) / (k + 1) * p / (1 - p)
        total += term
        if term < total * 1e-16:
            break
    return min(total, 1.0)
