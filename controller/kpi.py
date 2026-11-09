"""The three KPIs, each from its own counters. Never blended (constraint 3).

A zero denominator yields `value=None`: "no data", never 0%.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Rate:
    num: int
    den: int
    value: float | None
    ci_low: float | None
    ci_high: float | None

    def as_dict(self) -> dict:
        r = lambda x: None if x is None else round(x, 4)
        return {"value": r(self.value), "n": self.den, "ci95": [r(self.ci_low), r(self.ci_high)]}


def wilson(num: int, den: int, z: float = 1.96) -> Rate:
    if den <= 0:
        return Rate(num, den, None, None, None)
    p = num / den
    d = 1 + z * z / den
    centre = (p + z * z / (2 * den)) / d
    half = z * math.sqrt(p * (1 - p) / den + z * z / (4 * den * den)) / d
    return Rate(num, den, p, max(0.0, centre - half), min(1.0, centre + half))


def pickup(dials: int, connected: int) -> Rate:
    """connected / dials"""
    return wilson(connected, dials)


def engagement(connected: int, concluded: int) -> Rate:
    """concluded conversations / connected calls"""
    return wilson(concluded, connected)


def outcome(uploaded: int, concluded: int) -> Rate:
    """leads concluded / leads uploaded (campaign level)"""
    return wilson(concluded, uploaded)


# Which counters feed each KPI: (numerator column, denominator column) in `agg`.
COUNTERS = {
    "pickup_rate": ("connected", "dials"),
    "engagement_rate": ("concluded", "connected"),
}
