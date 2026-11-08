"""Chunk ingestion: each chunk's rollups and its cursor row commit in one transaction.

A kill before the commit leaves no trace of the chunk and it is re-read. A kill after the commit
means it is never read again. That makes ingestion exactly-once without per-event bookkeeping.
"""
from __future__ import annotations

import gzip
import json
import logging
import os
import time
from collections import defaultdict
from datetime import date

from .cohorts import FEATURES
from .store import Store, minute_of

log = logging.getLogger("controller.ingest")

D0_DATE = date(2027, 1, 4)
# Leads stay joinable this long after the end of their cadence, then memory is released.
LEAD_RETENTION_EXTRA_DAYS = 2


class Ingestor:
    def __init__(self, store: Store, client, archive_dir: str | None = None):
        self.store, self.client, self.archive_dir = store, client, archive_dir
        self.seg_ids: dict[tuple, int] = {}
        self.seg_features: dict[int, dict] = {}
        self.lead_seg: dict[str, int] = {}
        self.campaign_leads: dict[str, list[str]] = defaultdict(list)
        self.campaign_wf: dict[str, str] = {}
        self.campaign_day: dict[str, int] = {}
        self.max_cadence_days: dict[str, int] = {}
        self.unknown_lead_calls = 0
        self._day_cache: dict[str, int] = {}
        self._load()

    def _load(self) -> None:
        """Rebuilds the in-memory join after a restart. The database is the source of truth."""
        for r in self.store.q("SELECT seg, features FROM segments"):
            feats = json.loads(r["features"])
            self.seg_ids[tuple(feats.get(f) for f in FEATURES)] = r["seg"]
            self.seg_features[r["seg"]] = feats
        for r in self.store.q("SELECT campaign_id, workflow_id, created_minute FROM campaigns"):
            self.campaign_wf[r["campaign_id"]] = r["workflow_id"]
            self.campaign_day[r["campaign_id"]] = r["created_minute"] // 1440
        for r in self.store.q("SELECT lead_id, campaign_id, seg FROM leads"):
            self.lead_seg[r["lead_id"]] = r["seg"]
            self.campaign_leads[r["campaign_id"]].append(r["lead_id"])

    def set_cadences(self, workflows: list[dict]) -> None:
        self.max_cadence_days = {w["workflow_id"]: len(w["cadence"]) for w in workflows}

    def cursor(self) -> int:
        row = self.store.one("SELECT MAX(chunk) AS c FROM chunks")
        return -1 if row["c"] is None else row["c"]

    def ingest_new(self) -> tuple[int, int]:
        """Returns (events, milliseconds)."""
        events, t0 = 0, time.perf_counter()
        for meta in self.client.chunks(self.cursor()):
            events += self._ingest_chunk(meta)
        return events, int((time.perf_counter() - t0) * 1000)

    def _day(self, ts: str) -> int:
        key = ts[:10]
        day = self._day_cache.get(key)
        if day is None:
            day = self._day_cache[key] = (date.fromisoformat(key) - D0_DATE).days
        return day

    def _segment(self, feats: dict, new_segments: list) -> int:
        key = tuple(feats.get(f) for f in FEATURES)
        seg = self.seg_ids.get(key)
        if seg is None:
            seg = self.seg_ids[key] = len(self.seg_ids)
            self.seg_features[seg] = feats
            new_segments.append((seg, json.dumps(feats, sort_keys=True)))
        return seg

    def _ingest_chunk(self, meta: dict) -> int:
        t0 = time.perf_counter()
        chunk = meta["chunk"]
        hour_agg: dict[tuple, list[int]] = {}
        arm_agg: dict[tuple, list[int]] = {}
        seg_agg: dict[tuple, list[int]] = {}
        leads, campaigns, new_segments, config_events, new_lead_ids = [], [], [], [], []
        added_segments: list[int] = []
        events = 0
        loads = json.loads
        archive = None
        tmp_path = final_path = None
        if self.archive_dir and meta["kind"] == "events":
            os.makedirs(self.archive_dir, exist_ok=True)
            final_path = os.path.join(self.archive_dir, f"{chunk:06d}.ndjson.gz")
            tmp_path = final_path + ".tmp"
            archive = gzip.open(tmp_path, "wt", compresslevel=1, encoding="utf-8")
        try:
            for line in self.client.chunk_lines(chunk):
                if not line:
                    continue
                events += 1
                if archive:
                    archive.write(line + "\n")
                ev = loads(line)
                etype = ev["type"]
                if etype == "call":
                    self._add_call(ev, hour_agg, arm_agg, seg_agg)
                elif etype == "lead":
                    before = len(self.seg_ids)
                    seg = self._segment(ev["features"], new_segments)
                    if len(self.seg_ids) != before:
                        added_segments.append(seg)
                    lead_id, campaign_id = ev["lead_id"], ev["campaign_id"]
                    if lead_id not in self.lead_seg:
                        new_lead_ids.append((lead_id, campaign_id))
                    self.lead_seg[lead_id] = seg
                    leads.append((lead_id, campaign_id, seg))
                    seg_agg.setdefault((campaign_id, seg), [0, 0])[0] += 1
                elif etype == "campaign_created":
                    campaigns.append((ev["campaign_id"], ev["workflow_id"], minute_of(ev["ts"]), ev["leads"],
                                      ev["config_version_at_creation"]))
                elif etype == "config_changed":
                    config_events.append(ev)
        except BaseException:
            # A failed read must not leave partial joins behind: restore them from the database.
            for lead_id, _ in new_lead_ids:
                self.lead_seg.pop(lead_id, None)
            for seg in added_segments:
                feats = self.seg_features.pop(seg)
                self.seg_ids.pop(tuple(feats.get(f) for f in FEATURES), None)
            raise
        finally:
            if archive:
                archive.close()
        if tmp_path:
            os.replace(tmp_path, final_path)

        with self.store.tx() as db:
            db.executemany("INSERT OR REPLACE INTO segments VALUES(?,?)", new_segments)
            db.executemany("INSERT OR REPLACE INTO campaigns VALUES(?,?,?,?,?)", campaigns)
            db.executemany("INSERT OR REPLACE INTO leads VALUES(?,?,?)", leads)
            db.executemany(
                "INSERT INTO campaign_seg VALUES(?,?,?,?) ON CONFLICT(campaign_id,seg) DO UPDATE SET "
                "leads=leads+excluded.leads, concluded=concluded+excluded.concluded",
                [(c, s, v[0], v[1]) for (c, s), v in seg_agg.items()])
            db.executemany(
                "INSERT INTO fact_hour VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT DO UPDATE SET dials=dials+excluded.dials,"
                "connected=connected+excluded.connected, engaged=engaged+excluded.engaged, qa=qa+excluded.qa,"
                "halluc=halluc+excluded.halluc", [k + tuple(v) for k, v in hour_agg.items()])
            db.executemany(
                "INSERT INTO fact_arm VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO UPDATE SET dials=dials+excluded.dials,"
                "connected=connected+excluded.connected, engaged=engaged+excluded.engaged,"
                "halluc=halluc+excluded.halluc", [k + tuple(v) for k, v in arm_agg.items()])
            for ev in config_events:
                db.execute(
                    "INSERT INTO config_versions(workflow_id,version,actor,changed_dims,applied_minute,proposal_id,approval_id)"
                    " VALUES(?,?,?,?,?,?,?) ON CONFLICT DO UPDATE SET actor=excluded.actor, changed_dims=excluded.changed_dims,"
                    " applied_minute=excluded.applied_minute, proposal_id=excluded.proposal_id,"
                    " approval_id=excluded.approval_id",
                    (ev["workflow_id"], ev["version"], ev["actor"], json.dumps(ev["changed_dims"]), minute_of(ev["ts"]),
                     ev.get("proposal_id"), ev.get("approval_id")))
            db.execute("INSERT INTO chunks VALUES(?,?,?,?,?)",
                       (chunk, meta["kind"], events, meta.get("last_event_id"), int((time.perf_counter() - t0) * 1000)))
        for campaign_id, workflow_id, created, *_ in campaigns:
            self.campaign_wf[campaign_id] = workflow_id
            self.campaign_day[campaign_id] = created // 1440
        for lead_id, campaign_id, _ in leads:
            self.campaign_leads[campaign_id].append(lead_id)
        return events

    def _add_call(self, ev, hour_agg, arm_agg, seg_agg) -> None:
        ts = ev["ts"]
        day = self._day(ts)
        hour = int(ts[11:13])
        wf = ev["workflow_id"]
        variant = ev["variant"]
        prompt, did = variant["prompt_version"], variant["caller_id"]
        connected = 1 if ev["connected"] else 0
        engaged = 1 if ev["engaged"] else 0
        qa = ev.get("qa")
        halluc = 1 if qa and qa.get("hallucination_flag") else 0
        qa_n = 1 if qa else 0

        h = hour_agg.get((wf, day * 24 + hour, prompt, did))
        if h is None:
            h = hour_agg[(wf, day * 24 + hour, prompt, did)] = [0, 0, 0, 0, 0]
        h[0] += 1
        h[1] += connected
        h[2] += engaged
        h[3] += qa_n
        h[4] += halluc

        seg = self.lead_seg.get(ev["lead_id"])
        if seg is None:
            self.unknown_lead_calls += 1
            seg = -1
        key = (wf, day, ev["config_version"], ev["cohort_id"], seg, variant["welcome_message"], variant["voice"], did, prompt)
        a = arm_agg.get(key)
        if a is None:
            a = arm_agg[key] = [0, 0, 0, 0]
        a[0] += 1
        a[1] += connected
        a[2] += engaged
        a[3] += halluc
        if engaged:
            seg_agg.setdefault((ev["campaign_id"], seg), [0, 0])[1] += 1

    def evict_old_leads(self, minute: int) -> int:
        """Drops the lead join for campaigns past their cadence. Rollups are kept forever."""
        today = minute // 1440
        dropped = 0
        expired = []
        for campaign_id, created_day in self.campaign_day.items():
            if campaign_id not in self.campaign_leads:
                continue
            cadence = self.max_cadence_days.get(self.campaign_wf.get(campaign_id, ""), 3)
            if today - created_day > cadence + LEAD_RETENTION_EXTRA_DAYS:
                expired.append(campaign_id)
        if not expired:
            return 0
        with self.store.tx() as db:
            for campaign_id in expired:
                db.execute("DELETE FROM leads WHERE campaign_id=?", (campaign_id,))
        for campaign_id in expired:
            for lead_id in self.campaign_leads.pop(campaign_id):
                self.lead_seg.pop(lead_id, None)
                dropped += 1
        return dropped
