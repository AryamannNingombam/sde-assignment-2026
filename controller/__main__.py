"""CLI: ``python -m controller run|status``."""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from . import settings
from .client import SimClient, SimUnavailable
from .loop import Controller
from .store import Store
from .world_id import open_world_store

log = logging.getLogger("controller")


def _wait_for_sim(client: SimClient, timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            client.health()
            return
        except Exception as exc:  # noqa: BLE001 - any failure means "not up yet"
            if time.monotonic() > deadline:
                raise SimUnavailable(f"simulator not reachable: {exc}") from exc
            time.sleep(2)


def cmd_run(args: argparse.Namespace) -> int:
    client = SimClient(base_url=args.url)
    _wait_for_sim(client, settings.STARTUP_WAIT_S)
    store, world, fresh = open_world_store(client, args.state_dir)
    log.info("world %s fp=%s (%s db)", world.scenario, world.fingerprint[:8],
             "new" if fresh else "existing")
    stop = args.until_minute
    if args.max_sim_minutes is not None:
        stop = client.state()["sim_minute"] + args.max_sim_minutes
    result = Controller(client, store, stop_at_minute=stop).run()
    log.info("done: finished=%s ticks=%d sim_minute=%d events=%d", result.finished,
             result.ticks, result.sim_minute, result.stats.events)
    if not result.finished and stop is None:
        return 1
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    dbs = sorted(Path(args.state_dir).glob("*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not dbs:
        print(f"no state databases in {args.state_dir}")
        return 1
    store = Store(dbs[0])
    cursor = store.get_cursor()
    out = {"db": str(dbs[0]), "cursor": {"chunk": cursor.last_chunk, "event_id": cursor.last_event_id},
           "calls": store.count("calls"), "leads": store.count("leads"),
           "alerts": store.count("alerts"), "decisions": store.count("decisions"),
           "last_metrics": store.last_metric()}
    print(json.dumps(out, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="controller")
    sub = ap.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run")
    run.add_argument("--url", required=True)
    run.add_argument("--state-dir", default=settings.DEFAULT_STATE_DIR)
    run.add_argument("--until-minute", type=int, default=None,
                     help="dev: stop (exit 0) once sim_minute reaches this absolute minute")
    run.add_argument("--max-sim-minutes", type=int, default=None,
                     help="dev: stop (exit 0) after this many simulated minutes from now")
    status = sub.add_parser("status")
    status.add_argument("--state-dir", default=settings.DEFAULT_STATE_DIR)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return cmd_run(args) if args.cmd == "run" else cmd_status(args)


if __name__ == "__main__":
    sys.exit(main())
