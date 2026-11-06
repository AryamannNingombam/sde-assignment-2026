"""Incremental per-prompt flag/adherence/engagement tracker over connected calls (CONTEXT C8, C3).

State per workflow (JSON in ``detector_state``): the current prompt *segment* (a segment starts
whenever the prompt seen on calls changes, i.e. at a ``config_changed`` touching the prompt), hourly
buckets of the current prompt for the rolling 1-day window, lifetime totals of finished segments
(candidates for "last known-good"), and a frozen baseline of the first prompt (history, or the first
connects of a cold start).
"""
from __future__ import annotations

from typing import Mapping

from .. import settings
from ..store import Store
from .common import load_state, save_state

DETECTOR = "halluc"
BUCKET_KEEP_HOURS = 48
# [connects, flags, sum_adherence, engaged]


def _add(a: list, b: list) -> list:
    return [a[0] + b[0], a[1] + b[1], a[2] + b[2], a[3] + b[3]]


def _zero() -> list:
    return [0, 0, 0.0, 0]


def fresh_state() -> dict:
    return {"last_event": 0, "first_prompt": None, "base": _zero(), "base_frozen": False,
            "seg": None, "buckets": {}, "done": {}, "bad": []}


def _flush_segment(st: dict) -> None:
    seg = st["seg"]
    if seg is None:
        return
    prev = st["done"].get(seg["prompt"], {"c": _zero(), "last_ts": seg["start"]})
    st["done"][seg["prompt"]] = {"c": _add(prev["c"], seg["c"]), "last_ts": seg["last_ts"]}


def _apply_group(st: dict, prompt: str, hour: int, counts: list, first_ts: int, last_ts: int) -> None:
    seg = st["seg"]
    if seg is None or seg["prompt"] != prompt:
        _flush_segment(st)
        st["seg"] = seg = {"prompt": prompt, "start": first_ts, "last_ts": last_ts, "c": _zero()}
        st["buckets"] = {}
    seg["c"] = _add(seg["c"], counts)
    seg["last_ts"] = max(seg["last_ts"], last_ts)
    key = str(hour)
    st["buckets"][key] = _add(st["buckets"].get(key, _zero()), counts)
    if st["first_prompt"] is None:
        st["first_prompt"] = prompt
    if prompt == st["first_prompt"] and not st["base_frozen"]:
        if hour >= 0 and st["base"][0] >= settings.HALLUC_BASELINE_MIN_CONNECTS:
            st["base_frozen"] = True  # history (or the first cold-start connects) is complete
        else:
            st["base"] = _add(st["base"], counts)


def update(store: Store, wid: str) -> dict:
    """Fold calls newer than the stored event id into the state; returns (and saves) it."""
    st = load_state(store, DETECTOR, wid) or fresh_state()
    rows = store.conn.execute(
        "SELECT prompt, day*24+hour AS h, COUNT(*), COALESCE(SUM(halluc_flag),0), COALESCE(SUM(adherence),0.0),"
        " SUM(engaged), MIN(ts_minute), MAX(ts_minute), MAX(event_id) FROM calls"
        " WHERE workflow_id=? AND event_id>? AND connected=1 GROUP BY prompt, h ORDER BY MIN(ts_minute), h",
        (wid, st["last_event"])).fetchall()
    for prompt, hour, n, flags, adh, eng, lo, hi, last_id in rows:
        _apply_group(st, prompt, hour, [n, flags, adh, eng], lo, hi)
        st["last_event"] = max(st["last_event"], last_id)
    if rows:
        newest = max(int(k) for k in st["buckets"])
        st["buckets"] = {k: v for k, v in st["buckets"].items() if int(k) > newest - BUCKET_KEEP_HOURS}
        save_state(store, DETECTOR, wid, st)
    return st


def window_counts(st: Mapping, now: int) -> list:
    """Current prompt's connects/flags/adherence/engaged over the rolling day ending at ``now``."""
    lo = now // 60 - settings.HALLUC_WINDOW_MINUTES // 60
    out = _zero()
    for k, v in st["buckets"].items():
        if int(k) > lo:
            out = _add(out, v)
    return out


def known_good_candidates(st: Mapping, current: str) -> list[tuple[str, list]]:
    """Prompts with enough finished-segment data, newest use first, never ones we declared bad."""
    out = [(p, d["c"], d["last_ts"]) for p, d in st["done"].items()
           if p != current and p not in st["bad"] and d["c"][0] >= settings.HALLUC_BASELINE_MIN_CONNECTS]
    return [(p, c) for p, c, _ in sorted(out, key=lambda t: -t[2])]


def save(store: Store, wid: str, st: dict) -> None:
    save_state(store, DETECTOR, wid, st)
