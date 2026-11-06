"""Pure allocation planning for caller-ID health: probe cap, target split, bounded steps."""
from __future__ import annotations

from typing import Mapping

from .. import settings

TESTED, UNTESTED, SUSPECT, FLAGGED, WEAK = "tested", "untested", "suspect", "flagged", "weak"
BAD = (FLAGGED, WEAK)
_EPS = 1e-12


def probe_cap(h_bar: float) -> float:
    """Largest share ``s`` for an untested DID with the worst-case DID-health step above -2%.

    ``s <= 0.015 * h_bar / (h_bar - h_floor)``: if the probe is as bad as ``h_floor`` the expected
    health moves by ``s * (h_bar - h_floor) / h_bar`` <= 1.5%. h_floor is a documented prior.
    """
    gap = max(h_bar - settings.DID_H_FLOOR, 0.01)
    return min(1.0, settings.DID_PROBE_BASE_STEP * h_bar / gap)


def tv(a: Mapping[str, float], b: Mapping[str, float]) -> float:
    return 0.5 * sum(abs(a.get(k, 0.0) - b.get(k, 0.0)) for k in set(a) | set(b))


def _clean(alloc: Mapping[str, float]) -> dict[str, float]:
    total = sum(v for v in alloc.values() if v > _EPS)
    return {k: v / total for k, v in alloc.items() if v > _EPS} if total > 0 else {}


def target_allocation(current: Mapping[str, float], status: Mapping[str, str], h_bar: float
                      ) -> dict[str, float]:
    """Desired caller-ID split: even over non-bad DIDs, one untested DID probed at the cap.

    While a bad (flagged/weak) DID still holds traffic this is an evacuation: untested DIDs may
    take the evacuated traffic beyond the probe cap, since their worst case is no worse than the
    bad source.
    """
    options = list(status)
    bad = [d for d in options if status[d] in BAD]
    evacuating = any(current.get(d, 0.0) > _EPS for d in bad)
    tested = [d for d in options if status[d] == TESTED]
    untested = [d for d in options if status[d] == UNTESTED]
    suspects = [d for d in options if status[d] == SUSPECT]
    if evacuating:
        receivers = tested + untested or suspects
        return _clean({d: 1.0 for d in receivers}) if receivers else _clean(current)
    if not tested:
        return _clean(current)  # nothing is known to be healthy: change nothing
    cap = probe_cap(h_bar)
    out: dict[str, float] = {}
    for d in suspects:  # never grow a DID that looks worse than its peers
        out[d] = min(current.get(d, 0.0), cap)
    if untested:
        out[untested[0]] = cap
    rest = max(1.0 - sum(out.values()), 0.0)
    for d in tested:
        out[d] = rest / len(tested)
    return _clean(out)


def plan_step(current: Mapping[str, float], target: Mapping[str, float], max_shift: float | None,
              status: Mapping[str, str]) -> dict[str, float]:
    """One bounded move from ``current`` towards ``target`` with TV <= max_shift * safety.

    Traffic leaves bad DIDs first; it lands on tested-healthy DIDs before untested ones.
    """
    cur, tgt = _clean(current), _clean(target)
    if max_shift is None:
        return tgt
    budget = max_shift * settings.DID_STEP_SAFETY
    if tv(cur, tgt) <= budget + _EPS:
        return tgt
    keys = set(cur) | set(tgt)
    out = {k: cur.get(k, 0.0) for k in keys}
    sources = sorted((k for k in keys if cur.get(k, 0.0) > tgt.get(k, 0.0) + _EPS),
                     key=lambda k: (status.get(k) not in BAD, k))
    sinks = sorted((k for k in keys if tgt.get(k, 0.0) > cur.get(k, 0.0) + _EPS),
                   key=lambda k: (status.get(k) != TESTED, k))
    left = budget
    for k in sources:
        take = min(cur[k] - tgt.get(k, 0.0), left)
        out[k] -= take
        left -= take
    left = budget
    for k in sinks:
        put = min(tgt[k] - cur.get(k, 0.0), left)
        out[k] += put
        left -= put
    return _clean(out)
