"""Thin HTTP client for the simulator. The controller talks to the world ONLY through this."""
import random
import time

import httpx

from ..observability.trace import Tracer, traceparent


class ApiError(Exception):
    def __init__(self, status: int, body):
        self.status = status
        self.body = body
        self.code = body.get("error") if isinstance(body, dict) else None
        super().__init__(f"{status} {body}")


class BreakerOpen(ConnectionError):
    """Raised immediately (no network call) while a circuit breaker is open."""


class CircuitBreaker:
    """closed -> open after `threshold` consecutive failures; after `cooldown` s one trial call (half-open) decides."""

    def __init__(self, name: str, threshold: int = 5, cooldown: float = 30.0, clock=time.monotonic, on_change=None):
        self.name, self.threshold, self.cooldown, self.clock = name, threshold, cooldown, clock
        self.on_change = on_change              # called with (name, 'open'|'closed') on real transitions
        self.fails = 0
        self.opened_at = None

    @property
    def state(self) -> str:
        if self.opened_at is None:
            return "closed"
        return "half_open" if self.clock() - self.opened_at >= self.cooldown else "open"

    def before(self):
        if self.state == "open":
            raise BreakerOpen(f"circuit '{self.name}' open; retry in {self.cooldown - (self.clock() - self.opened_at):.0f}s")

    def success(self):
        was_open = self.opened_at is not None
        self.fails, self.opened_at = 0, None
        if was_open and self.on_change:
            self.on_change(self.name, "closed")

    def failure(self):
        self.fails += 1
        if self.opened_at is not None or self.fails >= self.threshold:  # failed trial call re-opens immediately
            first = self.opened_at is None
            self.opened_at = self.clock()
            if first and self.on_change:
                self.on_change(self.name, "open")


class Api:
    def __init__(self, url: str, threshold: int = 5, cooldown: float = 30.0, tracer: Tracer | None = None,
                 metrics=None, on_breaker=None):
        self.tracer = tracer or Tracer()
        self.metrics = metrics
        self.c = httpx.Client(base_url=url, timeout=600)
        # bulkhead: reads and writes trip independently, so a failing write path never blocks polling/ingest reads
        self.breakers = {"read": CircuitBreaker("read", threshold, cooldown, on_change=on_breaker),
                         "write": CircuitBreaker("write", threshold, cooldown, on_change=on_breaker)}

    def _req(self, method: str, path: str, **kw):
        route, t0, status = "/" + path.lstrip("/").split("/")[0], time.perf_counter(), "error"
        try:
            with self.tracer.span(f"{method} {path}", method=method, path=path) as at:
                try:
                    return self._traced(method, path, at, **kw)
                finally:
                    status = str(at.get("http.status", "breaker_open" if at.get("breaker") == "open" else "error"))
        finally:
            if self.metrics:                    # low-cardinality labels: first path segment only
                self.metrics.inc("api_requests_total", method=method, route=route, status=status)
                self.metrics.observe("api_request_seconds", time.perf_counter() - t0, method=method, route=route)

    def _traced(self, method: str, path: str, at: dict, **kw):
        br = self.breakers["read" if method == "GET" else "write"]
        at["breaker"] = br.state
        br.before()
        tp = traceparent()
        if tp:
            kw["headers"] = {**kw.get("headers", {}), "traceparent": tp}
        try:
            r = self._send(method, path, **kw)
        except ConnectionError:
            br.failure()
            raise
        at["http.status"] = r.status_code
        # only server-side trouble counts; 4xx are business answers (stale_base_version, duplicate_proposal_id, 402...)
        br.failure() if r.status_code >= 500 else br.success()
        if r.status_code >= 400:
            try:
                body = r.json()
            except Exception:
                body = r.text
            raise ApiError(r.status_code, body)
        return r

    def _send(self, method: str, path: str, **kw):
        last = None
        for attempt in range(6):
            try:
                r = self.c.request(method, path, **kw)
                break
            except httpx.TransportError as e:  # simulator briefly unavailable -> retry with backoff
                last = e
                time.sleep(min(2 ** attempt, 15) * random.uniform(0.5, 1.0))  # jittered backoff
        else:
            raise ConnectionError(f"simulator unreachable: {last}")
        return r

    def get(self, path: str, **params):
        return self._req("GET", path, params=params or None).json()

    def post(self, path: str, body: dict):
        return self._req("POST", path, json=body).json()

    def put(self, path: str, body: dict):
        return self._req("PUT", path, json=body).json()

    def chunk(self, n: int) -> str:
        return self._req("GET", f"/events/chunks/{n}").text
