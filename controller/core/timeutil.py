"""Sim-time helpers. D0 00:00 = 2027-01-04T00:00:00+05:30 (documented in docs/SIMULATOR.md section 1)."""
import datetime as dt

_D0 = dt.date(2027, 1, 4).toordinal()
_days: dict[str, int] = {}


def day_of(ts: str) -> int:
    d = _days.get(ts[:10])
    if d is None:
        d = _days[ts[:10]] = dt.date.fromisoformat(ts[:10]).toordinal() - _D0
    return d


def hr_of(ts: str) -> int:
    """Absolute sim-hour index (negative during history)."""
    return day_of(ts) * 24 + int(ts[11:13])


def min_of(ts: str) -> int:
    """Absolute sim minute."""
    return hr_of(ts) * 60 + int(ts[14:16])


def label(minute: int) -> str:
    d, r = divmod(minute, 1440)
    return f"D{d} {r // 60:02d}:{r % 60:02d}"
