"""python -m controller run --url http://127.0.0.1:8700 [--db runs/ctl.db] [--serve]
   python -m controller why --db runs/ctl.db --wf nw_renewal --at "D3 14:00"
   python -m controller view --db runs/ctl.db
"""
import argparse
import json
import sys

from .store import Store


def main():
    ap = argparse.ArgumentParser(prog="controller")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--url", required=True)
    r.add_argument("--db", default="runs/controller.db")
    r.add_argument("--serve", action="store_true", help="serve the supervisor view on :8800")
    w = sub.add_parser("why")
    w.add_argument("--db", required=True)
    w.add_argument("--wf", required=True)
    w.add_argument("--at", required=True)
    v = sub.add_parser("view")
    v.add_argument("--db", required=True)
    a = ap.parse_args()
    if a.cmd == "run":
        import os
        from .loop import Controller
        os.makedirs(os.path.dirname(a.db) or ".", exist_ok=True)
        c = Controller(a.url, a.db)
        if a.serve:
            from .view import serve
            c.bootstrap()
            serve(c.s, c.specs)
        c.run()
    elif a.cmd == "why":
        from .audit import parse_at, why
        print(why(Store(a.db), a.wf, parse_at(a.at)))
    elif a.cmd == "view":
        from .view import build_view
        s = Store(a.db)
        specs = {r[0]: {"objective": {"primary": "?", "guardrail": {}}} for r in s.q("SELECT DISTINCT wf FROM wfstate")}
        print(json.dumps(build_view(s, specs), indent=1, default=str))


if __name__ == "__main__":
    main()
