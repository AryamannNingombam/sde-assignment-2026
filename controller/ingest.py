"""Chunk -> aggregates, in one transaction together with the checkpoint (SUBMISSION §4).

The chunk is the unit of idempotency: a crash before COMMIT re-reads the whole chunk, a crash after skips it.
No per-event dedupe is needed.
"""
from __future__ import annotations

import json
import sqlite3
import time
from collections import defaultdict
from dataclasses import dataclass, field

from . import store
from .clock import Clock, MIN_PER_DAY
from .cohorts import segment_of
from .sim_client import SimClient

OUTCOME_CODES = {"no_answer": 0, "voicemail": 1, "short_hangup": 2,
                 "concluded_interested": 3, "concluded_not_interested": 4}
CONCLUDED = ("concluded_interested", "concluded_not_interested")
LEAD_CACHE_DAYS = 6          # calls only reference campaigns younger than their cadence (<= ~4 days)

AGG_UPSERT = """
INSERT INTO agg(wf, hour, segment, config_version, cohort_id, wm, voice, caller_id, prompt,
                dials, connected, concluded, concluded_interested, short_hangup, halluc)
VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
ON CONFLICT(wf, hour, segment, config_version, cohort_id, wm, voice, caller_id, prompt) DO UPDATE SET
  dials=dials+excluded.dials, connected=connected+excluded.connected, concluded=concluded+excluded.concluded,
  concluded_interested=concluded_interested+excluded.concluded_interested,
  short_hangup=short_hangup+excluded.short_hangup, halluc=halluc+excluded.halluc
"""


@dataclass
class ChunkStats:
    chunk: int
    events: int = 0
    calls: int = 0
    wall_s: float = 0.0
    mismatches: int = 0          # engaged flag disagreeing with disposition
    max_minute: int | None = None
    by_type: dict = field(default_factory=lambda: defaultdict(int))


class Ingestor:
    def __init__(self, conn: sqlite3.Connection, client: SimClient, clock: Clock, *, log_calls: bool = True):
        self.conn, self.client, self.clock = conn, client, clock
        self.log_calls = log_calls
        self.before_commit = lambda chunk: None      # test hook: the crash test kills the process here
        self._reset_caches()

    def _reset_caches(self) -> None:
        self.leads: dict[str, tuple[int, str]] = {}            # lead_id -> (lead_int, segment)
        self.campaign_leads: dict[str, tuple[int, list[str]]] = {}   # campaign -> (created_minute, lead_ids)
        self.variants: dict[tuple, int] | None = None

    # ------------------------------------------------------------------ public
    def catch_up(self) -> list[ChunkStats]:
        """Ingest every chunk after the checkpoint, history first. Safe to call any number of times."""
        last = store.get_meta(self.conn, "last_chunk", -1)
        pending = sorted(self.client.chunks("history", last) + self.client.chunks("events", last),
                         key=lambda c: c["chunk"])
        out = []
        for ch in pending:
            out.append(self.ingest_chunk(ch["chunk"], ch["kind"]))
        return out

    def ingest_chunk(self, n: int, kind: str) -> ChunkStats:
        if n <= store.get_meta(self.conn, "last_chunk", -1):
            return ChunkStats(n)                                       # already committed
        t0 = time.perf_counter()
        try:
            st = self._ingest(n, kind)
        except BaseException:
            self._reset_caches()           # caches may hold assignments from the rolled-back transaction
            raise
        st.wall_s = time.perf_counter() - t0
        return st

    # ------------------------------------------------------------------ internals
    def _ingest(self, n: int, kind: str) -> ChunkStats:
        st = ChunkStats(n)
        conn, minute_of = self.conn, self.clock.minute
        if self.variants is None:
            self.variants = {(r[1], r[2], r[3], r[4]): r[0] for r in conn.execute("SELECT * FROM variant_codes")}
        next_lead = (conn.execute("SELECT COALESCE(MAX(lead_int), 0) FROM leads").fetchone()[0]) + 1
        new_variants: list[tuple] = []
        agg: dict[tuple, list[int]] = defaultdict(lambda: [0, 0, 0, 0, 0, 0])
        new_leads: list[tuple] = []
        campaigns: list[tuple] = []
        uploaded: dict[str, int] = defaultdict(int)
        concluded_by_campaign: dict[str, int] = defaultdict(int)
        concluded_leads: list[tuple] = []
        calls_log: list[tuple] = []
        log_calls = self.log_calls and kind == "events"

        for line in self.client.chunk(n):
            ev = json.loads(line)
            st.events += 1
            t = ev["type"]
            st.by_type[t] += 1
            if t == "call":
                st.calls += 1
                lead_int, seg = self._lead(ev["lead_id"], ev["campaign_id"])
                m = minute_of(ev["ts"])
                v = ev["variant"]
                disp = ev["disposition"]
                concluded = disp in CONCLUDED
                if concluded != bool(ev["engaged"]):
                    st.mismatches += 1
                halluc = bool(ev["qa"] and ev["qa"].get("hallucination_flag"))
                c = agg[(ev["workflow_id"], m // 60, seg, ev["config_version"], ev["cohort_id"],
                         v["welcome_message"], v["voice"], v["caller_id"], v["prompt_version"])]
                c[0] += 1
                c[1] += bool(ev["connected"])
                c[2] += concluded
                c[3] += disp == "concluded_interested"
                c[4] += disp == "short_hangup"
                c[5] += halluc
                if concluded:
                    concluded_by_campaign[ev["campaign_id"]] += 1
                    concluded_leads.append((lead_int,))
                if log_calls:
                    vk = (v["welcome_message"], v["voice"], v["caller_id"], v["prompt_version"])
                    code = self.variants.get(vk)
                    if code is None:
                        code = len(self.variants) + 1
                        self.variants[vk] = code
                        new_variants.append((code, *vk))
                    calls_log.append((lead_int, m, ev["attempt_no"], ev["config_version"], ev["cohort_id"], code,
                                      OUTCOME_CODES.get(disp, -1)))
                st.max_minute = m
            elif t == "lead":
                seg = segment_of(ev["features"])
                lid, cid = ev["lead_id"], ev["campaign_id"]
                self.leads[lid] = (next_lead, seg)
                self.campaign_leads.setdefault(cid, (minute_of(ev["ts"]), []))[1].append(lid)
                new_leads.append((next_lead, lid, ev["person_id"], ev["workflow_id"], cid, seg))
                next_lead += 1
                uploaded[cid] += 1
            elif t == "campaign_created":
                m = minute_of(ev["ts"])
                campaigns.append((ev["campaign_id"], ev["workflow_id"], m, ev["config_version_at_creation"],
                                  ev["leads"]))
                self.campaign_leads.setdefault(ev["campaign_id"], (m, []))
            # config_changed / approval_decided: the authoritative copies are read from the API by the
            # config sync and governance reconcile, so ingest does not need them.

        self.before_commit(n)
        with store.tx(conn):
            conn.executemany("INSERT INTO variant_codes VALUES(?,?,?,?,?)", new_variants)
            conn.executemany("INSERT INTO leads(lead_int, lead_id, person_id, wf, campaign_id, segment)"
                             " VALUES(?,?,?,?,?,?)", new_leads)
            conn.executemany("INSERT INTO campaign_kpi(campaign_id, wf, created_minute, config_version_at_creation,"
                             " declared_leads) VALUES(?,?,?,?,?)", campaigns)
            conn.executemany("UPDATE campaign_kpi SET uploaded=uploaded+? WHERE campaign_id=?",
                             [(k, cid) for cid, k in uploaded.items()])
            conn.executemany("UPDATE campaign_kpi SET concluded=concluded+? WHERE campaign_id=?",
                             [(k, cid) for cid, k in concluded_by_campaign.items()])
            conn.executemany("UPDATE leads SET concluded=1 WHERE lead_int=?", concluded_leads)
            conn.executemany(AGG_UPSERT, [(*k, *v) for k, v in agg.items()])
            conn.executemany("INSERT INTO calls_log VALUES(?,?,?,?,?,?,?)", calls_log)
            if st.mismatches:
                store.raise_alert(conn, st.max_minute or 0, "page", None,
                                  f"engaged flag disagrees with disposition on {st.mismatches} calls (chunk {n}); "
                                  "KPI definitions may have changed")
            store.set_meta(conn, "last_chunk", n)
        self._evict(st.max_minute)
        return st

    def _lead(self, lead_id: str, campaign_id: str) -> tuple[int, str]:
        hit = self.leads.get(lead_id)
        if hit is None:                     # after a restart: load the whole campaign once
            rows = self.conn.execute("SELECT lead_id, lead_int, segment, (SELECT created_minute FROM campaign_kpi"
                                     " WHERE campaign_id=?) FROM leads WHERE campaign_id=?",
                                     (campaign_id, campaign_id)).fetchall()
            ids = []
            for lid, li, seg, created in rows:
                self.leads[lid] = (li, seg)
                ids.append(lid)
            self.campaign_leads[campaign_id] = (rows[0][3] if rows else 0, ids)
            hit = self.leads[lead_id]       # KeyError here means a call for a lead we never saw: a real bug
        return hit

    def _evict(self, now: int | None) -> None:
        if now is None:
            return
        horizon = now - LEAD_CACHE_DAYS * MIN_PER_DAY
        for cid in [c for c, (m, _) in self.campaign_leads.items() if m < horizon]:
            for lid in self.campaign_leads.pop(cid)[1]:
                self.leads.pop(lid, None)
