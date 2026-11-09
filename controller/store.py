"""SQLite store: aggregates, cursors, proposals, decisions and incidents. One file, no extra infrastructure.

Crash safety rests on two rules: (1) every ingested chunk is written in ONE transaction together with its
cursor, so a chunk is either fully counted or not at all; (2) every outward call (approval request, apply,
auto-apply, validation) is preceded by a durable intent row that carries its idempotency key.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS cell(wf TEXT, code INTEGER, key TEXT, PRIMARY KEY(wf, code));
CREATE TABLE IF NOT EXISTS person(wf TEXT, idx INTEGER, code INTEGER, plast INTEGER, pconcl INTEGER,
                                  PRIMARY KEY(wf, idx));
CREATE TABLE IF NOT EXISTS agg_did(wf TEXT, hidx INTEGER, did TEXT, dials INTEGER, conn INTEGER,
                                   PRIMARY KEY(wf, hidx, did));
CREATE TABLE IF NOT EXISTS agg_hour(wf TEXT, day INTEGER, cell INTEGER, hour INTEGER, dials INTEGER, conn INTEGER,
                                    PRIMARY KEY(wf, day, cell, hour));
CREATE TABLE IF NOT EXISTS agg_var(wf TEXT, day INTEGER, cell INTEGER, dim TEXT, opt TEXT, conn INTEGER, eng INTEGER,
                                   PRIMARY KEY(wf, day, cell, dim, opt));
CREATE TABLE IF NOT EXISTS agg_prm(wf TEXT, hidx INTEGER, prompt TEXT, conn INTEGER, flags INTEGER,
                                   PRIMARY KEY(wf, hidx, prompt));
CREATE TABLE IF NOT EXISTS agg_day(wf TEXT, day INTEGER, ver INTEGER, dials INTEGER, conn INTEGER, eng INTEGER,
                                   PRIMARY KEY(wf, day, ver));
CREATE TABLE IF NOT EXISTS cfgchg(event_id INTEGER PRIMARY KEY, wf TEXT, minute INTEGER, version INTEGER,
                                  actor TEXT, dims TEXT, proposal_id TEXT, approval_id TEXT,
                                  handled INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS wfstate(wf TEXT PRIMARY KEY, js TEXT);
CREATE TABLE IF NOT EXISTS proposal(
  proposal_id TEXT PRIMARY KEY, wf TEXT, kind TEXT, state TEXT, base_version INTEGER, approval_id TEXT,
  config TEXT, body TEXT, state_patch TEXT, decision_id INTEGER, created_min INTEGER, sent_min INTEGER,
  decided_min INTEGER, applied_min INTEGER, applied_version INTEGER, reasons TEXT, dims TEXT, cfg_hash TEXT);
CREATE INDEX IF NOT EXISTS proposal_wf ON proposal(wf, state);
CREATE TABLE IF NOT EXISTS decision(
  id INTEGER PRIMARY KEY AUTOINCREMENT, minute INTEGER, wf TEXT, kind TEXT, summary TEXT, inputs TEXT, outputs TEXT,
  proposal_id TEXT);
CREATE INDEX IF NOT EXISTS decision_wf ON decision(wf, minute);
CREATE TABLE IF NOT EXISTS incident(
  id INTEGER PRIMARY KEY AUTOINCREMENT, wf TEXT, kind TEXT, state TEXT, opened_min INTEGER, closed_min INTEGER,
  js TEXT);
CREATE TABLE IF NOT EXISTS alert(id INTEGER PRIMARY KEY AUTOINCREMENT, minute INTEGER, wf TEXT, severity TEXT,
                                 code TEXT, message TEXT);
CREATE TABLE IF NOT EXISTS credit_log(id INTEGER PRIMARY KEY AUTOINCREMENT, minute INTEGER, wf TEXT, what TEXT,
                                      credits REAL, js TEXT);
CREATE TABLE IF NOT EXISTS plan_log(wf TEXT, day INTEGER, slot TEXT, minute INTEGER, PRIMARY KEY(wf, day, slot));
CREATE TABLE IF NOT EXISTS metric(minute INTEGER, name TEXT, v REAL);
"""


class Store:
    def __init__(self, path: str):
        self.path = path
        self.db = sqlite3.connect(path, isolation_level=None, timeout=60, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript(SCHEMA)
        self.lock = threading.RLock()

    @contextmanager
    def tx(self):
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield self.db
            except BaseException:
                self.db.execute("ROLLBACK")
                raise
            else:
                self.db.execute("COMMIT")

    def q(self, sql: str, args=()):
        with self.lock:
            return self.db.execute(sql, args).fetchall()

    def q1(self, sql: str, args=()):
        r = self.q(sql, args)
        return r[0] if r else None

    def x(self, sql: str, args=()):
        with self.lock:
            return self.db.execute(sql, args)

    # --- small helpers
    def kv_get(self, k, default=None):
        r = self.q1("SELECT v FROM kv WHERE k=?", (k,))
        return json.loads(r[0]) if r else default

    def kv_set(self, k, v):
        self.x("INSERT INTO kv VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, json.dumps(v)))

    def state(self, wf: str) -> dict:
        r = self.q1("SELECT js FROM wfstate WHERE wf=?", (wf,))
        return json.loads(r[0]) if r else {}

    def save_state(self, wf: str, st: dict):
        self.x("INSERT INTO wfstate VALUES(?,?) ON CONFLICT(wf) DO UPDATE SET js=excluded.js",
               (wf, json.dumps(st, sort_keys=True)))

    def decision(self, minute: int, wf: str, kind: str, summary: str, inputs=None, outputs=None, proposal_id=None):
        cur = self.x("INSERT INTO decision(minute,wf,kind,summary,inputs,outputs,proposal_id) VALUES(?,?,?,?,?,?,?)",
                     (minute, wf, kind, summary, json.dumps(inputs, default=str), json.dumps(outputs, default=str),
                      proposal_id))
        return cur.lastrowid

    def alert(self, minute: int, wf: str, severity: str, code: str, message: str):
        # one row per (wf, code, minute-day) is enough; dedupe on same code within 6h
        r = self.q1("SELECT minute FROM alert WHERE wf=? AND code=? ORDER BY id DESC LIMIT 1", (wf, code))
        if r and minute - r[0] < 360:
            return
        self.x("INSERT INTO alert(minute,wf,severity,code,message) VALUES(?,?,?,?,?)",
               (minute, wf, severity, code, message))
