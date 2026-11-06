"""C7 after a promotion: CUSUM on the winner's own composition-adjusted engagement, confirmed by the holdout.

The winner carries ~90% of traffic, so its own level is high-powered. Its engagement is adjusted for the hour x cell
mix of the calls it received (expected rate per (hour, cell) from the old control's pre-promotion cube history,
shrunk toward the pooled rate), then compared with its own level before promotion (or, if thin, its first blocks after). The 10%
holdout on the old control is the directional confirmation (and a second, direct significance route).
"""
from __future__ import annotations

import math
from typing import Sequence

from . import cube, exp_data, exp_stats as es, settings
from .cohorts import FeatureVocab
from .exp_state import DAY

Block = tuple[float, float, float, float]  # (connects, engaged, expected engaged, variance of engaged)


def reference_rates(store, wid: str, dim: str, control: str, day_max: int,
                    cells: Sequence[int] | None = None) -> tuple[dict, float]:
    """``{(hour, cell): shrunk engagement rate}`` of the old control over the cube days before promotion."""
    rows = cube.rollup(store, wid, by=("hour", "cell"), day_max=day_max, day_min=day_max - 14,
                       variant={exp_data.column(dim): control}, cells=cells)
    tot_n = sum(r.connects for r in rows)
    pooled = sum(r.engaged for r in rows) / tot_n if tot_n else 0.5
    m = settings.EXP_CUSUM_SHRINK_N
    return {r.key: (r.engaged + m * pooled) / (r.connects + m) for r in rows}, pooled


def _winner_rows(store, wid: str, dim: str, winner: str, since: int, until: int | None, ref: dict, pooled: float,
                 cells: Sequence[int] | None):
    """(expected p, engaged) of each winner connect in [since, until), in event order."""
    col = exp_data.column(dim)
    sql = (f"SELECT c.hour, l.cell, c.engaged FROM calls c JOIN leads l ON l.lid=c.lid WHERE c.workflow_id=?"
           f" AND c.day>=? AND c.ts_minute>=? AND c.connected=1 AND c.{col}=?")
    args: list = [wid, since // DAY, since, winner]
    if until is not None:
        sql += " AND c.ts_minute<?"
        args.append(until)
    if cells is not None:
        sql += f" AND l.cell IN ({','.join('?' * len(cells))})" if cells else " AND 0"
        args += list(cells)
    sql += " ORDER BY c.event_id"
    for hour, cell, engaged in store.conn.execute(sql, args):
        yield ref.get((hour, cell), pooled), engaged


def winner_blocks(store, wid: str, dim: str, winner: str, since: int, ref: dict, pooled: float,
                  cells: Sequence[int] | None = None) -> list[Block]:
    """Winner connects after ``since`` cut into blocks of EXP_CUSUM_BLOCK connects."""
    blocks: list[Block] = []
    n = x = e = v = 0.0
    for p, engaged in _winner_rows(store, wid, dim, winner, since, None, ref, pooled, cells):
        n, x, e, v = n + 1, x + engaged, e + p, v + p * (1 - p)
        if n >= settings.EXP_CUSUM_BLOCK:
            blocks.append((n, x, e, v))
            n = x = e = v = 0.0
    return blocks


def pre_promotion_level(store, wid: str, dim: str, winner: str, start: int, applied: int, ref: dict, pooled: float,
                        cells: Sequence[int] | None = None) -> Block | None:
    """The winner's own composition-adjusted level over its last 48 h of experiment exposure (None if too thin)."""
    lo = max(start, applied - 2 * DAY)
    n = x = e = v = 0.0
    for p, engaged in _winner_rows(store, wid, dim, winner, lo, applied, ref, pooled, cells):
        n, x, e, v = n + 1, x + engaged, e + p, v + p * (1 - p)
    return (n, x, e, v) if n >= settings.EXP_CUSUM_BLOCK else None


def cusum(blocks: Sequence[Block], reference: Block | None = None) -> dict:
    """One-sided CUSUM for a DROP of the composition-adjusted ratio.

    The reference is the winner's own level just BEFORE promotion when it has enough data (a decay that is already
    under way when the winner goes live would otherwise be baked into the reference), else its first blocks after.
    """
    k_ref = 0 if reference else settings.EXP_CUSUM_REF_BLOCKS
    out = {"blocks": len(blocks), "alarm": False, "S": 0.0, "ref_ratio": None, "last_ratio": None,
           "reference": "pre-promotion 48h" if reference else f"first {k_ref} blocks"}
    if len(blocks) <= k_ref:
        return out
    ref = reference or (sum(b[0] for b in blocks[:k_ref]), sum(b[1] for b in blocks[:k_ref]),
                        sum(b[2] for b in blocks[:k_ref]), sum(b[3] for b in blocks[:k_ref]))
    e0 = ref[2]
    se0 = math.sqrt(ref[3]) / e0
    r0 = ref[1] / e0
    s, first_alarm = 0.0, None
    for i, (_, x, e, v) in enumerate(blocks[k_ref:], start=k_ref):
        r, se = x / e, math.sqrt(v) / e
        z = (r0 - r) / math.sqrt(se0 ** 2 + se ** 2)
        s = max(0.0, s + z - settings.EXP_CUSUM_K)
        if s >= settings.EXP_CUSUM_H and first_alarm is None:
            first_alarm = i
    out.update(S=round(s, 3), ref_ratio=round(r0, 4), last_ratio=round(blocks[-1][1] / blocks[-1][2], 4),
               alarm=s >= settings.EXP_CUSUM_H, first_alarm_block=first_alarm)
    return out


def holdout_view(store, wid: str, dim: str, winner: str, holdout: str, since: int, now: int,
                 cells: Sequence[int] | None = None) -> dict:
    """Winner vs the concurrent holdout: recent-window point comparison and since-promotion significance."""
    data = exp_data.load_arms(store, wid, dim, since, now, cells)
    w, h = data.get(winner, exp_data.ArmData({}, {}, {})), data.get(holdout, exp_data.ArmData({}, {}, {}))
    since_c, recent_c = es.contrast(w.engaged, h.engaged), es.contrast(w.recent, h.recent)
    out = {"holdout_connects": es.totals(h.engaged)[0], "recent_holdout_connects": es.totals(h.recent)[0]}
    if recent_c is not None:
        out.update(recent_winner=recent_c.rate_a, recent_holdout=recent_c.rate_c, recent_lift=recent_c.lift)
    if since_c is not None:
        out.update(since_lift=since_c.lift, since_z=since_c.z)
    return out


def decide(cus: dict, held: dict) -> tuple[bool, str]:
    """Rollback when the CUSUM alarms AND the holdout confirms direction, or the winner is significantly worse."""
    if (held.get("holdout_connects", 0) >= settings.EXP_ROLLBACK_HOLDOUT_MIN
            and held.get("since_z", 0.0) <= settings.EXP_ROLLBACK_Z):
        return True, (f"winner significantly worse than the holdout since promotion "
                      f"(z {held['since_z']:.2f}, lift {held['since_lift']:+.1%})")
    if cus["alarm"] and held.get("recent_lift") is not None and held["recent_lift"] <= 0:
        return True, (f"CUSUM on the winner's composition-adjusted engagement alarmed (S {cus['S']:.1f} >= "
                      f"{settings.EXP_CUSUM_H}; ratio {cus['ref_ratio']} -> {cus['last_ratio']}) and the holdout "
                      f"confirms (recent winner-vs-holdout lift {held['recent_lift']:+.1%})")
    return False, ""
