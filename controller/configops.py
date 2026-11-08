"""Config changes expressed as data, applied to whatever the live config is at send time.

Keeping ops separate from any particular config is what makes re-proposal safe: after a supervisor
edit the same ops are replayed on the new base, so the supervisor's change is never overwritten.
"""
from __future__ import annotations

import copy

ALLOC_DIMS = ("welcome_message", "voice", "caller_id")


def _normalise(dist: dict) -> dict:
    total = sum(dist.values())
    return {k: round(v / total, 6) for k, v in sorted(dist.items())} if total > 0 else {}


def effective(config: dict, cohort: str, dim: str) -> dict:
    """The distribution a cohort really dials with, including fallback to default."""
    allocs = config.get("allocations", {})
    dist = allocs.get(cohort, {}).get(dim) or allocs.get("default", {}).get(dim) or {}
    return _normalise(dist)


def _ordered_cohorts(cohorts: list[dict]) -> list[dict]:
    """A supervisor's cohorts keep their order and precedence. Ours follow, most specific first."""
    theirs = [c for c in cohorts if not c["id"].startswith("c_")]
    ours = sorted((c for c in cohorts if c["id"].startswith("c_")),
                  key=lambda c: (-len(c["where"]), c["id"]))
    return theirs + ours


def apply_ops(config: dict, ops: list[dict]) -> dict:
    out = copy.deepcopy(config)
    allocs = out.setdefault("allocations", {})
    for op in ops:
        kind = op["op"]
        if kind == "set_alloc":
            allocs.setdefault(op["cohort"], {})[op["dim"]] = _normalise(op["dist"])
        elif kind == "add_cohort":
            if not any(c["id"] == op["id"] for c in out.setdefault("cohorts", [])):
                out["cohorts"].append({"id": op["id"], "where": op["where"]})
                out["cohorts"] = _ordered_cohorts(out["cohorts"])
        elif kind == "set_prompt":
            out["prompt_version"] = op["prompt"]
        elif kind == "remove_arm":
            cohort_alloc = allocs.get(op["cohort"], {})
            dist = dict(cohort_alloc.get(op["dim"], {}))
            if op["arm"] in dist and len(dist) > 1:
                del dist[op["arm"]]
                cohort_alloc[op["dim"]] = _normalise(dist)
        elif kind == "quarantine_did":
            _quarantine(allocs, op["did"], op.get("replacements", []))
        elif kind == "set_did_shares":
            allocs.setdefault("default", {})["caller_id"] = _normalise(op["dist"])
        else:
            raise ValueError(f"unknown op {kind}")
    return out


def _quarantine(allocs: dict, did: str, replacements: list[str]) -> None:
    for alloc in allocs.values():
        dist = alloc.get("caller_id")
        if not dist or did not in dist:
            continue
        remaining = {k: v for k, v in dist.items() if k != did and v > 0}
        if not remaining:
            remaining = {r: 1.0 for r in replacements if r != did}
        if remaining:
            alloc["caller_id"] = _normalise(remaining)


def changed_dims(old: dict, new: dict) -> list[str]:
    dims = []
    if old.get("cohorts", []) != new.get("cohorts", []):
        dims.append("cohorts")
    cohorts = set(old.get("allocations", {})) | set(new.get("allocations", {}))
    for dim in ALLOC_DIMS:
        if any(old.get("allocations", {}).get(c, {}).get(dim) != new.get("allocations", {}).get(c, {}).get(dim)
               for c in cohorts):
            dims.append(dim)
    if old.get("prompt_version") != new.get("prompt_version"):
        dims.append("prompt_version")
    if old.get("schedule") != new.get("schedule"):
        dims.append("schedule")
    return dims


def total_variation(a: dict, b: dict) -> float:
    return 0.5 * sum(abs(a.get(k, 0.0) - b.get(k, 0.0)) for k in set(a) | set(b))


def max_shift(old: dict, new: dict) -> float:
    """Largest per-cohort total-variation move, the quantity auto-apply's max_shift limits."""
    cohorts = set(old.get("allocations", {})) | set(new.get("allocations", {})) | {"default"}
    return max(total_variation(effective(old, c, d), effective(new, c, d)) for c in cohorts for d in ALLOC_DIMS)


def diff(old: dict, new: dict) -> dict:
    """A readable path -> {from, to} map for the approver."""
    out: dict = {}
    if old.get("prompt_version") != new.get("prompt_version"):
        out["prompt_version"] = {"from": old.get("prompt_version"), "to": new.get("prompt_version")}
    if old.get("cohorts", []) != new.get("cohorts", []):
        out["cohorts"] = {"from": old.get("cohorts", []), "to": new.get("cohorts", [])}
    for cohort in sorted(set(old.get("allocations", {})) | set(new.get("allocations", {}))):
        for dim in ALLOC_DIMS:
            a = old.get("allocations", {}).get(cohort, {}).get(dim)
            b = new.get("allocations", {}).get(cohort, {}).get(dim)
            if a != b:
                out[f"allocations.{cohort}.{dim}"] = {"from": a, "to": b}
    return out


def capped_step(old: dict, new: dict, limit: float) -> dict:
    """Moves caller-ID shares only as far as one auto-apply may. Never used to chain steps."""
    out = copy.deepcopy(new)
    for cohort, alloc in out.get("allocations", {}).items():
        if "caller_id" not in alloc:
            continue
        a, b = effective(old, cohort, "caller_id"), effective(new, cohort, "caller_id")
        tv = total_variation(a, b)
        if tv > limit > 0:
            frac = limit / tv
            alloc["caller_id"] = _normalise({k: a.get(k, 0) + frac * (b.get(k, 0) - a.get(k, 0))
                                             for k in set(a) | set(b)})
    return out
