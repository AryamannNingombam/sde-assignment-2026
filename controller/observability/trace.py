"""Minimal tracing: a trace_id per tick, a span_id per operation/API call, W3C `traceparent` propagation.

No external dependency. Spans nest via a contextvar (tick -> ingest/decide -> decide:<wf> -> HTTP call) and are
handed to `sink` when they finish; the controller stores them in the `spans` table.
"""
import contextvars
import secrets
import time
from contextlib import contextmanager

_cur: contextvars.ContextVar = contextvars.ContextVar("span", default=None)  # (trace_id, span_id)


def current():
    return _cur.get()


def traceparent():
    c = _cur.get()
    return f"00-{c[0]}-{c[1]}-01" if c else None


class Tracer:
    def __init__(self, sink=None):
        self.sink = sink

    @contextmanager
    def span(self, name: str, **attrs):
        parent = _cur.get()
        trace_id = parent[0] if parent else secrets.token_hex(16)
        span_id = secrets.token_hex(8)
        tok = _cur.set((trace_id, span_id))
        t0, rec = time.time(), {"trace_id": trace_id, "span_id": span_id, "parent_id": parent[1] if parent else None,
                                "name": name, "start": None, "dur_ms": None, "status": "ok", "attrs": attrs}
        rec["start"] = t0
        try:
            yield rec["attrs"]                      # caller may add attributes (e.g. http.status)
        except BaseException as e:
            rec["status"] = f"error:{type(e).__name__}"
            raise
        finally:
            rec["dur_ms"] = round((time.time() - t0) * 1000, 2)
            _cur.reset(tok)
            if self.sink:
                try:
                    self.sink(rec)
                except Exception:                   # tracing must never break the controller
                    pass
