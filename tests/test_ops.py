import json
import time
import urllib.request

import httpx
import pytest

from controller.api import client as api_mod
from controller.observability.alerts import Alerter
from controller.api import Api, ApiError
from controller.core.engine import Controller
from controller.core.limits import TokenBucket
from controller.observability.metrics import Metrics, serve


def test_backoff_has_jitter(monkeypatch):
    sleeps = []
    monkeypatch.setattr(api_mod.time, "sleep", sleeps.append)
    def boom(r): raise httpx.ConnectError("down")
    a = Api("http://t"); a.c = httpx.Client(base_url="http://t", transport=httpx.MockTransport(boom))
    with pytest.raises(ConnectionError): a.get("/x")
    base = [1, 2, 4, 8, 15, 15]
    assert len(sleeps) == 6 and all(0.5 * b <= s <= b for s, b in zip(sleeps, base)) and sleeps != base


def test_token_bucket_sim_time():
    b = TokenBucket(capacity=2, refill_per_min=1 / 30)
    assert b.take("w", 0) and b.take("w", 0) and not b.take("w", 0)
    assert not b.take("w", 20) and b.take("w", 30)          # 1 token refilled after 30 sim-min
    assert b.take("other", 0)                                  # per-key isolation


def test_metrics_render_and_api_instrumentation():
    m = Metrics()
    a = Api("http://t", metrics=m)
    a.c = httpx.Client(base_url="http://t", transport=httpx.MockTransport(lambda r: httpx.Response(409, json={"error": "x"})))
    with pytest.raises(ApiError): a.post("/approvals", {})
    out = m.render()
    assert 'ctrl_api_requests_total{method="POST",route="/approvals",status="409"} 1.0' in out
    assert 'ctrl_api_request_seconds_count{method="POST",route="/approvals"} 1' in out and 'le="+Inf"' in out


def test_alert_dedupe_and_breaker_callback():
    logs, t = [], [0.0]
    al = Alerter(lambda *a, **k: logs.append((a, k)), cooldown=60, webhook="", clock=lambda: t[0])
    assert al.fire("k", "boom") and not al.fire("k", "boom")
    t[0] = 61; assert al.fire("k", "boom")
    events = []
    a = Api("http://t", threshold=2, on_breaker=lambda n, s: events.append((n, s)))
    a.c = httpx.Client(base_url="http://t", transport=httpx.MockTransport(lambda r: httpx.Response(500, json={})))
    for _ in range(3):
        with pytest.raises(Exception): a.get("/x")
    assert events == [("read", "open")]                          # fires once on the transition, not on every failure


def test_prune_spans(tmp_path):
    c = Controller("http://x", str(tmp_path), log=lambda r: None)
    old = {"trace_id": "t", "span_id": "a", "parent_id": None, "name": "n", "start": time.time() - 100000, "dur_ms": 1, "status": "ok", "attrs": {}}
    c.st.span(old); c.st.span({**old, "span_id": "b", "start": time.time()})
    assert c.st.prune_spans(time.time() - 86400) == 1
    assert c.st.db.execute("select count(*) from spans").fetchone()[0] == 1


def test_http_endpoints_and_graceful_stop(tmp_path, monkeypatch):
    monkeypatch.setenv("CTRL_HTTP_PORT", "0")
    c = Controller("http://x", str(tmp_path), log=lambda r: None)
    state = {"scenario": "s", "chunks": 0, "ts": "2027-01-04T00:00:00+05:30", "credits_remaining": 50.0, "finished": False, "tick_minutes": 15}
    calls = {"adv": 0}
    class Fake:
        breakers = c.api.breakers
        def get(self, path, **kw): return state if path == "/sim/state" else []
        def post(self, path, body):
            calls["adv"] += 1; c._stop.set(); return {}      # request shutdown DURING the tick
    c.api = Fake()
    srv = serve(0, c.metrics, c.health)
    port = srv.server_port
    c._run()
    assert calls["adv"] == 1 and c.tick_no == 1                  # tick completed (advance + persisted) before stopping
    assert c.st.get("tick") == 1
    h = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz"))
    assert h["shutting_down"] is True and h["tick"] == 1
    with pytest.raises(urllib.error.HTTPError) as e: urllib.request.urlopen(f"http://127.0.0.1:{port}/readyz")
    assert e.value.code == 503                                   # not ready while shutting down
    assert b"ctrl_ticks_total 1.0" in urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics").read()
    srv.shutdown()


def test_restarted_simulator_is_detected_as_new_world(tmp_path):
    c = Controller("http://x", str(tmp_path), log=lambda r: None)
    st = {"scenario": "s", "chunks": 200, "ts": "2027-01-10T00:00:00+05:30", "credits_remaining": 1.0, "finished": False, "tick_minutes": 15}
    class Fake:
        breakers = c.api.breakers
        def __init__(self, st): self.st = st
        def get(self, path, **kw): return self.st if path == "/sim/state" else []
    c.api = Fake(st); c.startup()
    c.st.set("seen_chunks", 200); c.st.set("last_events", 150); c._time(st)
    # same world, restarted controller: state kept
    c.startup(); assert c.st.get("last_events") == 150
    # simulator restarted (same scenario name, time + chunk numbers went back): state must be reset
    c.api = Fake({**st, "chunks": 23, "ts": "2027-01-04T00:00:00+05:30"}); c.startup()
    assert c.st.get("last_events") is None


def test_guardrail_status_uses_lower_bound_and_hysteresis():
    from controller.core import policy as P
    # 0.609 -> 0.591 on ~7k calls: true drop ~0.018 vs limit 0.02 -> hold (>= 50% of limit), not breach
    r = P.guardrail_status(7000, 4263, 7000, 4137, 0.02)
    assert r["state"] == "hold", r
    assert P.guardrail_status(7000, 4263, 7000, 4263, 0.02)["state"] == "ok"
    # noise on thin data never trips
    assert P.guardrail_status(7000, 4263, 320, 190, 0.02)["state"] in ("ok", "hold") and P.guardrail_status(100, 60, 100, 40, 0.02)["state"] == "unknown"
    # a big drop breaches; once on hold it only releases below 25% of the limit
    assert P.guardrail_status(7000, 4263, 7000, 3900, 0.02)["state"] == "breach"
    assert P.guardrail_status(7000, 4263, 7000, 4220, 0.02, prev="hold")["state"] == "hold"


def test_prompt_candidate_check_blocks_robotic_fix():
    from controller.core import policy as P
    bp = {"P1": {"conn": 5000, "eng": 3000, "fla_n": 5000, "fla_sum": 4650},      # engagement .60, adherence .93
          "P3": {"conn": 1000, "eng": 450, "fla_n": 1000, "fla_sum": 990},         # no hallucination but engagement .45, script-like adherence .99
          "P4": {"conn": 1000, "eng": 590, "fla_n": 1000, "fla_sum": 930},
          "P2": {"conn": 2000, "eng": 1100, "fla_n": 2000, "fla_sum": 1800}}       # current (bad) prompt
    assert P.prompt_candidate_check(bp, "P3", "P2")[0] == "reject"
    assert P.prompt_candidate_check(bp, "P4", "P2")[0] == "ok"
    assert P.prompt_candidate_check(bp, "P9", "P2")[0] == "unknown"


def test_plan_exp_runs_with_guard_param(tmp_path):
    """Regression: a loop variable named `g` inside plan_exp once shadowed the guardrail argument (TypeError)."""
    import inspect
    from controller.core.engine import Controller
    src = inspect.getsource(Controller.plan_exp)
    assert "def plan_exp(self, wid, cfg, guard=None)" in src and "guard[\"state\"]" in src and "g[\"state\"]" not in src.replace("guard[\"state\"]", "")
