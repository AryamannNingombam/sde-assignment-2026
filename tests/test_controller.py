"""Tests for the controller where a bug would hurt a client: statistics, config validity, idempotent ingestion,
crash-recovery of proposals, and the rule that the controller never touches simulator internals."""
import copy
import json
import pathlib
import re

import pytest

from controller.governance import Gov
from controller.ingest import Ingestor
from controller.planner import Planner, norm, tv
from controller.simclient import ApiError
from controller.stats import benjamini_hochberg, binom_z, two_prop
from controller.store import Store


def test_controller_never_imports_the_simulator_or_reads_runs():
    for f in pathlib.Path("controller").glob("*.py"):
        src = f.read_text()
        assert not re.search(r"^\s*(from|import)\s+sim\b", src, re.M), f
        assert "_truth" not in src and "base_pickup" not in src and "did_base_health" not in src, f


def test_bh_controls_fdr_example():
    # classic example: with q=0.05 only the smallest two survive
    p = [0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205, 0.212, 0.216]
    assert benjamini_hochberg(p, 0.05) == [True, True] + [False] * 8


def test_two_prop_direction_and_binom():
    diff, z, _ = two_prop(70, 100, 50, 100)
    assert diff > 0 and z > 2
    assert binom_z(30, 100, 0.015) > 5
    assert abs(binom_z(2, 100, 0.02)) < 1e-9


def _spec(**kw):
    s = {"workflow_id": "w", "tenant_id": "t", "options": {"welcome_message": ["W1", "W2", "W3"],
         "voice": ["V1", "V2", "V3", "V4"], "caller_id": ["D1", "D2"], "prompt_version": ["P1", "P3"]},
         "objective": {"primary": "engagement_rate", "guardrail": {"pickup_rate_max_drop": 0.02}},
         "governance": {"approver_hours": [10, 19], "max_requests_per_24h": 3, "proposal_ttl_hours": 24,
                        "apply_window_hours": 2, "auto_apply": {"enabled": False, "allowed_dims": [], "max_shift": 0}},
         "dialling_window": [9, 21], "cadence": [2, 3, 3], "dials_per_hour": 300, "daily_batch": {"at_hour": 8}}
    s.update(kw)
    return s


BASE_CFG = {"cohorts": [], "allocations": {"default": {"welcome_message": {"W1": 1.0}, "voice": {"V1": 1.0},
            "caller_id": {"D1": 0.5, "D2": 0.5}}}, "prompt_version": "P1",
            "schedule": {"hour_weights": {}, "lead_preferred_hour": {}}}


def test_composite_cohorts_are_valid_ordered_and_capped(tmp_path):
    from sim.world import normalise_config      # test-only: validate against the simulator's own schema rules
    store = Store(str(tmp_path / "t.db"))
    pl = Planner(store, None, None)
    spec = _spec()
    st = pl.init_state(spec, BASE_CFG, {})
    st["v"]["voice"].update(feature="age_band", map={"60+": "V3", "46-60": "V3"}, strength={"60+": 5, "46-60": 3})
    st["v"]["welcome_message"].update(feature="lang", map={"hi": "W2", "ta": "W3"}, strength={"hi": 4, "ta": 2})
    cfg, ids = pl.build_variant_config(spec, BASE_CFG, st)
    # composites first, then singles: first-match semantics must see the most specific cohort first
    assert ids[0].count("&") == 1 and ids[-1].count("&") == 0
    assert len(ids) <= 20
    norm_cfg = normalise_config({"options": spec["options"], "dialling_window": [9, 21]}, cfg)
    for c in norm_cfg["cohorts"]:
        assert c["id"] in norm_cfg["allocations"]
    # a person in 60+ & hi gets BOTH rules
    both = next(c for c in cfg["cohorts"] if set(c["where"]) == {"age_band", "lang"})
    assert cfg["allocations"][both["id"]]["voice"].get("V3", 0) > 0.5
    assert cfg["allocations"][both["id"]]["welcome_message"].get("W2", 0) > 0.5


def test_cohort_cap_trims_weakest_levels(tmp_path):
    pl = Planner(Store(str(tmp_path / "t.db")), None, None)
    spec = _spec()
    st = pl.init_state(spec, BASE_CFG, {})
    langs = [f"l{i}" for i in range(7)]
    ages = ["18-30", "31-45", "46-60", "60+"]
    st["v"]["voice"].update(feature="age_band", map={a: "V2" for a in ages}, strength={a: i + 1 for i, a in enumerate(ages)})
    st["v"]["welcome_message"].update(feature="lang", map={l: "W2" for l in langs},
                                      strength={l: 10 + i for i, l in enumerate(langs)})
    cfg, ids = pl.build_variant_config(spec, BASE_CFG, st)
    assert len(ids) <= 20


def test_exploration_respects_control_share_and_pruning(tmp_path):
    pl = Planner(Store(str(tmp_path / "t.db")), None, None)
    spec = _spec()
    st = pl.init_state(spec, BASE_CFG, {})
    st["v"]["voice"]["prunes"] = {"V4": ["all=all"]}
    cfg, _ = pl.build_variant_config(spec, BASE_CFG, st)
    v = cfg["allocations"]["default"]["voice"]
    assert "V4" not in v and abs(sum(v.values()) - 1) < 1e-9 and v["V1"] == pytest.approx(0.5, abs=0.01)
    assert tv({"a": 1}, {"b": 1}) == 1 and norm({"a": 1, "b": 2})["b"] == pytest.approx(0.667, abs=1e-3)


def _chunk(n_calls=10):
    lines = [json.dumps({"type": "lead", "ts": "2027-01-04T08:00:00+05:30", "workflow_id": "w", "campaign_id": "w:c1",
                         "lead_id": f"w:l{i:08d}", "person_id": f"w:p{i:07d}",
                         "features": {"lang": "hi", "city_tier": "1", "age_band": "60+", "value_band": "mid"}, "event_id": i})
             for i in range(n_calls)]
    lines += [json.dumps({"type": "call", "ts": "2027-01-04T10:05:00+05:30", "workflow_id": "w", "campaign_id": "w:c1",
                          "lead_id": f"w:l{i:08d}", "person_id": f"w:p{i:07d}", "attempt_no": 1, "config_version": 1,
                          "cohort_id": "default", "variant": {"welcome_message": "W1", "voice": "V1", "caller_id": "D1",
                          "prompt_version": "P1"}, "connected": i % 2 == 0, "engaged": i % 4 == 0,
                          "qa": {"hallucination_flag": False, "flow_adherence": 0.9} if i % 2 == 0 else None,
                          "event_id": 100 + i}) for i in range(n_calls)]
    return "\n".join(lines) + "\n"


def test_ingest_is_atomic_per_chunk_and_restartable(tmp_path, monkeypatch):
    store = Store(str(tmp_path / "t.db"))
    ing = Ingestor(store)
    real = store.tx
    boom = {"on": True}

    class Boom:
        def __enter__(self_):
            self_.cm = real()
            db = self_.cm.__enter__()
            orig = db.executemany

            class Wrap:
                def __getattr__(s, k):
                    return getattr(db, k)

                def executemany(s, sql, rows):
                    orig(sql, rows)
                    if boom["on"] and "agg_var" in sql:
                        raise RuntimeError("crash mid-chunk")
            return Wrap()

        def __exit__(self_, *a):
            return self_.cm.__exit__(*a)
    monkeypatch.setattr(store, "tx", lambda: Boom())
    with pytest.raises(RuntimeError):
        ing.ingest(_chunk(), "events", 0)
    # nothing partial survived and the cursor did not move
    assert store.q1("SELECT COUNT(*) FROM agg_did")[0] == 0
    assert store.kv_get("cursor_events", -1) == -1
    boom["on"] = False
    ing.ingest(_chunk(), "events", 0)
    assert store.kv_get("cursor_events") == 0
    dials, conn = store.q1("SELECT SUM(dials), SUM(conn) FROM agg_did")
    assert (dials, conn) == (10, 5)
    # a fresh process reloads persons/cells from the store (warm restart)
    ing2 = Ingestor(store)
    assert len(ing2.persons["w"]) == 10 and ing2.cell_features("w", 1)["age_band"] == "60+"


class FakeSim:
    def __init__(self, existing=None, version=3):
        self.posts, self.existing, self.version = [], existing or [], version

    def post(self, path, body):
        self.posts.append((path, body))
        return {"approval_id": "apr_9", "status": "pending"}

    def approvals(self, wf=None, status=None):
        return self.existing

    def config(self, wf):
        return {"version": self.version}

    def config_history(self, wf):
        return []


def _intent(store, pid="w.v3.abc.a0", base=3):
    store.x("INSERT INTO proposal(proposal_id,wf,kind,state,base_version,config,body,state_patch,created_min,dims,cfg_hash)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?)", (pid, "w", "approval", "intent", base, "{}", json.dumps({"proposal_id": pid}),
                                              "{}", 0, "[]", "abc"))
    return pid


def test_crash_after_post_adopts_existing_approval_never_resends(tmp_path):
    store = Store(str(tmp_path / "t.db"))
    pid = _intent(store)
    sim = FakeSim(existing=[{"proposal_id": pid, "approval_id": "apr_7", "status": "pending"}])
    Gov(store, sim)._recover_intent("w", pid, "approval", 100)
    assert sim.posts == []
    assert store.q1("SELECT state, approval_id FROM proposal")[:2] == ("pending", "apr_7")


def test_crash_before_post_resends_only_if_base_still_current(tmp_path):
    store = Store(str(tmp_path / "t.db"))
    pid = _intent(store, base=3)
    sim = FakeSim(version=3)
    Gov(store, sim)._recover_intent("w", pid, "approval", 100)
    assert len(sim.posts) == 1 and store.q1("SELECT state FROM proposal")[0] == "pending"
    store2 = Store(str(tmp_path / "t2.db"))
    pid2 = _intent(store2, base=2)
    sim2 = FakeSim(version=3)                  # a supervisor edit moved the version while we were down
    Gov(store2, sim2)._recover_intent("w", pid2, "approval", 100)
    assert sim2.posts == [] and store2.q1("SELECT state FROM proposal")[0] == "stale"


def test_request_budget_keeps_a_slot_for_incidents_and_honours_client_cap(tmp_path):
    store = Store(str(tmp_path / "t.db"))
    g = Gov(store, FakeSim())
    spec = _spec(tenant_id="kestrel_finance")
    spec["governance"]["max_requests_per_24h"] = 4
    assert g.request_budget(spec, 100) == 1            # client cap 2, minus the incident reserve
    assert g.request_budget(spec, 100, urgent=True) == 4
    assert g.window_ok(spec, 10 * 60 + 30) is False    # Kestrel: never before 11:00
    assert g.window_ok(spec, 11 * 60) is True
    assert g.window_ok(spec, 19 * 60) is False         # approver hours end at 19:00
