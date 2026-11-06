"""Human-readable text for the audit reports built by :mod:`controller.audit`."""
from __future__ import annotations

import json
from typing import Any

from .audit import fmt_minute

_MAX_INPUT_CHARS = 260


def _compact(inputs: Any) -> str:
    if inputs is None:
        return ""
    text = json.dumps(inputs, sort_keys=True, default=str)
    return text if len(text) <= _MAX_INPUT_CHARS else text[:_MAX_INPUT_CHARS] + "...(truncated; see --json)"


def _decision_lines(rows: list[dict], indent: str = "    ") -> list[str]:
    lines = []
    for d in rows:
        lines.append(f"{indent}{fmt_minute(d['sim_minute'])} {d['kind']}: {d['summary']}")
        if d.get("inputs") is not None:
            lines.append(f"{indent}  inputs: {_compact(d['inputs'])}")
    return lines or [f"{indent}(none)"]


def _proposal_lines(p: dict) -> list[str]:
    lines = [f"  proposal {p['proposal_id']} [{p['route']}] state={p['state']} base=v{p['base_version']}"
             f" applied=v{p['applied_version']} at {fmt_minute(p['applied_minute'])}",
             f"    summary: {p['summary']}", f"    rationale: {p['rationale']}",
             f"    impact={p['impact_score']} affected_leads={p['affected_leads']} tv={p['tv']}"]
    if p.get("dry_run"):
        lines.append(f"    dry_run: {_compact(p['dry_run'])}")
    ap = p.get("approval")
    if ap:
        lines.append(f"    approval {ap['approval_id']}: {ap['decision']} (decided_at {ap['decided_at']}) by"
                     f" {ap['approver']}; the sim exposes no approver names")
    elif p["route"] == "auto":
        lines.append("    auto-applied under the workflow's auto_apply policy (no approval)")
    lines.append("  proposal lifecycle:")
    for e in p["events"]:
        extra = e["payload"].get("note", "") if isinstance(e["payload"], dict) else e["payload"]
        lines.append(f"    {fmt_minute(e['ts_minute'])} {e['event']} {extra or ''}".rstrip())
    if p.get("superseded_by"):
        lines.append(f"    superseded-by proposals: {p['superseded_by']}")
    return lines


def render_at(r: dict[str, Any]) -> str:
    lines = [f"why {r['workflow']} at {r['at']}"]
    v = r["version"]
    if v is None:
        return "\n".join(lines + ["  no config version recorded"])
    lines.append(f"  active version v{v['version']} by {v['actor'] or 'initial'} (observed"
                 f" {fmt_minute(v['ts_minute'])}, dims {v['changed_dims']})")
    cfg = r["config"]
    if cfg:
        lines.append(f"    prompt {cfg['prompt_version']}, cohorts {cfg['cohorts']}, allocations "
                     f"{json.dumps(cfg['allocations'], sort_keys=True)[:400]}")
    p = r["proposal"]
    if p:
        lines += _proposal_lines(p)
    elif v["actor"] == "supervisor":
        lines.append("  made by the client's supervisor (bypasses governance; never silently overwritten)")
    elif v["actor"] is None:
        lines.append("  initial business configuration (no controller change yet)")
    lines.append("  our decisions for this change:")
    lines += _decision_lines(r["decisions"])
    if r["evidence"]:
        lines.append("  evidence (newest detector/test rows in the 24h before the proposal):")
        lines += _decision_lines(r["evidence"])
    lines.append("  post-apply monitoring:")
    lines += _decision_lines(r["monitoring"])
    nxt = r["superseded_by"]
    if nxt:
        nv = nxt["version"]
        lines.append(f"  superseded by v{nv['version']} ({nv['actor']}) at {fmt_minute(nv['ts_minute'])}, dims"
                     f" {nv['changed_dims']}, proposal {nv['proposal_id']}: {nxt['proposal_summary']}")
    else:
        lines.append("  not superseded within the recorded run")
    return "\n".join(lines)


def render_range(r: dict[str, Any]) -> str:
    lines = [f"timeline {r['workflow']} from {r['from']} to {r['to']} (exclusive)"]
    for e in r["events"]:
        lines.append(f"  {fmt_minute(e['minute'])}  {e['type']}: {e['text']}")
    if len(lines) == 1:
        lines.append("  (no events)")
    return "\n".join(lines)


def render_lead(r: dict[str, Any]) -> str:
    lead = r["lead"]
    if lead is None:
        return f"lead {r['lead_id']}: not found in the store"
    lines = [f"lead {lead['lead_id']} person {lead['person_id']} workflow {lead['workflow_id']} campaign"
             f" {lead['campaign_id']} (created {fmt_minute(lead['ts_minute'])}, cell {lead['cell']})"
             + (f", day {r['day']}" if r["day"] is not None else "")]
    for c in r["calls"]:
        lines.append(f"  {fmt_minute(c['ts_minute'])} attempt {c['attempt_no']} welcome {c['welcome']} voice"
                     f" {c['voice']} DID {c['caller_id']} prompt {c['prompt']} cohort {c['cohort_id']}"
                     f" connected={bool(c['connected'])} engaged={bool(c['engaged'])}")
        lines.append(f"    allocation from config v{c['config_version']}; prompt from config"
                     f" v{c['prompt_active_version']} active at the call time")
    if not r["calls"]:
        lines.append("  (no calls)")
    for ver, basis in sorted(r["versions"].items()):
        lines.append(f"  decisions behind config v{ver}:")
        if basis is None:
            lines.append("    (version not in our store)")
            continue
        v = basis["version"]
        lines.append(f"    by {v['actor'] or 'initial'} at {fmt_minute(v['ts_minute'])} dims {v['changed_dims']}")
        if basis["proposal"]:
            p = basis["proposal"]
            lines.append(f"    proposal {p['proposal_id']}: {p['summary']}")
            lines.append(f"    rationale: {p['rationale']}")
            ap = p.get("approval")
            if ap:
                lines.append(f"    approval {ap['approval_id']} {ap['decision']} at {ap['decided_at']}"
                             f" by {ap['approver']}")
        lines += _decision_lines(basis["decisions"], "    ")
    return "\n".join(lines)
