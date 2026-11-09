"""Shared constants and time helpers. The controller knows only what the HTTP API tells it."""
from __future__ import annotations

from datetime import date

# D0 is documented in docs/SIMULATOR.md section 1 (2027-01-04 00:00 IST).
D0_ORD = date(2027, 1, 4).toordinal()
MIN_PER_DAY = 1440
FEATURES = ("lang", "city_tier", "age_band", "value_band")  # order of keys in `lead.features`
CUSTOMER_DIMS = ("welcome_message", "voice")  # what a customer hears: always via human approval
AGENT_DIMS = ("welcome_message", "voice", "caller_id")

_day_cache: dict[str, int] = {}


def day_of(ts: str) -> int:
    """'2027-01-05T09:15:00+05:30' -> sim day index (history days are negative)."""
    d = ts[:10]
    v = _day_cache.get(d)
    if v is None:
        v = _day_cache[d] = date.fromisoformat(d).toordinal() - D0_ORD
    return v


def minute_of(ts: str) -> int:
    return day_of(ts) * MIN_PER_DAY + int(ts[11:13]) * 60 + int(ts[14:16])


def fmt_minute(m: int) -> str:
    d, r = divmod(m, MIN_PER_DAY)
    return f"D{d} {r // 60:02d}:{r % 60:02d}"


def person_idx(person_id: str) -> int:
    return int(person_id[person_id.rindex(":p") + 2:])


def person_id_of(wf: str, idx: int) -> str:
    return f"{wf}:p{idx:07d}"
