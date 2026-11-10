"""The controller loop (SUBMISSION §4).

    startup: fresh-or-resume -> workflows -> config sync -> ingest catch-up -> reconcile governance
    loop:    decide at the current minute -> advance -> ingest -> repeat until the scenario finishes

Decisions happen right after ingest, so they see every event up to `now`. Restarting at any point is safe:
ingest is checkpointed per chunk, governance reconciles its intent rows, and each decision pass records the
minute it last completed.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time

from . import configs, settings, status, store
from .clock import MIN_PER_DAY, Clock, fmt
from .detectors import Detectors
from .experiments import Experiments
from .governance import Governance
from .incidents import Incidents
from .ingest import Ingestor
from .sim_client import SimClient

log = logging.getLogger("controller")


class Controller:
    def __init__(self, url: str, db_path: str):
        self.client = SimClient(url)
        self.db_path = db_path
        state = self.client.state()
        self.conn = self._open_store(state)
        self.clock = Clock.from_state(state)
        self.specs = self._load_workflows()
        self.ingestor = Ingestor(self.conn, self.client, self.clock)
        self.experiments = Experiments(self.conn, self.specs)
        self.incidents = Incidents(self.conn, self.client, self.specs)
        self.detectors = Detectors(self.conn, self.specs, self.experiments, self.incidents)
        self.governance = Governance(self.conn, self.client, self.clock, self.specs,
                                     {"experiments": self.experiments, "detectors": self.detectors,
                                      "incidents": self.incidents})
        self.loop_stats: dict = {"ingest": {}}
        self.stalled_ticks = 0
        self.day_started = (None, time.perf_counter())   # (simulated day, wall clock at its start)
        _install_crash_hooks(self)

    # ------------------------------------------------------------------ startup
    def _open_store(self, state: dict):
        """Same world -> resume. Different scenario, or a world that is behind our checkpoint -> archive and start
        clean (the simulator keeps its world in memory, so a simulator restart is a new world)."""
        conn = store.connect(self.db_path)
        known = store.get_meta(conn, "scenario")
        if known is not None and (known != state["scenario"] or store.get_meta(conn, "sim_minute", 0) > state["sim_minute"]):
            conn.close()
            stamp = time.strftime("%Y%m%d-%H%M%S")
            for suffix in ("", "-wal", "-shm"):
                if os.path.exists(self.db_path + suffix):
                    os.replace(self.db_path + suffix, f"{self.db_path}.{known}.{stamp}.bak{suffix}")
            log.warning("new world (%s at %s): archived old store", state["scenario"], state["ts"])
            conn = store.connect(self.db_path)
        with store.tx(conn):
            store.set_meta(conn, "scenario", state["scenario"])
            store.set_meta(conn, "end_minute", state["end_minute"])
            if store.get_meta(conn, "credits_start") is None:
                store.set_meta(conn, "credits_start", state["credits_remaining"])
            store.set_meta(conn, "credits_remaining", state["credits_remaining"])
        return conn

    def _load_workflows(self) -> dict[str, dict]:
        specs = {w["workflow_id"]: w for w in self.client.workflows()}
        with store.tx(self.conn):
            decided = store.get_meta(self.conn, "decided_minute")
            for wf, w in specs.items():
                self.conn.execute("INSERT INTO workflows VALUES(?,?,?) ON CONFLICT(wf) DO UPDATE SET"
                                  " spec_json=excluded.spec_json", (wf, w["tenant_id"], json.dumps(w)))
                if decided is not None and store.get_meta(self.conn, f"observed_version:{wf}") is None:
                    # a store from before observed_version existed: everything up to its last decision pass was
                    # already acted on, so don't replay those edits
                    seen = self.conn.execute("SELECT COALESCE(MAX(version), 0) FROM config_versions WHERE wf=? AND"
                                             " COALESCE(minute, -1) <= ?", (wf, decided)).fetchone()[0]
                    store.set_meta(self.conn, f"observed_version:{wf}", seen)
                configs.sync(self.conn, self.client, self.clock, wf)
        return specs

    # ------------------------------------------------------------------ loop
    def run(self, max_ticks: int | None = None) -> None:
        t0 = time.perf_counter()
        st = self._ingest()                         # history bootstrap on a fresh store, catch-up on a restart
        self.loop_stats["startup_ingest_wall_s"] = round(time.perf_counter() - t0, 1)
        for wf in self.specs:
            self.governance.reconcile(wf, st["sim_minute"])
        ticks = 0
        while not st["finished"]:
            self._decide(st["sim_minute"])
            r = self.client.advance(settings.STEP_MINUTES)
            if r.status is not None and not r.ok and r.code != "finished":
                raise RuntimeError(f"advance failed: {r.status} {r.json}")
            st = self._ingest()                     # an unknown advance outcome is fine: catch-up uses the checkpoint
            self._track_day(st["sim_minute"])
            ticks += 1
            if st["finished"]:
                self._decide(st["sim_minute"])
            elif max_ticks and ticks >= max_ticks:
                break
        self._write_status(st["sim_minute"], final=True)
        log.info("finished at %s", fmt(st["sim_minute"]))

    def _track_day(self, minute: int) -> None:
        """Wall seconds per simulated day (advance + ingest + decisions): the SRE's headline number."""
        day, t0 = self.day_started
        if day is None:
            self.day_started = (minute // MIN_PER_DAY, t0)
        elif minute // MIN_PER_DAY > day:
            walls = self.loop_stats.setdefault("wall_s_per_sim_day", {})
            walls[f"D{day}"] = round(time.perf_counter() - t0, 1)
            log.info("simulated day D%s took %.1fs wall", day, walls[f"D{day}"])
            self.day_started = (minute // MIN_PER_DAY, time.perf_counter())

    def _ingest(self) -> dict:
        """Catch up on chunks, then read /sim/state once: it serves the lag check and the whole next tick."""
        t0 = time.perf_counter()
        chunks = self.ingestor.catch_up()
        events = sum(c.events for c in chunks)
        wall = time.perf_counter() - t0
        st = self.client.state()
        with store.tx(self.conn):
            store.set_meta(self.conn, "sim_minute", st["sim_minute"])
            store.set_meta(self.conn, "credits_remaining", st["credits_remaining"])
        lag = st["chunks"] - 1 - store.get_meta(self.conn, "last_chunk", -1)
        self.stalled_ticks = self.stalled_ticks + 1 if lag > 0 else 0
        total = self.loop_stats.setdefault("ingest_total", {"events": 0, "wall_s": 0.0})
        total["events"] += events
        total["wall_s"] = round(total["wall_s"] + wall, 3)
        total["events_per_s"] = round(total["events"] / total["wall_s"]) if total["wall_s"] else 0
        self.loop_stats["ingest"] = {"chunks": len(chunks), "events": events, "wall_s": round(wall, 3),
                                     "events_per_s": round(events / wall) if wall > 0 and events else 0,
                                     "lag_chunks": lag, "stalled_ticks": self.stalled_ticks}
        return st

    def _decide(self, minute: int) -> None:
        """One decision pass at `minute`. Each part commits on its own; a repeat at the same minute is a no-op."""
        if store.get_meta(self.conn, "decided_minute", -1) >= minute:
            self._guarded("governance", self.governance.step, minute)     # still drive in-flight proposals
            return
        t0 = time.perf_counter()
        for name, step in (("config observer", self._observe_config_changes), ("detectors", self.detectors.step),
                           ("incidents", self.incidents.step), ("experiments", self.experiments.step),
                           ("governance", self.governance.step)):
            self._guarded(name, step, minute)
        with store.tx(self.conn):
            store.set_meta(self.conn, "decided_minute", minute)
        self.loop_stats["decision_pass_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        self._write_status(minute)

    def _guarded(self, name: str, step, minute: int) -> None:
        """A bug or an exhausted retry in one decision step must not end the run. Its transaction rolls back, the
        traceback is logged, on-call is paged with the step name, and the loop carries on: governance state is
        persisted and reconciled, so a skipped step simply runs again next tick."""
        try:
            step(minute)
        except Exception as e:                      # noqa: BLE001 - isolation boundary, re-raised in tests
            if os.environ.get("CONTROLLER_STRICT"):
                raise
            log.exception("%s step failed at %s", name, fmt(minute))
            self.loop_stats["module_errors"] = self.loop_stats.get("module_errors", 0) + 1
            with store.tx(self.conn):
                store.raise_alert(self.conn, minute, "page", None,
                                  f"{name} step failed ({type(e).__name__}: {e}); see controller log")

    def _observe_config_changes(self, minute: int) -> None:
        """React to every version not yet *observed*. Other paths (startup, apply, stale handling) also store new
        versions, so "stored" is not "observed": a supervisor edit stored by the restart's sync must still
        invalidate experiments, start the hallucination watch and supersede incidents."""
        for wf in self.specs:
            with store.tx(self.conn):
                configs.sync(self.conn, self.client, self.clock, wf)
                seen = store.get_meta(self.conn, f"observed_version:{wf}", 0)
                rows = self.conn.execute("SELECT version, actor, changed_dims, minute FROM config_versions"
                                         " WHERE wf=? AND version>? ORDER BY version", (wf, seen)).fetchall()
                for v in rows:
                    store.set_meta(self.conn, f"observed_version:{wf}", v["version"])
                    if v["actor"] != "supervisor":
                        continue
                    dims = json.loads(v["changed_dims"])
                    store.record_decision(self.conn, minute, wf, "supervisor_edit",
                                          "supervisor edit observed: recorded and preserved",
                                          {"version": v["version"], "changed_dims": dims}, "preserve")
                    store.raise_alert(self.conn, minute, "summary", wf,
                                      f"supervisor edit v{v['version']} changed {dims}")
                    self.experiments.on_supervisor_edit(wf, dims, v["version"], minute)
                    if "prompt_version" in dims:
                        self.incidents.on_supervisor_prompt_change(wf, v["version"], minute)
                        edit_minute = v["minute"] if v["minute"] is not None else minute
                        self.detectors.start_watch(wf, edit_minute, minute)

    def _write_status(self, minute: int, final: bool = False) -> None:
        with store.tx(self.conn):
            if self.stalled_ticks > settings.PAGE_INGEST_STALL_TICKS:
                store.raise_alert(self.conn, minute, "page", None, f"ingest stalled for {self.stalled_ticks} ticks")
            if self.client.server_errors > settings.PAGE_REPEATED_5XX:
                store.raise_alert(self.conn, minute, "page", None,
                                  f"simulator returned {self.client.server_errors} consecutive 5xx/connection errors")
            start = store.get_meta(self.conn, "credits_start", 0)
            if store.get_meta(self.conn, "credits_remaining", 0) < start * settings.CREDIT_RESERVE_FRAC:
                store.raise_alert(self.conn, minute, "page", None, "credits below the incident reserve")
        snap = status.write(self.conn, minute, {**self.loop_stats, "final": final}, status.path_for(self.db_path))
        if minute % (6 * 60) == 0 or final:
            log.info("%s chunk=%s decisions/h=%s proposals=%s credits=%s", snap["sim_time"],
                     snap["ingest"]["last_chunk"], snap["decisions_last_hour"], snap["proposals_by_state"],
                     snap["credits"]["remaining"])


def _install_crash_hooks(ctl: Controller) -> None:
    """CRASH_AT=ingest:<chunk> | pending | approved : die with os._exit at that point (scripts/crash_test.py)."""
    spec = os.environ.get("CRASH_AT")
    if not spec:
        return
    if spec.startswith("ingest:"):
        n = int(spec.split(":")[1])
        ctl.ingestor.before_commit = lambda chunk: os._exit(137) if chunk == n else None
    else:
        ctl.governance.after_commit = lambda state: os._exit(137) if state == spec.upper() else None


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Outcome-first controller")
    ap.add_argument("--url", required=True)
    ap.add_argument("--db", default=settings.DB_PATH)
    ap.add_argument("--max-ticks", type=int, default=None, help="stop after N advances (testing)")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stderr)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    Controller(a.url, a.db).run(a.max_ticks)


if __name__ == "__main__":
    main()
