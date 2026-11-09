"""SQLite store: schema, transactions, decisions and alerts.

One file, WAL mode, one writer (this process). Aggregates, not raw events (SUBMISSION §4).
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from typing import Any, Iterator

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS workflows(wf TEXT PRIMARY KEY, tenant TEXT, spec_json TEXT);

-- one row per lead; `segment` is the full feature tuple 'lang|tier|age|value'
CREATE TABLE IF NOT EXISTS leads(lead_int INTEGER PRIMARY KEY, lead_id TEXT UNIQUE, person_id TEXT, wf TEXT,
  campaign_id TEXT, segment TEXT, concluded INT DEFAULT 0, attempts INT DEFAULT 0);
CREATE INDEX IF NOT EXISTS leads_campaign ON leads(campaign_id);

-- business outcome = concluded / uploaded, per campaign
CREATE TABLE IF NOT EXISTS campaign_kpi(campaign_id TEXT PRIMARY KEY, wf TEXT, created_minute INT,
  config_version_at_creation INT, declared_leads INT, uploaded INT DEFAULT 0, concluded INT DEFAULT 0);

-- call counters per hour; each KPI is computed from its own counters
CREATE TABLE IF NOT EXISTS agg(wf TEXT, hour INT, segment TEXT, config_version INT, cohort_id TEXT,
  wm TEXT, voice TEXT, caller_id TEXT, prompt TEXT,
  dials INT, connected INT, concluded INT, concluded_interested INT, short_hangup INT, halluc INT,
  PRIMARY KEY(wf, hour, segment, config_version, cohort_id, wm, voice, caller_id, prompt));

-- per-lead call log (Compliance memo 02): integers only, variant combos in a lookup table
CREATE TABLE IF NOT EXISTS variant_codes(code INTEGER PRIMARY KEY, wm TEXT, voice TEXT, caller_id TEXT,
  prompt TEXT, UNIQUE(wm, voice, caller_id, prompt));
CREATE TABLE IF NOT EXISTS calls_log(lead_int INT, minute INT, attempt_no INT, config_version INT,
  cohort_id TEXT, variant_code INT, outcome INT);
CREATE INDEX IF NOT EXISTS calls_log_lead ON calls_log(lead_int);

CREATE TABLE IF NOT EXISTS config_versions(wf TEXT, version INT, actor TEXT, changed_dims TEXT,
  proposal_id TEXT, approval_id TEXT, minute INT, config_json TEXT, PRIMARY KEY(wf, version));

CREATE TABLE IF NOT EXISTS proposals(proposal_id TEXT PRIMARY KEY, wf TEXT, kind TEXT, path TEXT, state TEXT,
  urgent INT, base_version INT, patch_json TEXT, config_json TEXT, payload_json TEXT, refs_json TEXT,
  approval_id TEXT, apply_by_minute INT, created_minute INT, submitted_minute INT, decided_minute INT,
  applied_version INT, reasons TEXT, decision_id INT, parent_proposal_id TEXT, updated_minute INT);
CREATE INDEX IF NOT EXISTS proposals_wf_state ON proposals(wf, state);

CREATE TABLE IF NOT EXISTS experiments(id INTEGER PRIMARY KEY, wf TEXT, dim TEXT, kpi TEXT, stage INT,
  state TEXT, control TEXT, arms_json TEXT, screened_json TEXT, start_version INT, start_minute INT,
  n_required INT, looks_done INT DEFAULT 0, last_look_minute INT, carve_json TEXT, result_json TEXT,
  end_reason TEXT, derisk_expires INT, updated_minute INT);

CREATE TABLE IF NOT EXISTS decisions(id INTEGER PRIMARY KEY, minute INT, wf TEXT, kind TEXT, rule TEXT,
  inputs_json TEXT, outcome TEXT, proposal_id TEXT, experiment_id INT, incident_id INT);
CREATE INDEX IF NOT EXISTS decisions_wf_minute ON decisions(wf, minute);

CREATE TABLE IF NOT EXISTS incidents(id INTEGER PRIMARY KEY, wf TEXT, kind TEXT, opened_minute INT,
  state TEXT, credits_spent REAL DEFAULT 0, context_json TEXT, timeline_json TEXT, closed_minute INT);

-- suggest/validate intents: never auto-retried (SUBMISSION §9)
CREATE TABLE IF NOT EXISTS credit_ops(id INTEGER PRIMARY KEY, incident_id INT, kind TEXT, state TEXT,
  request_json TEXT, result_json TEXT, cost REAL, minute INT);

CREATE TABLE IF NOT EXISTS alerts(id INTEGER PRIMARY KEY, minute INT, severity TEXT, wf TEXT, message TEXT,
  resolved INT DEFAULT 0);
"""


def connect(path: str) -> sqlite3.Connection:
    if path != ":memory:":
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None)   # explicit transactions only
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.executescript(SCHEMA)
    if get_meta(conn, "schema_version") is None:
        set_meta(conn, "schema_version", SCHEMA_VERSION)
    return conn


@contextmanager
def tx(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """One atomic unit. Nested use joins the outer transaction."""
    if conn.in_transaction:
        yield conn
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def get_meta(conn: sqlite3.Connection, key: str, default: Any = None) -> Any:
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else default


def set_meta(conn: sqlite3.Connection, key: str, value: Any) -> None:
    conn.execute("INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (key, json.dumps(value)))


def record_decision(conn: sqlite3.Connection, minute: int, wf: str | None, kind: str, rule: str,
                    inputs: dict, outcome: str, *, proposal_id: str | None = None,
                    experiment_id: int | None = None, incident_id: int | None = None) -> int:
    """Every evaluation writes one row, including 'no-op'. If it's not here, it didn't happen."""
    cur = conn.execute(
        "INSERT INTO decisions(minute, wf, kind, rule, inputs_json, outcome, proposal_id, experiment_id, incident_id)"
        " VALUES(?,?,?,?,?,?,?,?,?)",
        (minute, wf, kind, rule, json.dumps(inputs, default=_json_default), outcome, proposal_id,
         experiment_id, incident_id))
    return cur.lastrowid


def raise_alert(conn: sqlite3.Connection, minute: int, severity: str, wf: str | None, message: str) -> None:
    """severity: 'page' (act now) or 'summary' (daily digest). Identical open alerts are not duplicated."""
    dup = conn.execute("SELECT 1 FROM alerts WHERE resolved=0 AND severity=? AND wf IS ? AND message=?",
                       (severity, wf, message)).fetchone()
    if not dup:
        conn.execute("INSERT INTO alerts(minute, severity, wf, message) VALUES(?,?,?,?)",
                     (minute, severity, wf, message))


def _json_default(o: Any) -> Any:
    if hasattr(o, "item"):          # numpy scalars
        return o.item()
    if isinstance(o, (set, tuple)):
        return list(o)
    raise TypeError(f"not JSON serialisable: {type(o)}")
