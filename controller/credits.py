"""Credit-costing calls (suggest-fixes, validation runs) with a recorded ledger.

Those calls are never retried (a retry would pay twice). If one fails in transit we do not
know whether it was charged, so the spend is reconciled from ``/sim/state``
``credits_remaining`` and recorded; the caller decides whether to ask again.
"""
from __future__ import annotations

import json
from typing import Any, Callable

from .client import OutcomeUnknown, SimClient
from .store import Store


def call_with_credit_ledger(client: SimClient, store: Store, workflow_id: str, minute: int,
                            description: str, call: Callable[..., Any], *args: Any) -> Any:
    before = client.credits_remaining()
    try:
        response = call(*args)
    except OutcomeUnknown:
        spent = round(before - client.credits_remaining(), 4)
        _record(store, workflow_id, minute, spent, description, "outcome_unknown")
        store.add_decision(minute, "credit_outcome_unknown",
                           f"{description}: transport failure, {spent} credits charged", workflow_id,
                           {"credits": spent})
        raise
    spent = round(before - float(response.get("credits_remaining", before)), 4)
    _record(store, workflow_id, minute, spent, description, json.dumps(response, sort_keys=True))
    return response


def _record(store: Store, workflow_id: str, minute: int, credits: float, request: str,
            response: str) -> None:
    store.conn.execute("INSERT INTO llm_calls(workflow_id, sim_minute, credits, request, response)"
                       " VALUES (?,?,?,?,?)", (workflow_id, minute, credits, request, response))
