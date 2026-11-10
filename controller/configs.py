"""Workflow config helpers and the config-version sync.

`config/history` carries no config bodies, so we keep our own copy per version: the body we proposed for our
own versions, and the live body (read at the tick we first see it) for supervisor edits.
"""
from __future__ import annotations

import copy
import json
import sqlite3

from .clock import Clock
from .sim_client import SimClient

AGENT_DIMS = ("welcome_message", "voice", "caller_id")
CHANGE_DIMS = ("cohorts", "welcome_message", "voice", "caller_id", "prompt_version", "schedule")


# ---------------------------------------------------------------------------- pure helpers
def dist(cfg: dict, cohort: str, dim: str) -> dict[str, float]:
    """Effective allocation of `dim` for `cohort` (a cohort that omits a dim falls back to default)."""
    return (cfg["allocations"].get(cohort) or {}).get(dim) or cfg["allocations"]["default"][dim]


def normalise(d: dict[str, float]) -> dict[str, float]:
    s = sum(d.values())
    return {k: round(v / s, 6) for k, v in sorted(d.items()) if v > 0}


def cohort_ids(cfg: dict) -> list[str]:
    return ["default"] + [c["id"] for c in cfg.get("cohorts", [])]


def cohorts_using_default(cfg: dict, dim: str) -> list[str]:
    """Cohorts whose `dim` allocation is the default one (they don't override it)."""
    return [c for c in cohort_ids(cfg) if c == "default" or dim not in (cfg["allocations"].get(c) or {})]


def tv_shift(old: dict, new: dict) -> float:
    """Largest total-variation distance of any agent-dim allocation across cohorts, as the policy measures it."""
    worst = 0.0
    for c in set(cohort_ids(old)) | set(cohort_ids(new)):
        for dim in AGENT_DIMS:
            a, b = _unit(old, c, dim), _unit(new, c, dim)
            worst = max(worst, 0.5 * sum(abs(a.get(o, 0) - b.get(o, 0)) for o in set(a) | set(b)))
    return worst


def changed_dims(old: dict, new: dict) -> list[str]:
    ch = set()
    if old.get("cohorts", []) != new.get("cohorts", []):
        ch.add("cohorts")
    keys = set(old["allocations"]) | set(new["allocations"])
    for dim in AGENT_DIMS:
        if any(not _same(_unit(old, k, dim), _unit(new, k, dim)) for k in keys):
            ch.add(dim)
    if old.get("prompt_version") != new.get("prompt_version"):
        ch.add("prompt_version")
    if old.get("schedule") != new.get("schedule"):
        ch.add("schedule")
    return [d for d in CHANGE_DIMS if d in ch]


def apply_patch(cfg: dict, patch: dict) -> dict:
    """patch = {"cohorts_add": [cohort...], "allocations": {cohort: {dim: dist}}, "prompt_version": str}"""
    out = copy.deepcopy(cfg)
    existing = {c["id"] for c in out.get("cohorts", [])}
    for c in patch.get("cohorts_add", []):
        if c["id"] not in existing:
            out.setdefault("cohorts", []).append(copy.deepcopy(c))
    for cohort, dims in patch.get("allocations", {}).items():
        for dim, d in dims.items():
            out["allocations"].setdefault(cohort, {})[dim] = normalise(d)
    if "prompt_version" in patch:
        out["prompt_version"] = patch["prompt_version"]
    return out


def patch_dims(patch: dict) -> set[str]:
    dims = {dim for dims in patch.get("allocations", {}).values() for dim in dims}
    if patch.get("cohorts_add"):
        dims.add("cohorts")
    if "prompt_version" in patch:
        dims.add("prompt_version")
    return dims


def _unit(cfg: dict, cohort: str, dim: str) -> dict[str, float]:
    d = dist(cfg, cohort, dim)
    s = sum(d.values())
    return {k: v / s for k, v in d.items()}


def _same(a: dict, b: dict) -> bool:
    return all(abs(a.get(k, 0) - b.get(k, 0)) < 1e-6 for k in set(a) | set(b))


# ---------------------------------------------------------------------------- store access
def current(conn: sqlite3.Connection, wf: str) -> tuple[int, dict | None]:
    row = conn.execute("SELECT version, config_json FROM config_versions WHERE wf=? ORDER BY version DESC LIMIT 1",
                       (wf,)).fetchone()
    return (row[0], json.loads(row[1]) if row[1] else None) if row else (0, None)


def version_at(conn: sqlite3.Connection, wf: str, minute: int) -> sqlite3.Row | None:
    """The version live at `minute` (the business default has minute NULL and counts as -inf)."""
    return conn.execute("SELECT * FROM config_versions WHERE wf=? AND COALESCE(minute, -1e18) <= ?"
                        " ORDER BY version DESC LIMIT 1", (wf, minute)).fetchone()


def sync(conn: sqlite3.Connection, client: SimClient, clock: Clock, wf: str) -> list[dict]:
    """Record versions we haven't seen. Returns the new rows (oldest first)."""
    known, _ = current(conn, wf)
    live = client.config(wf)
    if live["version"] <= known:
        return []
    new = []
    for h in client.config_history(wf):
        if h["version"] <= known:
            continue
        body = live["config"] if h["version"] == live["version"] else _our_body(conn, h["proposal_id"])
        row = {"wf": wf, "version": h["version"], "actor": h["actor"], "changed_dims": h["changed_dims"],
               "proposal_id": h["proposal_id"], "approval_id": h["approval_id"],
               "minute": clock.minute(h["applied_at"]) if h["applied_at"] else None, "config": body}
        conn.execute("INSERT OR IGNORE INTO config_versions VALUES(?,?,?,?,?,?,?,?)",
                     (wf, row["version"], row["actor"], json.dumps(row["changed_dims"]), row["proposal_id"],
                      row["approval_id"], row["minute"], json.dumps(body) if body else None))
        new.append(row)
    return new


def _our_body(conn: sqlite3.Connection, proposal_id: str | None) -> dict | None:
    if not proposal_id:
        return None
    row = conn.execute("SELECT config_json FROM proposals WHERE proposal_id=?", (proposal_id,)).fetchone()
    return json.loads(row[0]) if row and row[0] else None
