import httpx
import pytest

from controller.api import Api, ApiError, BreakerOpen, CircuitBreaker


class Clock:
    t = 0.0
    def __call__(self): return self.t


def test_breaker_state_machine():
    c = Clock(); b = CircuitBreaker("x", threshold=3, cooldown=10, clock=c)
    for _ in range(3): b.failure()
    assert b.state == "open"
    with pytest.raises(BreakerOpen): b.before()
    c.t = 11; assert b.state == "half_open"; b.before()
    b.failure(); assert b.state == "open"          # failed trial re-opens at once
    c.t = 30; b.success(); assert b.state == "closed" and b.fails == 0


def _api(handler, **kw):
    a = Api("http://t", **kw)
    a.c = httpx.Client(base_url="http://t", transport=httpx.MockTransport(handler))
    return a


def test_5xx_trips_but_4xx_does_not():
    a = _api(lambda r: httpx.Response(409, json={"error": "stale_base_version"}), threshold=2)
    for _ in range(5):
        with pytest.raises(ApiError): a.post("/x", {})
    assert a.breakers["write"].state == "closed"
    b = _api(lambda r: httpx.Response(503, json={}), threshold=2)
    for _ in range(2):
        with pytest.raises(ApiError): b.get("/x")
    with pytest.raises(BreakerOpen): b.get("/x")


def test_read_write_bulkhead():
    a = _api(lambda r: httpx.Response(500 if r.method == "POST" else 200, json={}), threshold=2)
    for _ in range(2):
        with pytest.raises(ApiError): a.post("/x", {})
    with pytest.raises(BreakerOpen): a.post("/x", {})
    assert a.get("/x") == {}                        # reads unaffected by the open write breaker


def test_tracing_ids_and_propagation():
    from controller.observability.trace import Tracer
    seen, spans = [], []
    def h(r): seen.append(r.headers.get("traceparent")); return httpx.Response(200, json={})
    a = _api(h); a.tracer = Tracer(spans.append)
    with a.tracer.span("tick"):
        a.get("/a"); a.post("/b", {})
    assert len({s["trace_id"] for s in spans}) == 1                  # one trace per tick
    tick = next(s for s in spans if s["name"] == "tick")
    calls = [s for s in spans if s["name"] != "tick"]
    assert all(c["parent_id"] == tick["span_id"] for c in calls) and len({c["span_id"] for c in calls}) == 2
    assert seen[0] == f"00-{calls[0]['trace_id']}-{calls[0]['span_id']}-01"   # W3C header carries the call's span id


def test_structured_log_has_trace_and_fields(tmp_path):
    import json
    from controller.core.engine import Controller
    out = []
    c = Controller("http://x", str(tmp_path), log=out.append)
    with c.tracer.span("tick") as _:
        c.log("applied", wf="w1", version=3)
    r = json.loads(json.dumps(out[0]))
    assert r["msg"] == "applied" and r["wf"] == "w1" and r["version"] == 3 and r["level"] == "info"
    assert len(r["trace_id"]) == 32 and len(r["span_id"]) == 16
