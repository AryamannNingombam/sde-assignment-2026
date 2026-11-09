"""CLI.

  python -m controller run --sim-url http://127.0.0.1:8700
  python -m controller why --workflow ks_cancel --at "D3 14:00"
  python -m controller why-call --lead nw_renewal:l00012345 [--day 3]
  python -m controller view --workflow ks_cancel
  python -m controller health
"""
import argparse
import logging
import os
import sys

DEFAULT_DB = os.environ.get("CONTROLLER_DB", "state/controller.db")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="controller")
    ap.add_argument("--db", default=DEFAULT_DB)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--sim-url", required=True)
    r.add_argument("--no-archive", action="store_true", help="skip the raw event archive that why-call reads")
    w = sub.add_parser("why")
    w.add_argument("--workflow", required=True)
    w.add_argument("--at", required=True, help="'D3 14:00' or an ISO timestamp")
    c = sub.add_parser("why-call")
    c.add_argument("--lead", required=True)
    c.add_argument("--day", type=int)
    v = sub.add_parser("view")
    v.add_argument("--workflow", required=True)
    sub.add_parser("health")
    a = ap.parse_args(argv)

    if a.cmd == "run":
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s", stream=sys.stderr)
        logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per request drowns everything else
        from .loop import Controller
        Controller(a.sim_url, a.db, archive=not a.no_archive).run()
        return 0

    from . import reports
    from .store import Store
    store = Store(a.db, read_only=True)
    if a.cmd == "why":
        print(reports.why(store, a.workflow, reports.parse_when(a.at)))
    elif a.cmd == "why-call":
        print(reports.why_call(store, os.path.join(os.path.dirname(a.db) or ".", "events"), a.lead, a.day))
    elif a.cmd == "view":
        print(reports.supervisor_view(store, a.workflow))
    elif a.cmd == "health":
        print(reports.health(store))
    return 0


if __name__ == "__main__":
    sys.exit(main())
