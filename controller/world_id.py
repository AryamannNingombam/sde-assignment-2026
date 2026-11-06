"""World identity: which SQLite file belongs to the simulator we are talking to."""
from __future__ import annotations

import hashlib
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path

from .client import SimClient
from .store import Store

log = logging.getLogger(__name__)
_SAFE = re.compile(r"[^A-Za-z0-9_.-]")


@dataclass(frozen=True)
class WorldId:
    scenario: str
    fingerprint: str
    anchor_chunk: int | None  # first history chunk, if any


def compute_fingerprint(scenario: str, first_line: str | None, first_event_id: int | None,
                        last_event_id: int | None) -> str:
    """scenario + hash(first line of first history chunk) + its event-id range."""
    line_hash = hashlib.sha256((first_line or "").encode()).hexdigest()[:16] if first_line else "nohist"
    raw = f"{scenario}|{line_hash}|{first_event_id}|{last_event_id}"
    return hashlib.sha256(raw.encode()).hexdigest()


def identify_world(client: SimClient) -> WorldId:
    state = client.state()
    history = client.list_chunks("history")
    if not history:
        return WorldId(state["scenario"], compute_fingerprint(state["scenario"], None, None, None), None)
    first = min(history, key=lambda c: c["chunk"])
    line = client.first_line(first["chunk"])
    fp = compute_fingerprint(state["scenario"], line, first["first_event_id"], first["last_event_id"])
    return WorldId(state["scenario"], fp, first["chunk"])


def db_path(state_dir: str | Path, world: WorldId) -> Path:
    return Path(state_dir) / f"{_SAFE.sub('_', world.scenario)}-{world.fingerprint[:8]}.db"


def open_world_store(client: SimClient, state_dir: str | Path) -> tuple[Store, WorldId, bool]:
    """Open (or create) the store for this world.

    Returns ``(store, world, fresh)``. If the simulator's ``last_event_id`` is behind
    our cursor, the simulator restarted as a new world: the stale DB is archived and
    a new one created.
    """
    world = identify_world(client)
    path = db_path(state_dir, world)
    store = Store(path)
    sim_last = client.state()["last_event_id"]
    if store.get_cursor().last_event_id > sim_last:
        log.warning("sim last_event_id %d behind cursor; archiving %s", sim_last, path)
        store.close()
        _archive(path)
        store = Store(path)
    fresh = store.get_meta("fingerprint") is None
    if fresh:
        store.set_meta("fingerprint", world.fingerprint)
        store.set_meta("scenario", world.scenario)
    return store, world, fresh


def _archive(path: Path) -> None:
    stamp = time.strftime("%Y%m%d%H%M%S")
    for suffix in ("", "-wal", "-shm"):
        src = Path(str(path) + suffix)
        if src.exists():
            src.rename(Path(str(path) + f".{stamp}.old{suffix}"))
