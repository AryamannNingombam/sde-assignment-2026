"""Allocation arithmetic of the C6 experiment lifecycle (pure; shared by the controller and the Monte Carlo)."""
from __future__ import annotations

from typing import Mapping, Sequence

from . import settings

_EPS = 1e-9


def entry_slots() -> int:
    return int((settings.EXP_MAX_CHALLENGER_TOTAL + _EPS) // settings.EXP_ENTRY_SHARE)


def entry_shares(challengers: Sequence[str]) -> dict[str, float]:
    """First challengers in catalogue order, each at the entry share, total <= the entry cap."""
    return {a: settings.EXP_ENTRY_SHARE for a in list(challengers)[:entry_slots()]}


def next_shares(shares: Mapping[str, float], ramp: Sequence[str], drop: Sequence[str],
                untested: Sequence[str] = ()) -> dict[str, float]:
    """Drop, ramp (to the ramp share, keeping control >= the floor) and rotate untested options in."""
    out = {a: s for a, s in shares.items() if a not in set(drop)}
    for arm in ramp:
        if arm in out:
            out[arm] = max(out[arm], settings.EXP_RAMP_SHARE)
    room = 1.0 - settings.EXP_MIN_CONTROL_SHARE
    total = sum(out.values())
    if total > room + _EPS:  # shrink the ramped arms proportionally (never below the entry share)
        scale = room / total
        out = {a: max(settings.EXP_ENTRY_SHARE, s * scale) if a in ramp else s for a, s in out.items()}
    for arm in untested:
        if sum(out.values()) + settings.EXP_ENTRY_SHARE <= settings.EXP_MAX_CHALLENGER_TOTAL + _EPS:
            out[arm] = settings.EXP_ENTRY_SHARE
    return out


def weights(control: str, shares: Mapping[str, float]) -> dict[str, float]:
    live = {a: float(s) for a, s in shares.items() if s > _EPS}
    return {control: round(1.0 - sum(live.values()), 6), **{a: round(s, 6) for a, s in live.items()}}


def promotion_weights(winner: str, old_control: str) -> dict[str, float]:
    return {winner: round(1.0 - settings.EXP_HOLDOUT, 6), old_control: round(settings.EXP_HOLDOUT, 6)}
