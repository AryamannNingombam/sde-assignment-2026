"""HTTP client for the simulator: typed errors, and retries only where a retry is safe."""
from __future__ import annotations

import logging
import time
from typing import Iterator

import httpx

log = logging.getLogger("controller.client")

MAX_RETRIES = 8


class SimError(Exception):
    """A definite answer from the simulator (4xx). Never retried."""

    def __init__(self, status: int, code: str, detail):
        super().__init__(f"{status} {code}: {detail}")
        self.status, self.code, self.detail = status, code, detail


class SimUnavailable(Exception):
    """The simulator could not be reached after every retry."""


class SimClient:
    def __init__(self, url: str, timeout: float = 600.0):
        self.http = httpx.Client(base_url=url, timeout=timeout, trust_env=False)
        self.calls = 0

    def _request(self, method: str, path: str, **kw) -> httpx.Response:
        """Retries transport errors and 5xx. Writes are safe to retry because every one carries
        an idempotency key or is reconciled by the caller (see advance)."""
        for attempt in range(MAX_RETRIES):
            try:
                self.calls += 1
                r = self.http.request(method, path, **kw)
            except httpx.TransportError as e:
                log.warning("%s %s transport error (%s), attempt %d", method, path, e, attempt + 1)
            else:
                if r.status_code < 500:
                    return self._check(r)
                log.warning("%s %s returned %d, attempt %d", method, path, r.status_code, attempt + 1)
            time.sleep(min(2 ** attempt * 0.1, 5.0))
        raise SimUnavailable(f"{method} {path} failed after {MAX_RETRIES} attempts")

    @staticmethod
    def _check(r: httpx.Response) -> httpx.Response:
        if r.status_code < 400:
            return r
        try:
            body = r.json()
        except ValueError:
            body = {"error": "unparseable", "detail": r.text[:300]}
        code = body.get("error", "unknown") if isinstance(body, dict) else "unknown"
        detail = body.get("detail") if isinstance(body, dict) else body
        raise SimError(r.status_code, code, detail)

    # --- read ---------------------------------------------------------------------------------
    def state(self) -> dict:
        return self._request("GET", "/sim/state").json()

    def workflows(self) -> list[dict]:
        return self._request("GET", "/workflows").json()

    def config(self, wid: str) -> dict:
        return self._request("GET", f"/workflows/{wid}/config").json()

    def config_history(self, wid: str) -> list[dict]:
        return self._request("GET", f"/workflows/{wid}/config/history").json()

    def chunks(self, after: int) -> list[dict]:
        out = []
        for kind in ("history", "events"):
            out += self._request("GET", "/events/chunks", params={"kind": kind, "after": after}).json()
        return sorted(out, key=lambda c: c["chunk"])

    def chunk_lines(self, n: int) -> Iterator[str]:
        """Streams one chunk. A partial read raises, and the whole chunk is then re-read."""
        with self.http.stream("GET", f"/events/chunks/{n}") as r:
            if r.status_code != 200:
                r.read()
                self._check(r)
                raise SimUnavailable(f"chunk {n}: HTTP {r.status_code}")
            yield from r.iter_lines()

    def approvals(self, wid: str) -> list[dict]:
        return self._request("GET", "/approvals", params={"workflow_id": wid}).json()

    def approval(self, aid: str) -> dict:
        return self._request("GET", f"/approvals/{aid}").json()

    # --- write --------------------------------------------------------------------------------
    def advance(self, minutes: int, from_minute: int) -> dict:
        """Advance is the one write with no idempotency key, so a retry could skip time.
        Check where the simulator actually is before sending it again."""
        for attempt in range(MAX_RETRIES):
            try:
                self.calls += 1
                r = self.http.post("/sim/advance", json={"minutes": minutes})
                if r.status_code < 500:
                    return self._check(r).json()
            except httpx.TransportError as e:
                log.warning("advance transport error (%s), attempt %d", e, attempt + 1)
            time.sleep(min(2 ** attempt * 0.1, 5.0))
            st = self.state()
            if st["sim_minute"] != from_minute:
                return {"sim_minute": st["sim_minute"], "ts": st["ts"], "finished": st["finished"], "new_chunks": []}
        raise SimUnavailable("advance failed after retries")

    def request_approval(self, body: dict) -> dict:
        return self._request("POST", "/approvals", json=body).json()

    def apply(self, wid: str, approval_id: str) -> dict:
        return self._request("POST", f"/workflows/{wid}/apply", json={"approval_id": approval_id}).json()

    def auto_apply(self, wid: str, body: dict) -> dict:
        return self._request("PUT", f"/workflows/{wid}/config", json=body).json()

    def suggest_fixes(self, wid: str, problem: str) -> dict:
        return self._request("POST", "/llm/suggest-fixes", json={"workflow_id": wid, "problem": problem}).json()

    def validate(self, wid: str, prompt: str, n: int) -> dict:
        return self._request("POST", "/validation/runs",
                             json={"workflow_id": wid, "prompt_version": prompt, "n": n}).json()
