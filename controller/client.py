"""HTTP client for the simulator with the error taxonomy of CONTEXT.md section 8.

Policy:
* 5xx and transport errors: bounded exponential backoff, then raise
  ``SimUnavailable``.
* ``POST /sim/advance`` is never retried. On a transport/5xx failure we re-read
  ``GET /sim/state`` and treat the advance as done only if ``sim_minute`` moved.
* 4xx responses raise typed exceptions carrying the JSON body; never retried.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable, Iterator

import httpx

from . import settings

log = logging.getLogger(__name__)


class SimError(Exception):
    """A non-success response from the simulator."""

    def __init__(self, status: int, code: str, body: Any) -> None:
        super().__init__(f"{status} {code}: {body}")
        self.status = status
        self.code = code
        self.body = body


class BadRequest(SimError):
    """400."""


class Forbidden(SimError):
    """403 auto_apply_not_permitted: a pre-check bug on our side."""


class NotFound(SimError):
    """404."""


class DuplicateProposal(SimError):
    """409 duplicate_proposal_id: reconcile."""


class StaleBase(SimError):
    """409 stale_base_version: re-plan."""


class NotApproved(SimError):
    """409 not_approved: reconcile."""


class Finished(SimError):
    """409 finished: the scenario ended; exit 0."""


class Conflict(SimError):
    """Any other 409."""


class Lapsed(SimError):
    """410: the apply window passed (should be impossible)."""


class OutOfCredits(SimError):
    """402: credit reserve breached."""


class Unprocessable(SimError):
    """422: validation failure."""


class SimUnavailable(Exception):
    """Transport failure or 5xx persisted through the retry budget."""


class AdvanceNotApplied(Exception):
    """Advance failed and ``sim_minute`` did not move."""


_CONFLICT_CODES = {
    "duplicate_proposal_id": DuplicateProposal,
    "stale_base_version": StaleBase,
    "not_approved": NotApproved,
    "finished": Finished,
}
_STATUS_CLASSES = {
    400: BadRequest, 402: OutOfCredits, 403: Forbidden, 404: NotFound,
    410: Lapsed, 422: Unprocessable,
}


def _error_from(response: httpx.Response) -> SimError:
    try:
        body = response.json()
    except ValueError:
        body = {"error": "non_json", "detail": response.text[:500]}
    code = body.get("error", "unknown") if isinstance(body, dict) else "unknown"
    status = response.status_code
    if status == 409:
        return _CONFLICT_CODES.get(code, Conflict)(status, code, body)
    return _STATUS_CLASSES.get(status, SimError)(status, code, body)


class SimClient:
    """Typed wrapper over every endpoint in docs/SIMULATOR.md."""

    def __init__(self, base_url: str | None = None, http: httpx.Client | None = None,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        if http is None:
            if base_url is None:
                raise ValueError("base_url or http client required")
            http = httpx.Client(base_url=base_url, timeout=settings.HTTP_TIMEOUT_S)
        self._http = http
        self._sleep = sleep

    def close(self) -> None:
        self._http.close()

    # ------------------------------------------------------------ plumbing
    def _once(self, method: str, path: str, **kw: Any) -> httpx.Response:
        return self._http.request(method, path, **kw)

    def _request(self, method: str, path: str, **kw: Any) -> httpx.Response:
        delay = settings.RETRY_BASE_DELAY_S
        last: Exception | None = None
        for attempt in range(1, settings.RETRY_ATTEMPTS + 1):
            try:
                resp = self._once(method, path, **kw)
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last = exc
            else:
                if resp.status_code < 500:
                    if resp.status_code >= 400:
                        raise _error_from(resp)
                    return resp
                last = SimUnavailable(f"{resp.status_code} from {path}")
            log.warning("%s %s failed (attempt %d): %s", method, path, attempt, last)
            if attempt < settings.RETRY_ATTEMPTS:
                self._sleep(delay)
                delay = min(delay * 2, settings.RETRY_MAX_DELAY_S)
        raise SimUnavailable(f"{method} {path} failed after retries: {last}")

    def _json(self, method: str, path: str, **kw: Any) -> Any:
        return self._request(method, path, **kw).json()

    # ------------------------------------------------------------ read API
    def health(self) -> dict:
        return self._json("GET", "/health")

    def state(self) -> dict:
        return self._json("GET", "/sim/state")

    def workflows(self) -> list[dict]:
        return self._json("GET", "/workflows")

    def workflow(self, workflow_id: str) -> dict:
        return self._json("GET", f"/workflows/{workflow_id}")

    def get_config(self, workflow_id: str) -> dict:
        return self._json("GET", f"/workflows/{workflow_id}/config")

    def config_history(self, workflow_id: str) -> list[dict]:
        return self._json("GET", f"/workflows/{workflow_id}/config/history")

    def list_approvals(self, workflow_id: str | None = None,
                       status: str | None = None) -> list[dict]:
        params = {k: v for k, v in (("workflow_id", workflow_id), ("status", status)) if v}
        return self._json("GET", "/approvals", params=params)

    def get_approval(self, approval_id: str) -> dict:
        return self._json("GET", f"/approvals/{approval_id}")

    # ------------------------------------------------------------ events
    def list_chunks(self, kind: str, after: int = -1) -> list[dict]:
        """``kind`` is explicit: the server default is ``events``, not history."""
        if kind not in ("events", "history"):
            raise ValueError(f"bad chunk kind {kind!r}")
        return self._json("GET", "/events/chunks", params={"kind": kind, "after": after})

    def get_chunk_text(self, chunk: int) -> str:
        return self._request("GET", f"/events/chunks/{chunk}",
                             timeout=settings.CHUNK_TIMEOUT_S).text

    def first_line(self, chunk: int) -> str:
        """First NDJSON line of a chunk, without downloading the rest."""
        with self._http.stream("GET", f"/events/chunks/{chunk}",
                               timeout=settings.CHUNK_TIMEOUT_S) as resp:
            if resp.status_code >= 400:
                resp.read()
                raise _error_from(resp)
            for line in resp.iter_lines():
                return line
        return ""

    def iter_chunk_lines(self, chunk: int) -> Iterator[str]:
        for line in self.get_chunk_text(chunk).splitlines():
            if line:
                yield line

    # ------------------------------------------------------------ mutations
    def advance(self, minutes: int) -> dict:
        """Advance the sim. Never retried; recovers via ``GET /sim/state``."""
        before = self.state()["sim_minute"]
        try:
            resp = self._once("POST", "/sim/advance", json={"minutes": minutes},
                              timeout=settings.ADVANCE_TIMEOUT_S)
            if resp.status_code < 500:
                if resp.status_code >= 400:
                    raise _error_from(resp)
                return resp.json()
            failure: Exception = SimUnavailable(f"advance returned {resp.status_code}")
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            failure = exc
        log.warning("advance failed (%s); re-reading sim state", failure)
        after = self.state()
        if after["sim_minute"] > before:
            return {"sim_minute": after["sim_minute"], "ts": after["ts"],
                    "finished": after["finished"], "new_chunks": [], "recovered": True}
        raise AdvanceNotApplied(f"advance failed and sim_minute stayed {before}: {failure}")

    def request_approval(self, body: dict) -> dict:
        return self._json("POST", "/approvals", json=body)

    def apply_approval(self, workflow_id: str, approval_id: str) -> dict:
        return self._json("POST", f"/workflows/{workflow_id}/apply",
                          json={"approval_id": approval_id})

    def put_config(self, workflow_id: str, body: dict) -> dict:
        return self._json("PUT", f"/workflows/{workflow_id}/config", json=body)

    def suggest_fixes(self, workflow_id: str, problem: str) -> dict:
        return self._json("POST", "/llm/suggest-fixes",
                          json={"workflow_id": workflow_id, "problem": problem})

    def run_validation(self, workflow_id: str, prompt_version: str, n: int) -> dict:
        return self._json("POST", "/validation/runs",
                          json={"workflow_id": workflow_id, "prompt_version": prompt_version, "n": n})
