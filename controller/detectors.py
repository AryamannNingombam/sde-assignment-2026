"""Population-level detectors (SUBMISSION §5, §7). None of them acts on a single call: each has a minimum n and must hold
for consecutive windows. Every evaluation with enough data writes a decision row.

- Caller-ID health: a number is degraded only if it is worse than its OWN history at matched hours AND worse
  than its peers right now. A number that was always a bit worse is never flagged.
- Hallucination spike: one-sided Poisson test on flags in a rolling window vs the prompt's baseline rate.
- KPI drift: workflow-level primary/guardrail today vs history at the same hours of day. Alerts only, never acts.

Persistence: windows are 3h and evaluated hourly, so two consecutive evaluations share two of their three hours.
The persistence rule is a debounce against one noisy hour, not two independent samples; the false-positive
rate in reports/detector_fp.md was measured with exactly this rule. An evaluation without enough data (e.g.
overnight) resets the streak, so "consecutive" never spans a gap.

The decision logic is in pure functions (`cid_verdict`, `hallu_verdict`) so `scripts/detector_holdout.py` can
replay them over history and measure the false-positive rate.
"""
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict

from . import configs, governance, impact, metrics, policy, settings, stats, store
from .clock import MIN_PER_DAY, hour_of_day

OWNER = "detectors"


# ============================================================================ pure verdicts
def cid_verdict(win: metrics.Counts, hist_matched: metrics.Counts, peers: metrics.Counts | None,
                wf_matched: metrics.Counts | None = None) -> dict:
    """Decide whether one number looks degraded in one window. Returns {'eligible', 'fire', 'rule', ...}.

    `wf_matched` is the whole workflow's history at the same hours. A number without its own history is also held
    to that norm, so an untested number that is simply bad (not just worse than equally bad peers) is caught."""
    out = {"dials": win.dials, "pickup": _r(win.rate("pickup_rate"))}
    if win.dials < settings.CID_MIN_DIALS:
        return {**out, "eligible": False, "fire": False, "rule": f"n<{settings.CID_MIN_DIALS} dials"}
    has_hist = hist_matched.dials >= settings.CID_MIN_HISTORY_DIALS
    z_self = stats.z_two_prop(win.connected, win.dials, hist_matched.connected, hist_matched.dials) if has_hist else None
    has_peers = peers is not None and peers.dials >= settings.CID_MIN_DIALS and peers.connected > 0
    ratio = (win.rate("pickup_rate") / peers.rate("pickup_rate")) if has_peers else None
    out.update({"z_self": _r(z_self), "peer_ratio": _r(ratio), "hist_pickup": _r(hist_matched.rate("pickup_rate"))})
    if has_hist and has_peers:
        fire = z_self is not None and z_self <= settings.CID_SELF_Z and ratio <= settings.CID_PEER_RATIO
        rule = f"self z<={settings.CID_SELF_Z} AND peer ratio<={settings.CID_PEER_RATIO}"
    elif not has_hist and (has_peers or _enough(wf_matched)):
        z_wf = stats.z_two_prop(win.connected, win.dials, wf_matched.connected, wf_matched.dials) \
            if _enough(wf_matched) else None
        out["z_vs_workflow"] = _r(z_wf)
        fire = (has_peers and ratio <= settings.CID_PEER_RATIO_NO_HISTORY) or \
            (z_wf is not None and z_wf <= settings.CID_SELF_Z)
        rule = (f"no own history: peer ratio<={settings.CID_PEER_RATIO_NO_HISTORY} OR z vs workflow history"
                f"<={settings.CID_SELF_Z}")
    elif has_hist:
        fire = z_self is not None and z_self <= settings.CID_SOLO_Z
        rule = f"solo number: self z<={settings.CID_SOLO_Z}"
    else:
        return {**out, "eligible": False, "fire": False, "rule": "no history and no peers"}
    return {**out, "eligible": True, "fire": bool(fire), "rule": rule}


def _enough(c: metrics.Counts | None) -> bool:
    return c is not None and c.dials >= settings.CID_MIN_HISTORY_DIALS


def hallu_verdict(flags: int, connected: int, baseline: float, min_connected: int) -> dict:
    lam = connected * max(baseline, settings.HALLU_BASELINE_FLOOR)
    if connected < min_connected:
        return {"eligible": False, "fire": False, "connected": connected}
    p = stats.poisson_upper_p(flags, lam)
    return {"eligible": True, "fire": p < settings.HALLU_P, "p": float(f"{p:.2e}"), "flags": flags,
            "connected": connected,
            "rate": _r(flags / connected), "baseline": _r(baseline), "expected_flags": _r(lam, 1)}


# ============================================================================ window queries
def cid_window(conn: sqlite3.Connection, wf: str, until_hour: int, baseline: tuple[int, int] = (-10**9, 0)) -> dict:
    """Per number: counts in the window, its baseline at the same hours of day (default: all history), and all
    other numbers combined as peers."""
    since = until_hour - settings.CID_WINDOW_MIN // 60
    rows = conn.execute("SELECT caller_id, ((hour % 24) + 24) % 24, SUM(dials), SUM(connected) FROM agg"
                        " WHERE wf=? AND hour>=? AND hour<? GROUP BY 1, 2", (wf, since, until_hour)).fetchall()
    win: dict[str, metrics.Counts] = defaultdict(metrics.Counts)
    hours: dict[str, set[int]] = defaultdict(set)
    for did, hod, d, c in rows:
        win[did].dials += d
        win[did].connected += c
        hours[did].add(hod)
    out = {}
    wf_hist = {}
    for did in win:                         # every number's history at these hours = the workflow's norm
        for hod, h in metrics.by_hour_of_day(conn, wf, "caller_id", did, since_hour=baseline[0],
                                             until_hour=baseline[1]).items():
            wf_hist.setdefault(hod, metrics.Counts())
            wf_hist[hod].dials += h.dials
            wf_hist[hod].connected += h.connected
    for did, w in win.items():
        hist = metrics.by_hour_of_day(conn, wf, "caller_id", did, since_hour=baseline[0], until_hour=baseline[1])
        wf_matched = metrics.Counts()
        for hod in hours[did]:
            if hod in wf_hist:
                wf_matched.dials += wf_hist[hod].dials
                wf_matched.connected += wf_hist[hod].connected
        matched = metrics.Counts()
        for hod in hours[did]:
            h = hist.get(hod)
            if h:
                matched.dials += h.dials
                matched.connected += h.connected
        peers = metrics.Counts()
        for other, o in win.items():
            if other != did:
                peers.dials += o.dials
                peers.connected += o.connected
        out[did] = (w, matched, peers if peers.dials else None, wf_matched)
    return out


def hallu_baseline(conn: sqlite3.Connection, wf: str, prompt: str) -> tuple[float, str]:
    own = metrics.total(conn, wf, until_hour=0, prompt=prompt)
    if own.connected >= settings.HALLU_MIN_CONNECTED * 5:
        return own.halluc / own.connected, f"{prompt} history"
    allh = metrics.total(conn, wf, until_hour=0)
    return (allh.halluc / allh.connected if allh.connected else settings.HALLU_BASELINE_FLOOR), "workflow history"


# ============================================================================ the detector pass
class Detectors:
    def __init__(self, conn: sqlite3.Connection, specs: dict[str, dict], experiments, incidents):
        self.conn, self.specs, self.experiments, self.incidents = conn, specs, experiments, incidents

    def step(self, minute: int) -> None:
        h = minute // 60
        for wf, spec in self.specs.items():
            if store.get_meta(self.conn, f"detected:{wf}", -1) >= minute:
                continue                            # already ran at this minute (restart): streaks count once
            with store.tx(self.conn):
                store.set_meta(self.conn, f"detected:{wf}", minute)
                self._caller_id(wf, spec, h, minute)
                self._hallucination(wf, h, minute)
                if hour_of_day(minute) == settings.DRIFT_CHECK_HOUR:
                    self._drift(wf, spec, minute)

    # ---------------------------------------------------------------- caller ID
    def _caller_id(self, wf: str, spec: dict, h: int, minute: int) -> None:
        flagged = set(store.get_meta(self.conn, f"cid_flagged:{wf}", []))
        for did, (w, matched, peers, wf_matched) in sorted(cid_window(self.conn, wf, h).items()):
            v = cid_verdict(w, matched, peers, wf_matched)
            key = f"cid_streak:{wf}:{did}"
            if not v["eligible"]:
                store.set_meta(self.conn, key, 0)
                continue
            streak = store.get_meta(self.conn, key, 0) + 1 if v["fire"] else 0
            store.set_meta(self.conn, key, streak)
            if not v["fire"] or did in flagged:
                continue
            v["streak"] = streak
            if streak < settings.CID_PERSIST:
                store.record_decision(self.conn, minute, wf, "caller_id", "degradation seen, waiting for persistence",
                                      {"did": did, **v}, "watch")
                continue
            self._rotate(wf, spec, did, v, minute, flagged)
            flagged.add(did)
            store.set_meta(self.conn, f"cid_flagged:{wf}", sorted(flagged))

    def _rotate(self, wf: str, spec: dict, did: str, v: dict, minute: int, flagged: set[str]) -> None:
        _, cur = configs.current(self.conn, wf)
        evidenced = {o for o, c in metrics.by_option(self.conn, wf, "caller_id").items()
                     if c.dials >= settings.CID_MIN_HISTORY_DIALS}
        patch, onto_untested = {"allocations": {}}, False
        for c in configs.cohort_ids(cur):
            d = configs.dist(cur, c, "caller_id")
            if d.get(did, 0) <= settings.CID_EXPLORE_SHARE + 1e-9:
                continue
            new, untested = rotate_off(d, did, spec["options"]["caller_id"], flagged, evidenced)
            if new:
                patch["allocations"][c] = {"caller_id": new}
                onto_untested |= untested
        if not patch["allocations"]:
            store.record_decision(self.conn, minute, wf, "caller_id",
                                  "flagged, but already at exploration share or no healthy number to move to",
                                  {"did": did, "flagged": sorted(flagged), **v}, "no-op")
            store.raise_alert(self.conn, minute, "page", wf, f"caller ID {did} degraded and no healthy number left")
            return
        self.experiments.invalidate(wf, "caller_id", minute, f"caller-ID health rotation off {did}")
        target = configs.apply_patch(cur, patch)
        # moving real volume onto numbers with no evidence is never automatic: a human approves it
        route = [("approval", target)] if onto_untested else policy.route_change(spec, cur, target)
        harm = (v["hist_pickup"] or v["pickup"] or 0) - (v["pickup"] or 0)
        share = max(configs.dist(cur, c, "caller_id").get(did, 0) for c in configs.cohort_ids(cur))
        payload = {"change_summary": f"Move dials off caller ID {did} (pickup collapsed); keep "
                                     f"{int(settings.CID_EXPLORE_SHARE * 100)}% on it to see recovery"
                                     + ("; no number with evidence left, so untested numbers take the volume"
                                        if onto_untested else ""),
                   "rationale": cid_rationale(did, v),
                   "impact_score": impact.score_harm_avoided(max(harm, 0), share),
                   "dry_run_extra": {"detector": v}}
        did_id = store.record_decision(self.conn, minute, wf, "caller_id", f"flag {did}: {v['rule']}",
                                       {"did": did, **v, "route": [r[0] for r in route]}, "rotate")
        for i, (path, cfg) in enumerate(route):
            step_patch = {"allocations": {c: {"caller_id": configs.dist(cfg, c, "caller_id")} for c in patch["allocations"]}}
            if len(route) == 2 and i == 0:
                step_payload = {**payload, "change_summary": f"First step off caller ID {did} within max_shift "
                                                             f"(full move requested via approval)"}
            else:
                step_payload = payload
            pid = governance.draft(self.conn, minute, wf, "cid_rotation", step_patch, step_payload, owner=OWNER,
                                   refs={"did": did}, decision_id=did_id, path=path, urgent=True)
            self.conn.execute("UPDATE decisions SET proposal_id=COALESCE(proposal_id, ?) WHERE id=?", (pid, did_id))

    # ---------------------------------------------------------------- hallucination
    def _hallucination(self, wf: str, h: int, minute: int) -> None:
        _, cur = configs.current(self.conn, wf)
        prompt = cur["prompt_version"]
        watch = store.get_meta(self.conn, f"hallu_watch:{wf}", {"from": 0, "until": -1})
        watching = minute < watch["until"]
        # heightened watch tests every call on the new prompt since the edit; otherwise a rolling window
        since = watch["from"] // 60 if watching else h - settings.HALLU_WINDOW_MIN // 60
        c = metrics.total(self.conn, wf, since_hour=since, until_hour=h, prompt=prompt)
        base, src = hallu_baseline(self.conn, wf, prompt)
        v = hallu_verdict(c.halluc, c.connected, base, settings.HALLU_MIN_CONNECTED)
        key = f"hallu_streak:{wf}"
        if not v["eligible"]:
            store.set_meta(self.conn, key, 0)
            return
        streak = store.get_meta(self.conn, key, 0) + 1 if v["fire"] else 0
        store.set_meta(self.conn, key, streak)
        persist = 1 if watching else settings.HALLU_PERSIST
        inputs = {"prompt": prompt, "baseline_source": src, "streak": streak, "watch": watching, **v}
        if not v["fire"]:
            if watching:
                store.record_decision(self.conn, minute, wf, "hallucination", "heightened watch: within band",
                                      inputs, "ok")
            return
        if streak < persist:
            store.record_decision(self.conn, minute, wf, "hallucination", "spike seen, waiting for persistence",
                                  inputs, "watch")
            return
        self.incidents.open_hallucination(wf, prompt, inputs, minute)

    def start_watch(self, wf: str, edit_minute: int, minute: int) -> None:
        store.set_meta(self.conn, f"hallu_watch:{wf}", {"from": edit_minute, "until": minute + MIN_PER_DAY})

    # ---------------------------------------------------------------- drift
    def _drift(self, wf: str, spec: dict, minute: int) -> None:
        day_start = (minute // MIN_PER_DAY) * 24
        today = metrics.total(self.conn, wf, since_hour=day_start, until_hour=minute // 60)
        hist = metrics.history_before_hour_of_day(self.conn, wf, hour_of_day(minute))   # same hours of day
        g_kpi = next(iter(spec["objective"]["guardrail"])).removesuffix("_max_drop")
        out = {}
        for k in (spec["objective"]["primary"], g_kpi):
            z = stats.z_two_prop(*today.num_den(k), *hist.num_den(k))
            out[k] = {"today": _r(today.rate(k)), "history": _r(hist.rate(k)), "z": _r(z)}
            if z is not None and z <= settings.DRIFT_Z:
                store.raise_alert(self.conn, minute, "summary", wf,
                                  f"{k} drifted down today: {_pct(today.rate(k))} vs history {_pct(hist.rate(k))}")
        store.record_decision(self.conn, minute, wf, "drift", f"daily KPI drift check (alert at z<={settings.DRIFT_Z})",
                              out, "alert only")

    # ---------------------------------------------------------------- governance callbacks
    def revalidate(self, conn, p, minute) -> tuple[bool, str]:
        return True, "caller-ID rotation stays valid until a supervisor edit says otherwise"

    def on_applied(self, conn, p, version, minute) -> None:
        store.raise_alert(conn, minute, "summary", p["wf"],
                          f"caller ID {json.loads(p['refs_json'])['did']} rotated out (v{version})")

    def on_terminal(self, conn, p, state, minute) -> None:
        if state in ("EXPIRED", "LAPSED", "DROPPED"):        # let the detector fire again on fresh data
            did = json.loads(p["refs_json"])["did"]
            flagged = [d for d in store.get_meta(conn, f"cid_flagged:{p['wf']}", []) if d != did]
            store.set_meta(conn, f"cid_flagged:{p['wf']}", flagged)


def rotate_off(d: dict[str, float], did: str, options: list[str], flagged: set[str],
               evidenced: set[str]) -> tuple[dict[str, float] | None, bool]:
    """Move traffic off `did`, keeping it at the exploration share so recovery stays visible.

    Order of preference: healthy numbers WITH evidence (>= CID_MIN_HISTORY_DIALS dials of their own), in proportion
    to current use (evenly if none is in use). Untested numbers already in use keep at most MAX_UNTESTED_PER_ARM,
    the same cap as an untested variant. Flagged numbers never receive traffic. Only when no evidenced healthy
    number exists does the volume go to untested numbers, evenly; the second return value says so, and the caller
    then routes the change through approval instead of auto-applying it. (None, False) when there is nowhere to go.
    """
    bad = flagged | {did}
    keep = {o: min(w, settings.CID_EXPLORE_SHARE) for o, w in d.items() if o in bad and w > 0}
    keep[did] = settings.CID_EXPLORE_SHARE
    proven = [o for o in options if o not in bad and o in evidenced]
    untested = [o for o in options if o not in bad and o not in evidenced]
    if proven:
        in_use = {o: d[o] for o in proven if d.get(o, 0) > 0}
        weights = in_use or {o: 1.0 for o in proven}
        capped = {o: min(d[o], settings.MAX_UNTESTED_PER_ARM) for o in untested if d.get(o, 0) > 0}
        room, s = 1 - sum(keep.values()) - sum(capped.values()), sum(weights.values())
        out, onto_untested = {**keep, **capped, **{o: room * w / s for o, w in weights.items()}}, False
    elif untested:
        room = 1 - sum(keep.values())
        out, onto_untested = {**keep, **{o: room / len(untested) for o in untested}}, True
    else:
        return None, False
    return {o: round(w, 6) for o, w in sorted(out.items()) if w > 0}, onto_untested


def cid_rationale(did: str, v: dict) -> str:
    """One sentence a supervisor can read; only the comparisons that actually exist are mentioned."""
    parts = [f"{did} pickup {_pct(v['pickup'])} over the last {settings.CID_WINDOW_MIN // 60}h (n={v['dials']})"]
    if v.get("z_self") is not None:
        parts.append(f"vs its own history {_pct(v['hist_pickup'])} at the same hours (z={v['z_self']})")
    if v.get("z_vs_workflow") is not None:
        parts.append(f"vs the workflow's history at the same hours (z={v['z_vs_workflow']})")
    if v.get("peer_ratio") is not None:
        parts.append(f"{v['peer_ratio']}x the pickup of its peers")
    return ", ".join(parts) + f"; held for {v['streak']} consecutive hourly windows ({v['rule']})."


def _r(x, nd: int = 4):
    return None if x is None else round(float(x), nd)


def _pct(x) -> str:
    return "n/a" if x is None else f"{x * 100:.1f}%"

