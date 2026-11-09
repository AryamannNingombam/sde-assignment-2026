"""SQLite: the only state the controller has.

WAL lets the read-only reports run while the loop writes. synchronous=FULL because the crash
guarantee depends on the row recording an intent reaching disk before the matching HTTP write.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
D0 = datetime(2027, 1, 4, tzinfo=IST)

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS workflows(workflow_id TEXT PRIMARY KEY, tenant_id TEXT, spec TEXT);
CREATE TABLE IF NOT EXISTS config_versions(
  workflow_id TEXT, version INT, actor TEXT, changed_dims TEXT, applied_minute INT,
  proposal_id TEXT, approval_id TEXT, config TEXT, PRIMARY KEY(workflow_id, version));
CREATE TABLE IF NOT EXISTS chunks(chunk INT PRIMARY KEY, kind TEXT, events INT, last_event_id INT, wall_ms INT);
CREATE TABLE IF NOT EXISTS segments(seg INT PRIMARY KEY, features TEXT);
CREATE TABLE IF NOT EXISTS leads(lead_id TEXT PRIMARY KEY, campaign_id TEXT, seg INT) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS leads_campaign ON leads(campaign_id);
CREATE TABLE IF NOT EXISTS campaigns(
  campaign_id TEXT PRIMARY KEY, workflow_id TEXT, created_minute INT, leads INT, config_version INT);
CREATE TABLE IF NOT EXISTS campaign_seg(
  campaign_id TEXT, seg INT, leads INT DEFAULT 0, concluded INT DEFAULT 0,
  PRIMARY KEY(campaign_id, seg)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS fact_hour(
  workflow_id TEXT, hour_idx INT, prompt TEXT, did TEXT,
  dials INT, connected INT, engaged INT, qa INT, halluc INT,
  PRIMARY KEY(workflow_id, hour_idx, prompt, did)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS fact_arm(
  workflow_id TEXT, day INT, config_version INT, cohort_id TEXT, seg INT,
  welcome TEXT, voice TEXT, did TEXT, prompt TEXT,
  dials INT, connected INT, engaged INT, halluc INT,
  PRIMARY KEY(workflow_id, day, config_version, cohort_id, seg, welcome, voice, did, prompt)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS cohorts(
  workflow_id TEXT, cohort_id TEXT, where_json TEXT, source TEXT, created_minute INT,
  PRIMARY KEY(workflow_id, cohort_id));
CREATE TABLE IF NOT EXISTS experiments(
  exp_id TEXT PRIMARY KEY, workflow_id TEXT, cohort_id TEXT, dim TEXT, status TEXT,
  control TEXT, arms TEXT, kpi TEXT, start_version INT, start_minute INT, end_minute INT, state TEXT);
CREATE TABLE IF NOT EXISTS promotions(
  promo_id TEXT PRIMARY KEY, workflow_id TEXT, cohort_id TEXT, dim TEXT, winner TEXT, holdout TEXT,
  kpi TEXT, lift_at_promotion REAL, version INT, status TEXT, applied_minute INT, closed_minute INT);
CREATE TABLE IF NOT EXISTS intents(
  intent_id TEXT PRIMARY KEY, workflow_id TEXT, kind TEXT, priority INT, ops TEXT, evidence TEXT,
  status TEXT, proposal_id TEXT, attempts INT DEFAULT 0, not_before INT DEFAULT 0, created_minute INT);
CREATE TABLE IF NOT EXISTS proposals(
  proposal_id TEXT PRIMARY KEY, workflow_id TEXT, route TEXT, status TEXT, base_version INT,
  approval_id TEXT, priority INT, impact REAL, summary TEXT, body TEXT, reasons TEXT,
  created_minute INT, decided_minute INT, applied_minute INT, applied_version INT);
CREATE INDEX IF NOT EXISTS proposals_open ON proposals(workflow_id, status);
CREATE TABLE IF NOT EXISTS incidents(
  incident_id TEXT PRIMARY KEY, workflow_id TEXT, kind TEXT, status TEXT, subject TEXT,
  opened_minute INT, closed_minute INT, detail TEXT);
CREATE TABLE IF NOT EXISTS did_status(
  workflow_id TEXT, did TEXT, status TEXT, since_minute INT, PRIMARY KEY(workflow_id, did));
CREATE TABLE IF NOT EXISTS credit_ledger(
  id INTEGER PRIMARY KEY AUTOINCREMENT, minute INT, workflow_id TEXT, purpose TEXT, cost REAL, ref TEXT);
CREATE TABLE IF NOT EXISTS decisions(
  id INTEGER PRIMARY KEY AUTOINCREMENT, minute INT, ts TEXT, workflow_id TEXT, kind TEXT, summary TEXT,
  detail TEXT, proposal_id TEXT, approval_id TEXT);
CREATE INDEX IF NOT EXISTS decisions_wf ON decisions(workflow_id, minute);
CREATE TABLE IF NOT EXISTS alerts(
  alert_key TEXT PRIMARY KEY, severity TEXT, message TEXT, opened_minute INT, last_minute INT, closed INT DEFAULT 0);
CREATE TABLE IF NOT EXISTS metrics(
  minute INT PRIMARY KEY, events INT, ingest_ms INT, decide_ms INT, credits REAL, rss_mb REAL, wall_s REAL);
"""


def ts_of(minute: int) -> str:
    return (D0 + timedelta(minutes=minute)).isoformat()


def minute_of(ts: str) -> int:
    return int((datetime.fromisoformat(ts) - D0).total_seconds() // 60)


class Store:
    def __init__(self, path: str, read_only: bool = False):
        uri = f"file:{path}?mode=ro" if read_only else f"file:{path}"
        self.db = sqlite3.connect(uri, uri=True, isolation_level=None, timeout=60)
        self.db.row_factory = sqlite3.Row
        self._depth = 0
        if not read_only:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.executescript(SCHEMA)

    def close(self) -> None:
        self.db.close()

    @contextmanager
    def tx(self):
        """Nested uses join the outer transaction, so helpers compose without partial commits."""
        if self._depth == 0:
            self.db.execute("BEGIN IMMEDIATE")
        self._depth += 1
        try:
            yield self.db
        except BaseException:
            self._depth -= 1
            if self._depth == 0:
                self.db.execute("ROLLBACK")
            raise
        else:
            self._depth -= 1
            if self._depth == 0:
                self.db.execute("COMMIT")

    def q(self, sql: str, *args) -> list[sqlite3.Row]:
        return self.db.execute(sql, args).fetchall()

    def one(self, sql: str, *args):
        return self.db.execute(sql, args).fetchone()

    def x(self, sql: str, *args):
        return self.db.execute(sql, args)

    def get_meta(self, key: str, default=None):
        row = self.one("SELECT value FROM meta WHERE key=?", key)
        return json.loads(row["value"]) if row else default

    def set_meta(self, key: str, value) -> None:
        self.x("INSERT INTO meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
               key, json.dumps(value))

    def audit(self, minute: int, workflow_id: str | None, kind: str, summary: str, detail: dict | None = None,
              proposal_id: str | None = None, approval_id: str | None = None) -> None:
        """Append-only: nothing in the codebase updates or deletes a decisions row."""
        self.x("INSERT INTO decisions(minute,ts,workflow_id,kind,summary,detail,proposal_id,approval_id) "
               "VALUES(?,?,?,?,?,?,?,?)", minute, ts_of(minute), workflow_id, kind, summary,
               json.dumps(detail or {}, default=str, sort_keys=True), proposal_id, approval_id)
