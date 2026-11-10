"""Simulated time helpers. Minute 0 is D0 00:00; history has negative minutes.

D0 is never hard-coded: it is derived from `/sim/state` (ts and sim_minute), so the controller follows
whatever start date a scenario uses.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

MIN_PER_DAY = 1440


class Clock:
    def __init__(self, d0_iso: str):
        self.d0 = datetime.fromisoformat(d0_iso)
        self._cache: dict[str, int] = {}

    @classmethod
    def from_state(cls, state: dict) -> "Clock":
        d0 = datetime.fromisoformat(state["ts"]) - timedelta(minutes=state["sim_minute"])
        return cls(d0.isoformat())

    def minute(self, ts: str) -> int:
        """Event timestamp -> simulated minute. Cached: thousands of events share a timestamp."""
        m = self._cache.get(ts)
        if m is None:
            if len(self._cache) > 50_000:
                self._cache.clear()
            m = int((datetime.fromisoformat(ts) - self.d0).total_seconds() // 60)
            self._cache[ts] = m
        return m


def fmt(minute: int) -> str:
    """Minute -> 'D3 14:00' (history days are negative: 'D-2 09:00')."""
    day, mod = divmod(minute, MIN_PER_DAY)
    return f"D{day} {mod // 60:02d}:{mod % 60:02d}"


def parse(label: str) -> int:
    """'D3 14:00' -> minute."""
    m = re.fullmatch(r"\s*D(-?\d+)\s+(\d{1,2}):(\d{2})\s*", label)
    if not m:
        raise ValueError(f"expected 'D<day> HH:MM', got {label!r}")
    return int(m[1]) * MIN_PER_DAY + int(m[2]) * 60 + int(m[3])


def hour_of_day(minute: int) -> int:
    return (minute % MIN_PER_DAY) // 60
