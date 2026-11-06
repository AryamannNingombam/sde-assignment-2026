"""Shortened public_02-like worlds for integration tests (tests may import sim and read YAML)."""
from pathlib import Path

from fastapi.testclient import TestClient

import sim.server
from controller.client import SimClient
from sim.scenario import load_scenario
from sim.world import World

ROOT = Path(__file__).resolve().parents[2]
DAY = 1440


def when(day: int, hour: int, minute: int = 0) -> int:
    return day * DAY + hour * 60 + minute


def build(tmp_path, workflows=("ks_cancel",), days=4, history_days=6, incidents=(), credits=200):
    """public_02 reduced to the given workflows; ``incidents`` is a list of scenario incident dicts
    (``at_minute`` is filled in from ``at_minute`` given directly)."""
    sc = load_scenario(str(ROOT / "scenarios" / "public_02_incidents.yaml"))
    sc["days"], sc["history_days"], sc["credits"] = days, history_days, credits
    for t in sc["tenants"]:
        t["workflows"] = [w for w in t["workflows"] if w["id"] in workflows]
    sc["tenants"] = [t for t in sc["tenants"] if t["workflows"]]
    sc["incidents"] = [dict(i) for i in incidents]
    world = World(sc, tmp_path / "run")
    sim.server._world = world
    return world


def make_client(world):
    http = TestClient(sim.server.app)
    http.__enter__()
    return SimClient(http=http, sleep=lambda s: None), http
