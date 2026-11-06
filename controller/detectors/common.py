"""Shared read helpers for detectors and producers (store only; no HTTP, no sim imports)."""
from __future__ import annotations

import json
from typing import Any

from ..store import Store


def latest_config(store: Store, wid: str) -> tuple[int, dict] | None:
    """Newest mirrored config; None if the newest known version has no body yet."""
    row = store.conn.execute("SELECT version, body FROM config_versions WHERE workflow_id=?"
                             " ORDER BY version DESC LIMIT 1", (wid,)).fetchone()
    if row is None or not row[1]:
        return None
    return row[0], json.loads(row[1])


def load_state(store: Store, detector: str, key: str) -> dict:
    row = store.conn.execute("SELECT value FROM detector_state WHERE detector=? AND key=?",
                             (detector, key)).fetchone()
    return json.loads(row[0]) if row else {}


def save_state(store: Store, detector: str, key: str, value: Any) -> None:
    store.conn.execute("INSERT OR REPLACE INTO detector_state(detector, key, value) VALUES (?,?,?)",
                       (detector, key, json.dumps(value, sort_keys=True)))


def credits_remaining(client) -> float:
    return float(client.credits_remaining())
