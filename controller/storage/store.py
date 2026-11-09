"""Durable state: aggregates, lead features, proposals, audit trail. One SQLite file, WAL, atomic per-chunk commits.

Crash safety: a chunk's aggregates and the `last_chunk` pointer are committed in ONE transaction, so a restart
resumes at the next unprocessed chunk and never double counts.
"""
import json
import sqlite3
from pathlib import Path

import numpy as np

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS agg(wf TEXT, hr INT, key TEXT, dials REAL, conn REAL, eng REAL, flag REAL,
                               PRIMARY KEY(wf, hr, key)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS leads(lead TEXT PRIMARY KEY, day INT, age TEXT, lang TEXT) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT, sim_ts TEXT, sim_min INT, wf TEXT,
                                 kind TEXT, summary TEXT, details TEXT);
CREATE INDEX IF NOT EXISTS audit_wf ON audit(wf, sim_min);
CREATE TABLE IF NOT EXISTS proposals(proposal_id TEXT PRIMARY KEY, wf TEXT, kind TEXT, status TEXT, approval_id TEXT,
                                     base_version INT, created_min INT, dims TEXT, config TEXT, meta TEXT);
CREATE TABLE IF NOT EXISTS spans(trace_id TEXT, span_id TEXT, parent_id TEXT, name TEXT, start REAL, dur_ms REAL,
                                 status TEXT, attrs TEXT);
CREATE INDEX IF NOT EXISTS spans_trace ON spans(trace_id);
CREATE INDEX IF NOT EXISTS spans_start ON spans(start);
CREATE TABLE IF NOT EXISTS metrics(tick INT, sim_ts TEXT, events INT, ingest_ms REAL, decide_ms REAL, credits REAL);
"""


class Store:
    def __init__(self, state_dir: str):
        Path(state_dir).mkdir(parents=True, exist_ok=True)
        self.path = str(Path(state_dir) / "controller.db")
        self.db = sqlite3.connect(self.path, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript(SCHEMA)

    def reset(self):
        self.db.close()
        for suffix in ("", "-wal", "-shm"):
            Path(self.path + suffix).unlink(missing_ok=True)
        self.__init__(str(Path(self.path).parent))

    # ---- kv
    def get(self, k, default=None):
        r = self.db.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
        return json.loads(r[0]) if r else default

    def set(self, k, v):
        self.db.execute("INSERT INTO kv VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, json.dumps(v)))

    # ---- ingestion commit (atomic)
    def commit_chunk(self, agg: dict, leads: list, kv: dict, audits: list = ()):
        self.db.execute("BEGIN")
        try:
            self.db.executemany(
                "INSERT INTO agg VALUES(?,?,?,?,?,?,?) ON CONFLICT(wf,hr,key) DO UPDATE SET "
                "dials=dials+excluded.dials, conn=conn+excluded.conn, eng=eng+excluded.eng, flag=flag+excluded.flag",
                [(wf, hr, key, *v) for (wf, hr, key), v in agg.items()])
            if leads:
                self.db.executemany("INSERT OR IGNORE INTO leads VALUES(?,?,?,?)", leads)
            for k, v in kv.items():
                self.set(k, v)
            for a in audits:
                self.audit(*a)
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def load_leads(self, min_day: int) -> dict:
        return {r[0]: (r[1], r[2], r[3]) for r in self.db.execute("SELECT lead, day, age, lang FROM leads WHERE day>=?", (min_day,))}

    def prune_leads(self, min_day: int):
        self.db.execute("DELETE FROM leads WHERE day<?", (min_day,))

    # ---- windows over aggregates
    def window(self, wf: str, now_hr: int, hours: int, prefix: str, halflife: float | None = None) -> dict:
        """key -> np.array([dials, conn, eng, flag]) over (now_hr-hours, now_hr], optionally exponentially weighted."""
        out: dict[str, np.ndarray] = {}
        q = "SELECT key, hr, dials, conn, eng, flag FROM agg WHERE wf=? AND hr>? AND hr<=? AND key LIKE ?"
        for key, hr, d, c, e, f in self.db.execute(q, (wf, now_hr - hours, now_hr, prefix + "%")):
            w = 0.5 ** ((now_hr - hr) / halflife) if halflife else 1.0
            a = out.get(key)
            row = np.array([d, c, e, f]) * w
            out[key] = row if a is None else a + row
        return out

    def span_sum(self, wf: str, prefix: str, lo_hr: int, hi_hr: int):
        """Sum of [dials, conn, eng, flag] over keys with `prefix`, hours in (lo_hr, hi_hr]."""
        r = self.db.execute("SELECT SUM(dials), SUM(conn), SUM(eng), SUM(flag) FROM agg WHERE wf=? AND key LIKE ? AND hr>? AND hr<=?",
                            (wf, prefix + "%", lo_hr, hi_hr)).fetchone()
        return np.array([x or 0.0 for x in r], dtype=float)

    def alltime(self, wf: str, prefix: str) -> dict:
        out = {}
        for key, d, c, e, f in self.db.execute(
                "SELECT key, SUM(dials), SUM(conn), SUM(eng), SUM(flag) FROM agg WHERE wf=? AND key LIKE ? GROUP BY key",
                (wf, prefix + "%")):
            out[key] = np.array([d, c, e, f])
        return out

    # ---- audit
    def audit(self, sim_ts: str, sim_min: int, wf: str | None, kind: str, summary: str, details=None):
        self.db.execute("INSERT INTO audit(sim_ts, sim_min, wf, kind, summary, details) VALUES(?,?,?,?,?,?)",
                        (sim_ts, sim_min, wf, kind, summary, json.dumps(details, default=str)))

    def span(self, r: dict):
        self.db.execute("INSERT INTO spans VALUES(?,?,?,?,?,?,?,?)",
                        (r["trace_id"], r["span_id"], r["parent_id"], r["name"], r["start"], r["dur_ms"], r["status"],
                         json.dumps(r["attrs"], default=str)))

    def prune_spans(self, older_than_epoch: float) -> int:
        return self.db.execute("DELETE FROM spans WHERE start < ?", (older_than_epoch,)).rowcount

    # ---- proposals
    def put_proposal(self, p: dict):
        self.db.execute(
            "INSERT OR REPLACE INTO proposals VALUES(?,?,?,?,?,?,?,?,?,?)",
            (p["proposal_id"], p["wf"], p["kind"], p["status"], p.get("approval_id"), p["base_version"], p["created_min"],
             json.dumps(p.get("dims")), json.dumps(p["config"]), json.dumps(p.get("meta"), default=str)))

    def set_status(self, pid: str, status: str, approval_id: str | None = None):
        if approval_id:
            self.db.execute("UPDATE proposals SET status=?, approval_id=? WHERE proposal_id=?", (status, approval_id, pid))
        else:
            self.db.execute("UPDATE proposals SET status=? WHERE proposal_id=?", (status, pid))

    def proposals(self, wf: str | None = None, statuses: tuple = ()) -> list[dict]:
        q, args = "SELECT proposal_id, wf, kind, status, approval_id, base_version, created_min, dims, config, meta FROM proposals", []
        cond = []
        if wf:
            cond.append("wf=?"); args.append(wf)
        if statuses:
            cond.append(f"status IN ({','.join('?' * len(statuses))})"); args += list(statuses)
        if cond:
            q += " WHERE " + " AND ".join(cond)
        q += " ORDER BY created_min"
        return [dict(proposal_id=r[0], wf=r[1], kind=r[2], status=r[3], approval_id=r[4], base_version=r[5], created_min=r[6],
                     dims=json.loads(r[7]), config=json.loads(r[8]), meta=json.loads(r[9]) if r[9] else None)
                for r in self.db.execute(q, args)]

    def requests_in_last_24h(self, wf: str, now_min: int) -> int:
        r = self.db.execute("SELECT COUNT(*) FROM proposals WHERE wf=? AND created_min>? AND approval_id IS NOT NULL",
                            (wf, now_min - 1440)).fetchone()
        return r[0]

    def metric(self, tick, sim_ts, events, ingest_ms, decide_ms, credits):
        self.db.execute("INSERT INTO metrics VALUES(?,?,?,?,?,?)", (tick, sim_ts, events, ingest_ms, decide_ms, credits))
