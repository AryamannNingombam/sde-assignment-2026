"""Event ingestion (C1) and the feature join (C2).

A chunk (NDJSON) is folded into *sufficient statistics*, never stored as raw rows: 850k events/day collapse
to a few thousand aggregate rows per workflow-day. Everything downstream (detection, experiments, call-time,
supervisor view) reads these same tables, keyed by the same feature cells, so a "cohort" has exactly one
definition. The chunk's aggregates and its cursor commit in a single transaction => idempotent + restartable.
"""
from __future__ import annotations

import json
from array import array

from .common import FEATURES, day_of, minute_of, person_idx
from .store import Store


class Persons:
    """Compact person table: feature cell code, last enrolment day, last conclusion day."""

    def __init__(self):
        self.code = array("H")
        self.plast = array("h")
        self.pconcl = array("h")

    def ensure(self, n: int):
        k = n - len(self.code)
        if k > 0:
            self.code.extend([0] * k)
            self.plast.extend([-32000] * k)
            self.pconcl.extend([-32000] * k)

    def __len__(self):
        return len(self.code)


class Ingestor:
    def __init__(self, store: Store):
        self.s = store
        self.cells: dict[str, dict[tuple, int]] = {}       # wf -> feature tuple -> code (1-based)
        self.cell_keys: dict[str, list[tuple]] = {}        # wf -> code-1 -> feature tuple
        self.persons: dict[str, Persons] = {}
        self.max_event_ts_min = 0
        self.events_total = 0
        self._unpersisted: list[tuple[str, int, tuple]] = []   # cells created in memory, not yet committed
        self._load()

    # ---------------------------------------------------------------- warm start from the store
    def _load(self):
        for wf, code, key in self.s.q("SELECT wf, code, key FROM cell ORDER BY wf, code"):
            tup = tuple(json.loads(key))
            self.cells.setdefault(wf, {})[tup] = code
            self.cell_keys.setdefault(wf, []).append(tup)
        for wf, idx, code, plast, pconcl in self.s.db.execute("SELECT wf, idx, code, plast, pconcl FROM person"):
            p = self.persons.setdefault(wf, Persons())
            p.ensure(idx + 1)
            p.code[idx], p.plast[idx], p.pconcl[idx] = code, plast, pconcl

    def cell_features(self, wf: str, code: int) -> dict | None:
        if code <= 0:
            return None
        return dict(zip(FEATURES, self.cell_keys[wf][code - 1]))

    def cell_tuple(self, wf: str, code: int) -> tuple | None:
        return self.cell_keys[wf][code - 1] if code > 0 else None

    # ---------------------------------------------------------------- chunk processing
    def ingest(self, text: str, kind: str, chunk_no: int) -> dict:
        did, hour, var, prm, day_a = {}, {}, {}, {}, {}
        dirty: dict[str, set] = {}
        cfgs, n_ev, max_min = [], 0, 0
        loads = json.loads
        for line in text.splitlines():
            if not line:
                continue
            e = loads(line)
            n_ev += 1
            t = e["type"]
            if t == "call":
                wf = e["workflow_id"]
                ts = e["ts"]
                day = day_of(ts)
                hr = int(ts[11:13])
                hidx = day * 24 + hr
                P = self.persons.get(wf)
                pi = person_idx(e["person_id"])
                code = P.code[pi] if P is not None and pi < len(P) else 0
                conn = 1 if e["connected"] else 0
                v = e["variant"]
                k = (wf, hidx, v["caller_id"])
                a = did.get(k)
                if a is None: did[k] = [1, conn]
                else: a[0] += 1; a[1] += conn
                k = (wf, day, code, hr)
                a = hour.get(k)
                if a is None: hour[k] = [1, conn]
                else: a[0] += 1; a[1] += conn
                eng = 1 if e["engaged"] else 0
                k = (wf, day, e["config_version"])
                a = day_a.get(k)
                if a is None: day_a[k] = [1, conn, eng]
                else: a[0] += 1; a[1] += conn; a[2] += eng
                if conn:
                    for dim in ("welcome_message", "voice"):
                        k = (wf, day, code, dim, v[dim])
                        a = var.get(k)
                        if a is None: var[k] = [1, eng]
                        else: a[0] += 1; a[1] += eng
                    q = e.get("qa")
                    k = (wf, hidx, v["prompt_version"])
                    a = prm.get(k)
                    fl = 1 if (q and q.get("hallucination_flag")) else 0
                    if a is None: prm[k] = [1, fl]
                    else: a[0] += 1; a[1] += fl
                if eng and P is not None and pi < len(P):
                    P.pconcl[pi] = day
                    dirty.setdefault(wf, set()).add(pi)
                m = day * 1440 + hr * 60 + int(ts[14:16])
                if m > max_min: max_min = m
            elif t == "lead":
                wf = e["workflow_id"]
                f = e["features"]
                tup = tuple(f.get(x) for x in FEATURES)
                cm = self.cells.setdefault(wf, {})
                code = cm.get(tup)
                if code is None:
                    code = cm[tup] = len(cm) + 1
                    self.cell_keys.setdefault(wf, []).append(tup)
                    self._unpersisted.append((wf, code, tup))
                pi = person_idx(e["person_id"])
                P = self.persons.setdefault(wf, Persons())
                P.ensure(pi + 1)
                P.code[pi] = code
                P.plast[pi] = day_of(e["ts"])
                dirty.setdefault(wf, set()).add(pi)
            elif t == "config_changed":
                cfgs.append((e["event_id"], e["workflow_id"], minute_of(e["ts"]), e["version"], e["actor"],
                             json.dumps(e.get("changed_dims") or []), e.get("proposal_id"), e.get("approval_id")))
        with self.s.tx() as db:
            if self._unpersisted:      # includes cells from an earlier attempt whose transaction failed
                db.executemany("INSERT OR IGNORE INTO cell VALUES(?,?,?)",
                               [(wf, c, json.dumps(list(t))) for wf, c, t in self._unpersisted])
            if dirty:
                rows = []
                for wf, idxs in dirty.items():
                    P = self.persons[wf]
                    rows += [(wf, i, P.code[i], P.plast[i], P.pconcl[i]) for i in idxs]
                db.executemany("INSERT OR REPLACE INTO person VALUES(?,?,?,?,?)", rows)
            db.executemany("INSERT INTO agg_did VALUES(?,?,?,?,?) ON CONFLICT(wf,hidx,did) DO UPDATE SET "
                           "dials=dials+excluded.dials, conn=conn+excluded.conn",
                           [(k[0], k[1], k[2], a[0], a[1]) for k, a in did.items()])
            db.executemany("INSERT INTO agg_hour VALUES(?,?,?,?,?,?) ON CONFLICT(wf,day,cell,hour) DO UPDATE SET "
                           "dials=dials+excluded.dials, conn=conn+excluded.conn",
                           [(k[0], k[1], k[2], k[3], a[0], a[1]) for k, a in hour.items()])
            db.executemany("INSERT INTO agg_var VALUES(?,?,?,?,?,?,?) ON CONFLICT(wf,day,cell,dim,opt) DO UPDATE SET "
                           "conn=conn+excluded.conn, eng=eng+excluded.eng",
                           [(k[0], k[1], k[2], k[3], k[4], a[0], a[1]) for k, a in var.items()])
            db.executemany("INSERT INTO agg_prm VALUES(?,?,?,?,?) ON CONFLICT(wf,hidx,prompt) DO UPDATE SET "
                           "conn=conn+excluded.conn, flags=flags+excluded.flags",
                           [(k[0], k[1], k[2], a[0], a[1]) for k, a in prm.items()])
            db.executemany("INSERT INTO agg_day VALUES(?,?,?,?,?,?) ON CONFLICT(wf,day,ver) DO UPDATE SET "
                           "dials=dials+excluded.dials, conn=conn+excluded.conn, eng=eng+excluded.eng",
                           [(k[0], k[1], k[2], a[0], a[1], a[2]) for k, a in day_a.items()])
            if cfgs:
                db.executemany("INSERT OR IGNORE INTO cfgchg(event_id,wf,minute,version,actor,dims,proposal_id,"
                                "approval_id) VALUES(?,?,?,?,?,?,?,?)", cfgs)
            db.execute("INSERT INTO kv VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                       (f"cursor_{kind}", json.dumps(chunk_no)))
        self._unpersisted = []
        self.events_total += n_ev
        self.max_event_ts_min = max(self.max_event_ts_min, max_min)
        return {"events": n_ev, "calls": sum(a[0] for a in did.values())}
