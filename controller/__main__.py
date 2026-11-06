"""CLI: ``python -m controller run|status``."""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from . import audit, settings
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


def _latest_db(state_dir: str) -> Path | None:
    dbs = sorted(Path(state_dir).glob("*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    return dbs[0] if dbs else None


def _resolve_db(args: argparse.Namespace) -> Path | None:
    if getattr(args, "db", None):
        return Path(args.db)
    return _latest_db(args.state_dir)


def _build_why(store: Store, args: argparse.Namespace) -> tuple[dict, str] | None:
    from . import audit_render as ar
    if args.lead:
        rep = audit.why_lead(store, args.lead, args.day)
        return rep, ar.render_lead(rep)
    if not args.workflow:
        raise ValueError("--workflow is required unless --lead is given")
    if args.at:
        rep = audit.why_at(store, args.workflow, audit.parse_at(args.at))
        return rep, ar.render_at(rep)
    if args.from_ and args.to:
        rep = audit.why_range(store, args.workflow, audit.parse_bound(args.from_),
                              audit.parse_bound(args.to, end=True))
        return rep, ar.render_range(rep)
    raise ValueError("give --at, or --from and --to, or --lead")


def cmd_why(args: argparse.Namespace) -> int:
    db = _resolve_db(args)
    if db is None or not db.exists():
        print(f"no state database found ({db or args.state_dir})")
        return 1
    try:
        with Store(db) as store:
            built = _build_why(store, args)
    except ValueError as exc:
        print(exc)
        return 2
    rep, text = built  # type: ignore[misc]
    print(json.dumps(rep, indent=2, default=str) if args.json else text)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    db = _latest_db(args.state_dir)
    if db is None:
        print(f"no state databases in {args.state_dir}")
        return 1
    dbs = [db]
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
    why = sub.add_parser("why", help="explain which config was active at a time and why")
    why.add_argument("--state-dir", default=settings.DEFAULT_STATE_DIR)
    why.add_argument("--db", default=None, help="explicit database file (default: newest in --state-dir)")
    why.add_argument("--workflow")
    why.add_argument("--at", help='e.g. "Day 3 14:00"')
    why.add_argument("--from", dest="from_", help='timeline start, e.g. "Day 2"')
    why.add_argument("--to", help='timeline end (a bare day includes that whole day), e.g. "Day 4"')
    why.add_argument("--lead", help="lead id: that customer's calls and the decisions behind them")
    why.add_argument("--day", type=int, default=None, help="with --lead: only calls on this day")
    why.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return {"run": cmd_run, "status": cmd_status, "why": cmd_why}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
