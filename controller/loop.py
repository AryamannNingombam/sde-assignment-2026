"""The control loop: ingest, decide, advance.

Decisions for a simulated minute may run more than once after a crash. Every step is safe to repeat
because each one is guarded by a status column or a once-per-day marker in the database.
"""
from __future__ import annotations

import json
import logging
import os
import time

from . import config as cfg
from .client import SimClient, SimError
from .experiments import Experiments
from .governance import Governance
from .incidents import Incidents
from .ingest import Ingestor
from .store import Store

log = logging.getLogger("controller.loop")


def rss_mb() -> float:
    try:
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
    except ImportError:
        pass
    try:
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t)]

        counters = Counters()
        counters.cb = ctypes.sizeof(Counters)
        kernel32 = ctypes.WinDLL("kernel32")
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi = ctypes.WinDLL("psapi")
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        if psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            return counters.PeakWorkingSetSize / (1024.0 * 1024.0)
    except (OSError, AttributeError):
        pass
    return -1.0


def open_store_for_world(db_path: str, state: dict) -> Store:
    """Resumes if this database belongs to the running world, otherwise sets it aside.

    The simulator's memory is the world. A fresh simulator with an old database must not resume.
    """
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    store = Store(db_path)
    known = store.get_meta("world")
    last_minute = store.get_meta("last_minute")
    last_event = store.one("SELECT MAX(last_event_id) m FROM chunks")["m"]
    different = known is not None and (known != state["scenario"] or (last_minute or 0) > state["sim_minute"]
                                       or (last_event or 0) > state["last_event_id"])
    if different:
        store.close()
        stamp = int(time.time())
        for suffix in ("", "-wal", "-shm"):
            if os.path.exists(db_path + suffix):
                os.replace(db_path + suffix, f"{db_path}.{stamp}.old{suffix}")
        log.warning("database belonged to another world; set aside with suffix .%d.old", stamp)
        store = Store(db_path)
    store.set_meta("world", state["scenario"])
    return store


class Controller:
    def __init__(self, url: str, db_path: str, archive: bool = True):
        self.client = SimClient(url)
        state = self.client.state()
        self.store = open_store_for_world(db_path, state)
        self.end_minute = state["end_minute"]
        archive_dir = os.path.join(os.path.dirname(db_path) or ".", "events") if archive else None
        self.ingestor = Ingestor(self.store, self.client, archive_dir)
        workflows = self.client.workflows()
        self.specs = {w["workflow_id"]: w for w in workflows}
        self.ingestor.set_cadences(workflows)
        with self.store.tx():
            for w in workflows:
                self.store.x("INSERT OR REPLACE INTO workflows VALUES(?,?,?)", w["workflow_id"], w["tenant_id"], json.dumps(w))
        segments = self.ingestor.seg_features
        self.gov = Governance(self.store, self.client, self.specs, segments)
        self.experiments = Experiments(self.store, self.gov, self.specs, segments, self.end_minute)
        self.incidents = Incidents(self.store, self.client, self.gov, self.specs)
        self.configs: dict[str, dict] = {}
        self.t0 = time.time()
        self.events_total = 0

    def sync_config(self, wid: str, now: int) -> dict:
        """Picks up edits we did not make. A supervisor's edit is a fact, never something to undo."""
        current = self.client.config(wid)
        version = current["version"]
        key = f"processed_version:{wid}"
        processed = self.store.get_meta(key)
        if processed == version:
            return current["config"]
        with self.store.tx():
            self.store.x("INSERT INTO config_versions(workflow_id,version,actor,changed_dims,applied_minute,config) VALUES(?,?,?,?,?,?) "
                         "ON CONFLICT DO UPDATE SET config=excluded.config", wid, version, current.get("actor"), "[]", now, json.dumps(current["config"]))
            if processed is not None:
                for row in self.store.q("SELECT * FROM config_versions WHERE workflow_id=? AND version>? ORDER BY version", wid, processed):
                    if row["actor"] == "supervisor":
                        dims = json.loads(row["changed_dims"])
                        self.store.audit(now, wid, "supervisor_edit", f"supervisor changed {dims} (v{row['version']})", {"version": row["version"], "dims": dims})
                        self.experiments.on_supervisor_edit(wid, row["version"], dims, now)
            self.store.set_meta(key, version)
        return current["config"]

    def decide(self, now: int) -> None:
        for wid in self.specs:
            config = self.sync_config(wid, now)
            self.gov.poll(wid, now)
            self.incidents.step(wid, config, now)
            if self.experiments.look_due(wid, now):
                self.experiments.plan(wid, config, now)
                self.experiments.daily(wid, config, now)
            self.gov.flush(wid, now)
        self._evaluate_alerts(now)

    def _alert(self, key: str, severity: str, message: str, now: int, active: bool) -> None:
        if active:
            self.store.x("INSERT INTO alerts VALUES(?,?,?,?,?,0) ON CONFLICT(alert_key) DO UPDATE SET message=excluded.message, last_minute=excluded.last_minute, closed=0",
                         key, severity, message, now, now)
        else:
            self.store.x("UPDATE alerts SET closed=1 WHERE alert_key=?", key)

    def _evaluate_alerts(self, now: int) -> None:
        """Pages must be actionable (memo 03), so each message names what to look at."""
        stuck = self.store.q("SELECT incident_id, workflow_id, detail FROM incidents WHERE status='open'")
        for r in stuck:
            detail = json.loads(r["detail"])
            self._alert(f"stuck:{r['incident_id']}", "page", f"Incident {r['incident_id']} needs a human: {detail.get('stuck_reason')}. "
                        f"Run: python -m controller why --workflow {r['workflow_id']}", now, detail.get("phase") == "stuck")
        credits = self.client.state()["credits_remaining"]
        self._alert("credits_low", "page", f"Only {credits:.0f} credits remain, an incident may not be fixable. Top up or lower VALIDATION_N.", now, credits < 30)
        unknown = self.ingestor.unknown_lead_calls
        self._alert("unknown_leads", "ticket", f"{unknown} calls had no lead record, so they are in cohort -1. Check ingest ordering.", now, unknown > 0)
        for wid in self.specs:
            blocked = self.store.get_meta(f"budget_blocked:{wid}")
            self._alert(f"budget:{wid}", "ticket", f"{wid}: routine changes are waiting for approval request budget.", now, blocked is not None and now - blocked < 1440)

    def run(self) -> None:
        self.incidents_ready = False
        while True:
            events, ingest_ms = self.ingestor.ingest_new()
            self.events_total += events
            state = self.client.state()
            now = state["sim_minute"]
            if not self.incidents_ready:
                self.incidents.compute_baselines()
                self.incidents_ready = True
            t = time.perf_counter()
            self.decide(now)
            decide_ms = int((time.perf_counter() - t) * 1000)
            if now % 60 == 0:
                self.ingestor.evict_old_leads(now)
            with self.store.tx():
                self.store.x("INSERT OR REPLACE INTO metrics VALUES(?,?,?,?,?,?,?)", now, events, ingest_ms, decide_ms, state["credits_remaining"], rss_mb(), time.time() - self.t0)
                self.store.set_meta("last_minute", now)
            if now % 1440 == 0:
                log.info("D%d: %d events ingested so far, %.0fs elapsed", now // 1440, self.events_total, time.time() - self.t0)
            if state["finished"]:
                log.info("scenario finished at minute %d", now)
                return
            try:
                self.client.advance(cfg.TICK_MINUTES, now)
            except SimError as e:
                if e.code == "finished" or e.status == 409:
                    log.info("simulator reports finished")
                    return
                raise
