"""Small, dependency-free statistics used by the detectors (R5: deterministic decisions)."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence


def norm_sf(z: float) -> float:
    """Upper-tail probability of the standard normal."""
    return 0.5 * math.erfc(z / math.sqrt(2.0))


def two_prop_z(x1: int, n1: int, x2: int, n2: int, alternative: str = "less") -> tuple[float, float]:
    """Pooled two-proportion z-test of group 1 against group 2.

    ``alternative`` is ``"less"`` (p1 < p2) or ``"greater"``. No data on either side: p = 1.
    """
    if n1 <= 0 or n2 <= 0:
        return 0.0, 1.0
    pooled = (x1 + x2) / (n1 + n2)
    var = pooled * (1 - pooled) * (1 / n1 + 1 / n2)
    if var <= 0:
        return 0.0, 1.0
    z = (x1 / n1 - x2 / n2) / math.sqrt(var)
    return z, norm_sf(-z) if alternative == "less" else norm_sf(z)


def wilson_upper(x: int, n: int, z: float = 1.96) -> float:
    """Upper Wilson bound of a binomial proportion (used to rank failure rates)."""
    if n <= 0:
        return 1.0
    p = x / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    spread = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return min(1.0, (centre + spread) / denom)


def isotonic_decreasing(xs: Sequence[float], ys: Sequence[float], ws: Sequence[float]
                        ) -> list[tuple[float, float, float]]:
    """Pool-adjacent-violators for a non-increasing fit. Returns blocks ``(x_mean, level, weight)``."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    blocks: list[list[float]] = []  # [sum_wx, sum_wy, sum_w]
    for i in order:
        w = max(float(ws[i]), 1e-12)
        blocks.append([w * xs[i], w * ys[i], w])
        while len(blocks) > 1 and blocks[-2][1] / blocks[-2][2] < blocks[-1][1] / blocks[-1][2]:
            last = blocks.pop()
            for k in range(3):
                blocks[-1][k] += last[k]
    return [(b[0] / b[2], b[1] / b[2], b[2]) for b in blocks]


@dataclass(frozen=True)
class RatioDrop:
    drop: float  # 1 - adjusted ratio-of-ratios (positive = the DID got worse vs peers)
    z: float
    p: float  # one-sided p for "got worse"
    q_window: float
    q_ref: float


def _logvar(x: float, n: float) -> float:
    x = max(x, 0.5)
    return max(1.0 - x / n, 1e-9) / x


def ratio_drop_test(x_w: int, n_w: int, xp_w: int, np_w: int, x_r: int, n_r: int, xp_r: int, np_r: int,
                    expected_ratio_change: float = 1.0) -> RatioDrop:
    """Did a DID's pickup, relative to its peers, step down between a reference period and a window?

    q = pickup(DID) / pickup(peers) in each period; the statistic is ln(q_window / (q_ref * e))
    where ``e`` is the change the fatigue curve already predicts (load difference). The variance
    is the delta-method sum of the four binomial log-proportion variances.
    """
    def ratio(x, n, xp, npp):
        return (max(x, 0.5) / n) / (max(xp, 0.5) / npp)
    q_w, q_r = ratio(x_w, n_w, xp_w, np_w), ratio(x_r, n_r, xp_r, np_r)
    q_adj = q_w / (q_r * expected_ratio_change)
    se = math.sqrt(_logvar(x_w, n_w) + _logvar(xp_w, np_w) + _logvar(x_r, n_r) + _logvar(xp_r, np_r))
    z = math.log(q_adj) / se
    return RatioDrop(1.0 - q_adj, z, norm_sf(-z), q_w, q_r)
