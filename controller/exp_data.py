"""Per-lead, per-arm counts for the experiment tests, straight from the ``calls`` table (R7: our own store)."""
from __future__ import annotations

from typing import Sequence

from . import settings
from .exp_rules import ArmData
from .store import Store

DAY = settings.MINUTES_PER_DAY
_COLUMN = {"welcome_message": "welcome", "voice": "voice"}


def column(dim: str) -> str:
    return _COLUMN[dim]


def _cell_filter(cells: Sequence[int] | None) -> tuple[str, list]:
    if cells is None:
        return "", []
    if not cells:
        return " AND 0", []
    return f" AND lid IN (SELECT lid FROM leads WHERE cell IN ({','.join('?' * len(cells))}))", list(cells)


def _group(store: Store, sql: str, args: list) -> dict[str, dict[int, tuple[float, float]]]:
    out: dict[str, dict[int, tuple[float, float]]] = {}
    for arm, lid, n, x in store.conn.execute(sql, args):
        out.setdefault(arm, {})[lid] = (float(n), float(x))
    return out


_STRATUM = "(day*100000 + config_version)"  # one stratum per day and live config version (= share regime)


def _group_strata(store: Store, sql: str, args: list) -> dict[str, dict[str, dict[int, tuple[float, float]]]]:
    out: dict[str, dict[str, dict[int, tuple[float, float]]]] = {}
    for arm, stratum, lid, n, x in store.conn.execute(sql, args):
        out.setdefault(arm, {}).setdefault(str(stratum), {})[lid] = (float(n), float(x))
    return out


def _flatten(strata: dict[str, dict[int, tuple[float, float]]]) -> dict[int, tuple[float, float]]:
    out: dict[int, tuple[float, float]] = {}
    for rows in strata.values():
        for lid, (n, x) in rows.items():
            a = out.get(lid, (0.0, 0.0))
            out[lid] = (a[0] + n, a[1] + x)
    return out


def load_arms(store: Store, wid: str, dim: str, start_minute: int, now: int,
              cells: Sequence[int] | None = None) -> dict[str, ArmData]:
    """Arm data for calls at or after ``start_minute`` (``recent`` = the last EXP_RECENT_MINUTES).

    Engagement is also returned per stratum (day x the config version live at the call = share regime),
    so contrasts can be Mantel-Haenszel pooled.
    """
    col = column(dim)
    cf, cargs = _cell_filter(cells)
    base = f" FROM calls WHERE workflow_id=? AND day>=? AND ts_minute>=?{cf}"
    lead = [wid, start_minute // DAY, start_minute, *cargs]
    eng_s = _group_strata(store, f"SELECT {col}, {_STRATUM}, lid, COUNT(*), SUM(engaged){base} AND connected=1"
                                 f" GROUP BY {col}, {_STRATUM}, lid", lead)
    pick = _group(store, f"SELECT {col}, lid, COUNT(*), SUM(connected){base} GROUP BY {col}, lid", lead)
    recent_from = max(start_minute, now - settings.EXP_RECENT_MINUTES)
    rec_s = _group_strata(store, f"SELECT {col}, {_STRATUM}, lid, COUNT(*), SUM(engaged) FROM calls WHERE workflow_id=?"
                                 f" AND day>=? AND ts_minute>=?{cf} AND connected=1 GROUP BY {col}, {_STRATUM}, lid",
                          [wid, recent_from // DAY, recent_from, *cargs])
    return {arm: ArmData(_flatten(eng_s.get(arm, {})), _flatten(rec_s.get(arm, {})), pick.get(arm, {}),
                         eng_s.get(arm, {}), rec_s.get(arm, {}))
            for arm in sorted(set(eng_s) | set(pick) | set(rec_s))}


def first_exposure_minute(store: Store, wid: str, dim: str, options: Sequence[str], since: int = 0) -> int | None:
    """First call served by any of ``options`` (the decay clock of a challenger starts here)."""
    if not options:
        return None
    col = column(dim)
    row = store.conn.execute(f"SELECT MIN(ts_minute) FROM calls WHERE workflow_id=? AND ts_minute>=? AND {col} IN"
                             f" ({','.join('?' * len(options))})", [wid, since, *options]).fetchone()
    return None if row is None or row[0] is None else int(row[0])
