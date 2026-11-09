"""HTTP client for the simulator with bounded retries on transport errors and 5xx."""
from __future__ import annotations

import time

import httpx


class ApiError(Exception):
    def __init__(self, status: int, body):
        super().__init__(f"{status}: {body}")
        self.status = status
        self.body = body

    @property
    def code(self):
        return self.body.get("error") if isinstance(self.body, dict) else None


class Sim:
    def __init__(self, url: str, retries: int = 6):
        self.c = httpx.Client(base_url=url, timeout=300)
        self.retries = retries

    def _req(self, method: str, path: str, **kw):
        delay = 0.5
        for attempt in range(self.retries + 1):
            try:
                r = self.c.request(method, path, **kw)
            except (httpx.TransportError, httpx.TimeoutException):
                if attempt == self.retries:
                    raise
                time.sleep(delay)
                delay = min(delay * 2, 8)
                continue
            if r.status_code >= 500 and attempt < self.retries:
                time.sleep(delay)
                delay = min(delay * 2, 8)
                continue
            if r.status_code >= 400:
                try:
                    body = r.json()
                except Exception:
                    body = r.text
                raise ApiError(r.status_code, body)
            return r
        raise RuntimeError("unreachable")

    def get(self, path, **params):
        return self._req("GET", path, params=params or None).json()

    def get_text(self, path):
        return self._req("GET", path).text

    def post(self, path, body):
        return self._req("POST", path, json=body).json()

    def put(self, path, body):
        return self._req("PUT", path, json=body).json()

    # --- typed helpers
    def state(self): return self.get("/sim/state")
    def workflows(self): return self.get("/workflows")
    def config(self, wf): return self.get(f"/workflows/{wf}/config")
    def config_history(self, wf): return self.get(f"/workflows/{wf}/config/history")
    def advance(self, minutes=15): return self.post("/sim/advance", {"minutes": minutes})
    def chunks(self, kind, after=-1): return self.get("/events/chunks", kind=kind, after=after)
    def chunk_text(self, n): return self.get_text(f"/events/chunks/{n}")
    def approvals(self, wf=None, status=None):
        p = {}
        if wf: p["workflow_id"] = wf
        if status: p["status"] = status
        return self.get("/approvals", **p)
