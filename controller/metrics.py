"""Read-side queries over `agg`. Every consumer (detectors, experiments, impact, status) counts from here."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

COLUMN = {"welcome_message": "wm", "voice": "voice", "caller_id": "caller_id", "prompt_version": "prompt"}


@dataclass
class Counts:
    dials: int = 0
    connected: int = 0
    concluded: int = 0
    halluc: int = 0

    def num_den(self, kpi: str) -> tuple[int, int]:
        """(successes, trials) for a KPI, from that KPI's own counters."""
        if kpi == "pickup_rate":
            return self.connected, self.dials
        if kpi == "engagement_rate":
            return self.concluded, self.connected
        raise ValueError(kpi)

    def rate(self, kpi: str) -> float | None:
        x, n = self.num_den(kpi)
        return x / n if n else None


def by_option(conn: sqlite3.Connection, wf: str, dim: str | None, *, since_hour: int | None = None,
              until_hour: int | None = None, min_version: int | None = None, versions: list[int] | None = None,
              cohorts: list[str] | None = None, age_band: str | None = None,
              prompt: str | None = None) -> dict[str, Counts]:
    """Counters grouped by the option of `dim` (or a single '*' group when dim is None). Hours are [since, until)."""
    where, args = ["wf=?"], [wf]
    if since_hour is not None:
        where.append("hour>=?")
        args.append(since_hour)
    if until_hour is not None:
        where.append("hour<?")
        args.append(until_hour)
    if min_version is not None:
        where.append("config_version>=?")
        args.append(min_version)
    if versions is not None:
        where.append(f"config_version IN ({','.join('?' * len(versions))})")
        args += versions
    if cohorts is not None:
        where.append(f"cohort_id IN ({','.join('?' * len(cohorts))})")
        args += cohorts
    if age_band is not None:
        where.append("segment LIKE ?")
        args.append(f"%|%|{age_band}|%")
    if prompt is not None:
        where.append("prompt=?")
        args.append(prompt)
    group = COLUMN[dim] if dim else "'*'"
    sql = (f"SELECT {group}, SUM(dials), SUM(connected), SUM(concluded), SUM(halluc) FROM agg"
           f" WHERE {' AND '.join(where)} GROUP BY 1")
    return {r[0]: Counts(r[1], r[2], r[3], r[4]) for r in conn.execute(sql, args)}


def total(conn: sqlite3.Connection, wf: str, **kw) -> Counts:
    return by_option(conn, wf, None, **kw).get("*", Counts())


def by_hour_of_day(conn: sqlite3.Connection, wf: str, dim: str, option: str, *, since_hour: int = -10**9,
                   until_hour: int = 0) -> dict[int, Counts]:
    """Baseline counters per hour of day for one option over [since_hour, until_hour) (default: all history)."""
    sql = (f"SELECT ((hour % 24) + 24) % 24, SUM(dials), SUM(connected), SUM(concluded), SUM(halluc) FROM agg"
           f" WHERE wf=? AND {COLUMN[dim]}=? AND hour>=? AND hour<? GROUP BY 1")
    return {r[0]: Counts(r[1], r[2], r[3], r[4]) for r in conn.execute(sql, (wf, option, since_hour, until_hour))}
