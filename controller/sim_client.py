"""Thin typed wrapper over the simulator's HTTP API.

Rules (SUBMISSION §9):
- 4xx never raises: the caller gets `Resp(status, json)` and decides.
- Only read-only GETs are retried (5xx / connection errors, bounded backoff).
- A mutating call that times out, drops, or returns 5xx comes back as `Resp(status=None)`: outcome UNKNOWN.
  The caller reconciles against an authoritative endpoint before doing anything else.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Iterator

import httpx

from . import settings


@dataclass
class Resp:
    status: int | None          # None = unknown outcome (timeout, connection drop, 5xx on a mutation)
    json: Any = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status is not None and 200 <= self.status < 300

    @property
    def code(self) -> str | None:
        """Simulator error code, e.g. 'stale_base_version'."""
        return self.json.get("error") if isinstance(self.json, dict) else None


class SimError(RuntimeError):
    """A read-only call failed after all retries."""


class SimClient:
    def __init__(self, base_url: str, timeout: float = settings.HTTP_TIMEOUT_S):
        self.http = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout)
        self.server_errors = 0          # consecutive 5xx/connection failures, for paging

    # ---------------------------------------------------------------- transport
    def _get(self, path: str, **params) -> Any:
        last = None
        for i, backoff in enumerate((0, *settings.GET_RETRIES)):
            if backoff:
                time.sleep(backoff)
            try:
                r = self.http.get(path, params={k: v for k, v in params.items() if v is not None})
            except httpx.HTTPError as e:
                last = repr(e)
                self.server_errors += 1
                continue
            if r.status_code >= 500:
                last = f"{r.status_code} {r.text[:200]}"
                self.server_errors += 1
                continue
            self.server_errors = 0
            if r.status_code >= 400:
                raise SimError(f"GET {path} -> {r.status_code} {r.text[:200]}")
            return r.json()
        raise SimError(f"GET {path} failed after retries: {last}")

    def _mutate(self, method: str, path: str, body: dict) -> Resp:
        try:
            r = self.http.request(method, path, json=body)
        except httpx.HTTPError as e:
            self.server_errors += 1
            return Resp(None, error=repr(e))
        try:
            payload = r.json()
        except json.JSONDecodeError:
            payload = r.text
        if r.status_code >= 500:
            self.server_errors += 1
            return Resp(None, payload, error=f"{r.status_code}")
        self.server_errors = 0
        return Resp(r.status_code, payload)

    # ---------------------------------------------------------------- reads
    def state(self) -> dict:
        return self._get("/sim/state")

    def workflows(self) -> list[dict]:
        return self._get("/workflows")

    def config(self, wf: str) -> dict:
        return self._get(f"/workflows/{wf}/config")

    def config_history(self, wf: str) -> list[dict]:
        return self._get(f"/workflows/{wf}/config/history")

    def chunks(self, kind: str, after: int = -1) -> list[dict]:
        return self._get("/events/chunks", kind=kind, after=after)

    def chunk(self, n: int) -> Iterator[bytes]:
        """Yields raw NDJSON lines. Streamed, so a 250k-event chunk never sits in memory as text."""
        for backoff in (0, *settings.GET_RETRIES):
            if backoff:
                time.sleep(backoff)
            try:
                with self.http.stream("GET", f"/events/chunks/{n}") as r:
                    if r.status_code >= 500:
                        continue
                    if r.status_code >= 400:
                        raise SimError(f"chunk {n} -> {r.status_code}")
                    buf = b""
                    for part in r.iter_bytes(1 << 20):
                        buf += part
                        *lines, buf = buf.split(b"\n")
                        yield from (ln for ln in lines if ln)
                    if buf:
                        yield buf
                    return
            except httpx.HTTPError:
                continue
        raise SimError(f"chunk {n} could not be fetched")

    def approval(self, approval_id: str) -> dict:
        return self._get(f"/approvals/{approval_id}")

    def approvals(self, workflow_id: str, status: str | None = None) -> list[dict]:
        return self._get("/approvals", workflow_id=workflow_id, status=status)

    # ---------------------------------------------------------------- mutations
    def advance(self, minutes: int) -> Resp:
        return self._mutate("POST", "/sim/advance", {"minutes": minutes})

    def submit_approval(self, body: dict) -> Resp:
        return self._mutate("POST", "/approvals", body)

    def apply(self, wf: str, approval_id: str) -> Resp:
        return self._mutate("POST", f"/workflows/{wf}/apply", {"approval_id": approval_id})

    def auto_apply(self, wf: str, body: dict) -> Resp:
        return self._mutate("PUT", f"/workflows/{wf}/config", body)

    def suggest_fixes(self, wf: str, problem: str) -> Resp:
        return self._mutate("POST", "/llm/suggest-fixes", {"workflow_id": wf, "problem": problem})

    def validate(self, wf: str, prompt_version: str, n: int) -> Resp:
        return self._mutate("POST", "/validation/runs", {"workflow_id": wf, "prompt_version": prompt_version, "n": n})
