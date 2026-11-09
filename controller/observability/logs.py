"""Structured (JSON-lines) logging. Every record carries wall-clock ts, level, msg, sim time and the active trace/span ids."""
import json
import os
import sys
import time

from .trace import current


def emit(rec: dict):
    """Default sink: one JSON object per line on stdout (CTRL_LOG_FORMAT=text for a human-readable line)."""
    if os.environ.get("CTRL_LOG_FORMAT") == "text":
        extra = " ".join(f"{k}={v}" for k, v in rec.items() if k not in ("ts", "level", "msg", "sim_ts", "trace_id", "span_id"))
        line = f"[{rec.get('sim_ts', '')}] {rec['level'].upper()} {rec['msg']} {extra}".rstrip()
    else:
        line = json.dumps(rec, default=str, separators=(",", ":"))
    print(line, file=sys.stderr if rec["level"] in ("error", "warning") else sys.stdout, flush=True)


def record(msg: str, level: str = "info", **fields) -> dict:
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + f".{int(time.time() * 1000) % 1000:03d}Z",
           "level": level, "msg": msg}
    c = current()
    if c:
        rec["trace_id"], rec["span_id"] = c
    rec.update(fields)
    return rec
