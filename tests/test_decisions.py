"""Decision logic against a scripted world: detectors, stopping rules, governance, crash recovery."""
import json

import pytest

from controller import config as cfg
from controller import configops as co
from controller import stats
from controller.client import SimError
from controller.experiments import Experiments
from controller.governance import Governance
from controller.incidents import Incidents
from controller.store import Store

WID = "w1"
TEN = 600  # D0 10:00


def spec(**over):
    gov = {"auto_apply": {"enabled": True, "allowed_dims": ["caller_id", "schedule"], "max_shift": 0.5},
           "approver_hours": [10, 19], "approver_latency_minutes": [30, 240], "proposal_ttl_hours": 24,
           "apply_window_hours": 2, "max_requests_per_24h": 3, "base_reject_rate": 0.1, "min_validation_pass_rate": 0.97}
    gov.update(over.pop("governance", {}))
    s = {"workflow_id": WID, "tenant_id": "t1", "cadence": [2, 2], "governance": gov,
         "objective": {"primary": "engagement_rate", "guardrail": {"pickup_rate_max_drop": 0.02}},
         "options": {"welcome_message": ["W1", "W2"], "voice": ["V1", "V2"], "caller_id": ["D1", "D2", "D3"], "prompt_version": ["P1", "P2", "P3"]}}
    s.update(over)
    return s


def base_config():
    return {"cohorts": [], "allocations": {"default": {"welcome_message": {"W1": 1.0}, "voice": {"V1": 1.0}, "caller_id": {"D1": 0.5, "D2": 0.5}}},
            "prompt_version": "P1", "schedule": {"hour_weights": {}, "lead_preferred_hour": {}}}


class FakeSim:
    """The contract from docs/SIMULATOR.md, including its error codes."""

    def __init__(self):
        self.version = 1
        self.cfg = base_config()
        self.approvals_by_id = {}
        self.history = []
        self.applied = []
        self.approval_posts = 0
        self.validation = {}
        self.suggestions = []
        self.fail_next_apply_after_commit = False

    def config(self, wid):
        return {"version": self.version, "config": self.cfg, "actor": "business_default"}

    def config_history(self, wid):
        return self.history

    def approvals(self, wid):
        return list(self.approvals_by_id.values())

    def approval(self, aid):
        return self.approvals_by_id[aid]

    def request_approval(self, body):
        if any(a["proposal_id"] == body["proposal_id"] for a in self.approvals_by_id.values()):
            raise SimError(409, "duplicate_proposal_id", body["proposal_id"])
        if body["base_version"] != self.version:
            raise SimError(409, "stale_base_version", {"current_version": self.version})
        self.approval_posts += 1
        aid = f"apr_{len(self.approvals_by_id) + 1}"
        a = {"approval_id": aid, "proposal_id": body["proposal_id"], "status": "pending", "body": body, "reasons": []}
        self.approvals_by_id[aid] = a
        return a

    def decide(self, aid, status="approved", reasons=None):
        self.approvals_by_id[aid]["status"] = status
        self.approvals_by_id[aid]["reasons"] = reasons or []

    def apply(self, wid, aid):
        a = self.approvals_by_id[aid]
        if a["status"] != "approved":
            raise SimError(409, "not_approved", {"status": a["status"]})
        if a["body"]["base_version"] != self.version:
            raise SimError(409, "stale_base_version", {"current_version": self.version})
        self.version += 1
        self.cfg = a["body"]["proposed_config"]
        a["status"] = "applied"
        self.applied.append(a["proposal_id"])
        self.history.append({"version": self.version, "proposal_id": a["proposal_id"], "approval_id": aid})
        if self.fail_next_apply_after_commit:
            self.fail_next_apply_after_commit = False
            raise ConnectionError("killed after the apply landed")
        return {"version": self.version, "workflow_id": wid, "changed_dims": []}

    def auto_apply(self, wid, body):
        assert not any(k.startswith("_") for k in body), "internal fields must not reach the API"
        if any(h["proposal_id"] == body["proposal_id"] for h in self.history):
            raise SimError(409, "duplicate_proposal_id", body["proposal_id"])
        self.version += 1
        self.cfg = body["proposed_config"]
        self.applied.append(body["proposal_id"])
        self.history.append({"version": self.version, "proposal_id": body["proposal_id"], "approval_id": None})
        return {"version": self.version, "workflow_id": wid, "changed_dims": []}

    def supervisor_edit(self, new_cfg):
        self.version += 1
        self.cfg = new_cfg

    def validate(self, wid, prompt, n):
        return {"validation_run_id": f"val_{prompt}_{n}", "pass_rate": self.validation.get(prompt, 0.99), "n": n}

    def suggest_fixes(self, wid, problem):
        return {"suggestions": self.suggestions}


@pytest.fixture()
def world(tmp_path):
    store = Store(str(tmp_path / "c.db"))
    sim = FakeSim()
    specs = {WID: spec()}
    gov = Governance(store, sim, specs, {})
    yield store, sim, specs, gov
    store.close()


def _intent(gov, store, key="k1", kind="promote", priority=60, ops=None, now=TEN, **ev):
    ops = ops or [{"op": "set_alloc", "cohort": "default", "dim": "voice", "dist": {"V2": 1}}]
    with store.tx():
        return gov.enqueue(WID, kind, priority, ops, {"summary": f"change {key}", "rationale": "because", "dims": ["voice"], "value_per_day": 5, "confidence": 0.9, **ev}, now, key)


def _status(store):
    return store.one("SELECT status FROM proposals ORDER BY created_minute DESC, rowid DESC LIMIT 1")["status"]


# --- statistics added after the false-incident bug ----------------------------------------------
def test_exact_tail_matches_hand_calculation():
    # P(X >= 1) with n=10, p=0.1 is 1 - 0.9^10
    assert stats.binomial_tail(1, 10, 0.1) == pytest.approx(1 - 0.9 ** 10, rel=1e-9)
    assert stats.binomial_tail(0, 10, 0.1) == 1.0
    assert stats.binomial_tail(11, 10, 0.1) == 0.0


def test_exact_tail_shows_why_the_normal_approximation_was_wrong():
    # 7 flags in 100 calls at a 1.4% baseline. z is well above 4, yet the event is common enough
    # that hundreds of looks a week would produce it. This exact case opened a false incident.
    n, base, flags = 100, 0.014, 7
    z = stats.poisson_binomial_z(flags, n * base, n * base * (1 - base))
    assert z > 4
    assert stats.binomial_tail(flags, n, base) > 1e-4
    assert stats.binomial_tail(flags, n, base) > cfg.HALLUC_P


# --- config operations --------------------------------------------------------------------------
def test_ops_replay_on_a_new_base_keeps_supervisor_edit():
    ops = [{"op": "set_alloc", "cohort": "default", "dim": "voice", "dist": {"V1": 0.5, "V2": 0.5}}]
    edited = base_config()
    edited["prompt_version"] = "P2"
    out = co.apply_ops(edited, ops)
    assert out["prompt_version"] == "P2" and out["allocations"]["default"]["voice"] == {"V1": 0.5, "V2": 0.5}


def test_supervisor_cohorts_keep_precedence_over_ours():
    cfg_ = base_config()
    cfg_["cohorts"] = [{"id": "vip", "where": {"value_band": ["high"]}}]
    out = co.apply_ops(cfg_, [{"op": "add_cohort", "id": "c_lang_ta", "where": {"lang": ["ta"]}}])
    assert [c["id"] for c in out["cohorts"]] == ["vip", "c_lang_ta"]


def _server_normalise(dist):
    total = sum(dist.values())
    return {k: v / total for k, v in dist.items()}


@pytest.mark.parametrize("dist", [
    {"V1": 0.5, "V2": 1 / 6, "V3": 1 / 6, "V4": 1 / 6},
    {"V1": 1, "V2": 1, "V3": 1},
    {"D1": 0.475, "D2": 0.475, "D3": 0.05},
    {"W1": 0.85, "W2": 0.15},
    {"A": 0.1, "B": 0.2, "C": 0.3, "D": 0.4},
    {"A": 3, "B": 7, "C": 11, "D": 13, "E": 17, "F": 19, "G": 23},
])
def test_weights_do_not_change_on_the_servers_write_round_trip(dist):
    # Found in a real run: float drift made a caller-ID auto-apply report voice as changed too.
    out = co._normalise(dist)
    assert sum(out.values()) == 1.0
    assert _server_normalise(out) == out
    assert _server_normalise(dict(reversed(list(out.items())))) == dict(reversed(list(out.items())))


def test_normalised_weights_stay_close_to_what_was_asked():
    assert co._normalise({"V2": 0.85, "V1": 0.15})["V2"] == pytest.approx(0.85, abs=1e-4)


def test_drifting_weights_are_detected():
    drifting = base_config()
    drifting["allocations"]["default"]["voice"] = {"V1": 0.4999995000004999, "V2": 0.16666683333316665, "V3": 0.16666683333316665, "V4": 0.16666683333316665}
    assert not co.survives_normalisation(drifting)
    assert co.survives_normalisation(base_config())


def test_auto_apply_refuses_a_write_that_could_touch_a_customer_facing_dim(world):
    store, sim, _, gov = world
    sim.cfg["allocations"]["default"]["voice"] = {"V1": 0.4999995000004999, "V2": 0.16666683333316665, "V3": 0.16666683333316665, "V4": 0.16666683333316665}
    _intent(gov, store, kind="did_quarantine", priority=90, ops=[{"op": "quarantine_did", "did": "D1", "replacements": []}])
    gov.flush(WID, TEN)
    assert not sim.history, "must not auto-apply"
    assert sim.approval_posts == 1, "falls through to a human"


def test_max_shift_measures_total_variation():
    new = base_config()
    new["allocations"]["default"]["caller_id"] = {"D2": 1.0}
    assert co.max_shift(base_config(), new) == pytest.approx(0.5)


def test_capped_step_never_exceeds_the_policy_limit():
    target = base_config()
    target["allocations"]["default"]["caller_id"] = {"D2": 1.0}
    step = co.capped_step(base_config(), target, 0.2)
    assert co.max_shift(base_config(), step) == pytest.approx(0.2, abs=1e-5)


def test_quarantine_of_only_number_uses_replacements():
    c = base_config()
    c["allocations"]["default"]["caller_id"] = {"D1": 1.0}
    out = co.apply_ops(c, [{"op": "quarantine_did", "did": "D1", "replacements": ["D2", "D3"]}])
    assert out["allocations"]["default"]["caller_id"] == {"D2": 0.5, "D3": 0.5}


# --- governance ---------------------------------------------------------------------------------
def test_happy_path_applies_exact_approved_config(world):
    store, sim, _, gov = world
    _intent(gov, store)
    gov.flush(WID, TEN)
    assert _status(store) == "pending"
    sim.decide("apr_1")
    gov.poll(WID, TEN + 60)
    assert _status(store) == "applied" and sim.version == 2
    assert sim.cfg["allocations"]["default"]["voice"] == {"V2": 1.0}


def test_proposal_is_complete_for_the_approver(world):
    store, sim, _, gov = world
    _intent(gov, store)
    gov.flush(WID, TEN)
    body = sim.approvals_by_id["apr_1"]["body"]
    assert body["change_summary"] and body["diff"] and body["dry_run"] and body["rationale"]
    assert 0 <= body["impact_score"] <= 1 and body["affected_leads"] >= 0


def test_nothing_is_sent_outside_approver_hours(world):
    store, sim, _, gov = world
    _intent(gov, store)
    gov.flush(WID, 3 * 60)
    gov.flush(WID, 20 * 60)
    assert sim.approval_posts == 0


def test_routine_work_leaves_one_request_for_incidents(world):
    store, sim, specs, gov = world
    specs[WID]["governance"]["max_requests_per_24h"] = 1
    _intent(gov, store)
    gov.flush(WID, TEN)
    assert sim.approval_posts == 0
    _intent(gov, store, key="i1", kind="incident_fix", priority=100)
    gov.flush(WID, TEN)
    assert sim.approval_posts == 1


def test_kestrel_cancel_preferences_narrow_the_policy(tmp_path):
    store = Store(str(tmp_path / "c.db"))
    s = spec(workflow_id="ks_cancel", tenant_id="kestrel_finance", governance={"max_requests_per_24h": 4})
    gov = Governance(store, FakeSim(), {"ks_cancel": s}, {})
    assert gov.request_limit(s) == 2
    assert not gov.can_send(s, 10 * 60 + 30, urgent=False)
    assert gov.can_send(s, 11 * 60, urgent=False)
    assert gov.can_send(s, 10 * 60 + 30, urgent=True)
    store.close()


def test_other_kestrel_workflows_are_not_constrained_by_one_supervisor(tmp_path):
    store = Store(str(tmp_path / "c.db"))
    s = spec(workflow_id="kest_renewal_0", tenant_id="kestrel_finance")
    gov = Governance(store, FakeSim(), {"kest_renewal_0": s}, {})
    assert gov.request_limit(s) == 3 and gov.can_send(s, 10 * 60 + 30, urgent=False)
    store.close()


def test_stale_on_apply_reproposes_on_the_supervisors_base(world):
    store, sim, _, gov = world
    _intent(gov, store)
    gov.flush(WID, TEN)
    sim.decide("apr_1")
    edited = base_config()
    edited["prompt_version"] = "P2"
    sim.supervisor_edit(edited)
    gov.poll(WID, TEN + 60)
    assert _status(store) == "stale" and not sim.applied
    gov.flush(WID, TEN + 75)
    assert sim.approvals_by_id["apr_2"]["body"]["proposed_config"]["prompt_version"] == "P2"
    assert sim.approvals_by_id["apr_2"]["body"]["base_version"] == 2


@pytest.mark.parametrize("outcome", ["rejected", "expired"])
def test_rejected_and_expired_retry_tomorrow_with_a_new_id(world, outcome):
    store, sim, _, gov = world
    _intent(gov, store)
    gov.flush(WID, TEN)
    sim.decide("apr_1", outcome)
    gov.poll(WID, TEN + 60)
    gov.flush(WID, TEN + 90)
    assert sim.approval_posts == 1, "must wait for fresh data"
    gov.flush(WID, TEN + 60 + cfg.RETRY_BACKOFF_MINUTES)  # backoff runs from the decision, not the request
    assert sim.approval_posts == 2
    ids = {a["proposal_id"] for a in sim.approvals_by_id.values()}
    assert len(ids) == 2


def test_lapsed_approval_is_requeued(world):
    store, sim, _, gov = world
    _intent(gov, store)
    gov.flush(WID, TEN)
    sim.decide("apr_1", "lapsed")
    gov.poll(WID, TEN + 200)
    assert store.one("SELECT status FROM intents")["status"] == "queued"


def test_intent_is_dropped_after_max_attempts(world):
    store, sim, _, gov = world
    _intent(gov, store)
    for attempt in range(cfg.MAX_PROPOSAL_ATTEMPTS):
        now = TEN + attempt * (60 + cfg.RETRY_BACKOFF_MINUTES)
        gov.flush(WID, now)
        sim.decide(f"apr_{attempt + 1}", "rejected")
        gov.poll(WID, now + 60)
    assert store.one("SELECT status FROM intents")["status"] == "dropped"


def test_batches_many_changes_into_one_request(world):
    store, sim, _, gov = world
    for i in range(5):
        _intent(gov, store, key=f"k{i}", ops=[{"op": "set_alloc", "cohort": "default", "dim": "voice", "dist": {"V1": 1, "V2": i + 1}}])
    gov.flush(WID, TEN)
    assert sim.approval_posts == 1


def test_no_second_routine_request_while_one_is_open(world):
    store, sim, _, gov = world
    _intent(gov, store, key="k1")
    gov.flush(WID, TEN)
    _intent(gov, store, key="k2", now=TEN + 15)
    gov.flush(WID, TEN + 15)
    assert sim.approval_posts == 1


def test_incident_fix_jumps_ahead_of_an_open_routine_request(world):
    store, sim, _, gov = world
    _intent(gov, store, key="k1")
    gov.flush(WID, TEN)
    sim.decide("apr_1")
    _intent(gov, store, key="i1", kind="incident_fix", priority=100, ops=[{"op": "set_prompt", "prompt": "P3"}], validation_run_id="val_1")
    gov.flush(WID, TEN + 15)
    gov.poll(WID, TEN + 30)
    assert sim.version == 1, "routine apply must wait for the incident fix"
    sim.decide("apr_2")
    gov.poll(WID, TEN + 45)
    assert sim.cfg["prompt_version"] == "P3"


def test_auto_apply_is_only_used_for_caller_id(world):
    store, sim, _, gov = world
    _intent(gov, store, kind="did_quarantine", priority=90, ops=[{"op": "quarantine_did", "did": "D1", "replacements": []}])
    gov.flush(WID, 3 * 60)  # middle of the night: operational changes do not need an approver
    assert sim.version == 2 and sim.approval_posts == 0
    assert gov.auto_allowed(spec(), "voice") is False


def test_customer_facing_never_auto_applies_even_if_policy_would_allow_it(world):
    _, _, _, gov = world
    permissive = spec(governance={"auto_apply": {"enabled": True, "allowed_dims": ["voice", "welcome_message"], "max_shift": 0.2}})
    assert not gov.auto_allowed(permissive, "voice")
    assert not gov.auto_allowed(permissive, "welcome_message")


def test_large_did_move_takes_one_capped_step_then_asks_a_human(world):
    store, sim, specs, gov = world
    specs[WID]["governance"]["auto_apply"]["max_shift"] = 0.2
    _intent(gov, store, kind="did_quarantine", priority=90, ops=[{"op": "quarantine_did", "did": "D1", "replacements": []}])
    gov.flush(WID, TEN)
    assert co.max_shift(base_config(), sim.cfg) <= 0.2 + 1e-6
    assert sim.version == 2, "exactly one auto-apply: chaining steps would evade max_shift"
    gov.flush(WID, TEN + 15)
    assert sim.version == 2 and sim.approval_posts == 1


# --- crash recovery -----------------------------------------------------------------------------
def test_crash_after_draft_before_post_sends_once(world):
    store, sim, _, gov = world
    _intent(gov, store)
    real = sim.request_approval
    sim.request_approval = lambda body: (_ for _ in ()).throw(ConnectionError("killed before POST"))
    with pytest.raises(ConnectionError):
        gov.flush(WID, TEN)
    sim.request_approval = real
    assert _status(store) == "drafted"
    Governance(store, sim, {WID: spec()}, {}).poll(WID, TEN + 15)
    assert _status(store) == "pending" and sim.approval_posts == 1


def test_crash_after_post_recovers_the_existing_approval(world):
    store, sim, _, gov = world
    _intent(gov, store)
    real = sim.request_approval

    def post_then_die(body):
        real(body)
        raise ConnectionError("killed after POST landed")

    sim.request_approval = post_then_die
    with pytest.raises(ConnectionError):
        gov.flush(WID, TEN)
    sim.request_approval = real
    Governance(store, sim, {WID: spec()}, {}).poll(WID, TEN + 15)
    assert _status(store) == "pending" and sim.approval_posts == 1
    assert store.one("SELECT approval_id FROM proposals")["approval_id"] == "apr_1"


def test_crash_after_apply_does_not_apply_twice(world):
    store, sim, _, gov = world
    _intent(gov, store)
    gov.flush(WID, TEN)
    sim.decide("apr_1")
    sim.fail_next_apply_after_commit = True
    with pytest.raises(ConnectionError):
        gov.poll(WID, TEN + 60)
    assert sim.version == 2
    Governance(store, sim, {WID: spec()}, {}).poll(WID, TEN + 75)
    assert _status(store) == "applied" and sim.version == 2 and len(sim.applied) == 1
    assert store.one("SELECT applied_version FROM proposals")["applied_version"] == 2


def test_crash_during_auto_apply_does_not_apply_twice(world):
    store, sim, _, gov = world
    _intent(gov, store, kind="did_quarantine", priority=90, ops=[{"op": "quarantine_did", "did": "D1", "replacements": []}])
    real = sim.auto_apply

    def apply_then_die(wid, body):
        real(wid, body)
        raise ConnectionError("killed after PUT landed")

    sim.auto_apply = apply_then_die
    with pytest.raises(ConnectionError):
        gov.flush(WID, TEN)
    sim.auto_apply = real
    Governance(store, sim, {WID: spec()}, {}).poll(WID, TEN + 15)
    assert len(sim.applied) == 1 and _status(store) == "applied"


# --- experiments --------------------------------------------------------------------------------
def _fact(store, day, version, voice, connected, engaged, cohort="default", seg=0, did="D1", prompt="P1"):
    store.x("INSERT INTO fact_arm VALUES(?,?,?,?,?,?,?,?,?,?,?,?,0)", WID, day, version, cohort, seg, "W1", voice, did, prompt, connected * 3, connected, engaged)


def _running(store, end=8 * 1440, control="V1", arms=("V2",), start_minute=720):
    store.x("INSERT INTO experiments(exp_id,workflow_id,cohort_id,dim,status,control,arms,kpi,start_version,start_minute,state) VALUES('e1',?,'default','voice','running',?,?,'engagement_rate',2,?,?)",
            WID, json.dumps([control]), json.dumps(list(arms)), start_minute, json.dumps({"alpha_spent": 0.0, "stopped": [], "looks": 0}))


def _exp(world, end=8 * 1440):
    store, _, specs, gov = world
    return Experiments(store, gov, specs, {0: {"lang": "hi", "city_tier": "1", "age_band": "18-30", "value_band": "low"}}, end)


def _intents(store, kind=None):
    rows = store.q("SELECT * FROM intents")
    return [r for r in rows if kind is None or r["kind"] == kind]


def test_early_look_does_not_declare_a_winner_on_a_modest_lift(world):
    store = world[0]
    exp = _exp(world)
    _running(store)
    _fact(store, 0, 2, "V1", 300, 90)
    _fact(store, 0, 2, "V2", 300, 115)  # would pass an uncorrected p<0.05 test
    assert stats.compare_stratified([(115, 300, 90, 300)]).p_two_sided < 0.05
    exp.daily(WID, base_config(), 1440 + 660)
    assert not _intents(store, "promote")


def test_strong_winner_is_promoted_with_a_holdout(world):
    store = world[0]
    exp = _exp(world)
    _running(store, start_minute=0)
    for day in (0, 1, 2, 3):
        _fact(store, day, 2, "V1", 800, 240)
        _fact(store, day, 2, "V2", 800, 400)
    exp.daily(WID, base_config(), 3 * 1440 + 660)
    ops = json.loads(_intents(store, "promote")[0]["ops"])
    assert ops[0]["dist"] == pytest.approx({"V2": 1 - cfg.HOLDOUT_SHARE, "V1": cfg.HOLDOUT_SHARE})


def test_no_winner_at_the_end_returns_traffic_to_control(world):
    store = world[0]
    exp = _exp(world)
    _running(store, start_minute=0)
    for day in range(5):
        _fact(store, day, 2, "V1", 300, 90)
        _fact(store, day, 2, "V2", 300, 91)
    exp.daily(WID, base_config(), 5 * 1440 + 660)
    ops = json.loads(_intents(store, "promote")[0]["ops"])
    assert ops[0]["dist"] == {"V1": 1.0}


def test_winner_whose_lift_collapsed_inside_the_test_is_not_promoted(world):
    store = world[0]
    exp = _exp(world)
    _running(store, start_minute=0)
    for day in (0, 1, 2):
        _fact(store, day, 2, "V1", 800, 240)
        _fact(store, day, 2, "V2", 800, 480)
    for day in (3, 4):
        _fact(store, day, 2, "V1", 800, 240)
        _fact(store, day, 2, "V2", 800, 235)
    exp.daily(WID, base_config(), 5 * 1440 + 660)
    ops = json.loads(_intents(store, "promote")[0]["ops"])
    assert ops[0]["dist"] == {"V1": 1.0}
    assert store.q("SELECT 1 FROM decisions WHERE kind='winner_unstable'")


def test_clearly_worse_arm_is_stopped_early(world):
    store = world[0]
    exp = _exp(world)
    _running(store, arms=("V2", "V3"))
    _fact(store, 0, 2, "V1", 800, 400)
    _fact(store, 0, 2, "V2", 800, 410)
    _fact(store, 0, 2, "V3", 800, 200)
    exp.daily(WID, base_config(), 1440 + 660)
    assert json.loads(_intents(store, "stop_arm")[0]["ops"])[0]["arm"] == "V3"


def test_guardrail_blocks_a_winner_that_hurts_pickup(world):
    store = world[0]
    exp = _exp(world)
    _running(store, start_minute=0)
    for day in range(4):
        store.x("INSERT INTO fact_arm VALUES(?,?,2,'default',0,'W1','V1','D1','P1',4000,1600,480,0)", WID, day)
        store.x("INSERT INTO fact_arm VALUES(?,?,2,'default',0,'W1','V2','D1','P1',4000,1200,600,0)", WID, day)
    exp.daily(WID, base_config(), 4 * 1440 + 660)
    assert store.q("SELECT 1 FROM decisions WHERE kind='guardrail_block'")
    assert json.loads(_intents(store, "promote")[0]["ops"])[0]["dist"] == {"V1": 1.0}


def test_days_with_only_one_arm_are_not_evidence(world):
    store = world[0]
    exp = _exp(world)
    _running(store, start_minute=0)
    _fact(store, 0, 2, "V2", 5000, 2500)  # V2 ran alone: no contrast exists for this day
    assert exp._compare(exp._rows(WID, "default", 2), "voice", "V2", ["V1"], "engagement_rate") is None


def test_supervisor_edit_on_the_tested_dimension_ends_the_test(world):
    store = world[0]
    exp = _exp(world)
    _running(store)
    exp.on_supervisor_edit(WID, 3, ["voice"], TEN)
    assert store.one("SELECT status FROM experiments")["status"] == "invalidated"


def test_supervisor_prompt_edit_leaves_a_voice_test_running(world):
    store = world[0]
    exp = _exp(world)
    _running(store)
    exp.on_supervisor_edit(WID, 3, ["prompt_version"], TEN)
    assert store.one("SELECT status FROM experiments")["status"] == "running"


def test_arm_never_approved_records_no_learning(world):
    store, sim, _, gov = world
    exp = _exp(world)
    exp.plan(WID, base_config(), TEN)
    planned = store.q("SELECT COUNT(*) n FROM experiments")[0]["n"]
    assert planned >= 1
    for attempt in range(cfg.MAX_PROPOSAL_ATTEMPTS):
        now = TEN + attempt * (60 + cfg.RETRY_BACKOFF_MINUTES)
        gov.flush(WID, now)
        for a in sim.approvals_by_id.values():
            if a["status"] == "pending":
                sim.decide(a["approval_id"], "rejected")
        gov.poll(WID, now + 60)
    assert {r["status"] for r in store.q("SELECT status FROM experiments WHERE dim='voice'")} == {"never_ran"}


def _promo(store, version=3, lift=0.08, cohort="default"):
    store.x("INSERT INTO promotions(promo_id,workflow_id,cohort_id,dim,winner,holdout,kpi,lift_at_promotion,version,status,applied_minute) VALUES('p1',?,?,'voice','V2','V1','engagement_rate',?,?,'active',0)",
            WID, cohort, lift, version)


def test_decay_is_caught_using_pooled_control(world):
    store = world[0]
    exp = _exp(world)
    _promo(store, version=3, lift=0.10)
    for day in range(-14, 3):  # long, stable control history at 30%
        _fact(store, day, 1, "V1", 500, 150)
    for day in (3, 4, 5):
        _fact(store, day, 3, "V1", 60, 18)    # a small holdout, also at 30%
        _fact(store, day, 3, "V2", 340, 102)  # winner has fallen to control's level
    exp.daily(WID, base_config(), 6 * 1440 + 660)
    assert _intents(store, "rollback")
    assert store.one("SELECT status FROM promotions")["status"] == "rollback_requested"


def test_a_winner_that_is_holding_is_left_alone(world):
    store = world[0]
    exp = _exp(world)
    _promo(store, version=3, lift=0.10)
    for day in range(-14, 3):
        _fact(store, day, 1, "V1", 500, 150)
    for day in (3, 4, 5):
        _fact(store, day, 3, "V1", 60, 18)
        _fact(store, day, 3, "V2", 340, 136)
    exp.daily(WID, base_config(), 6 * 1440 + 660)
    assert not _intents(store, "rollback")


def test_holdout_disagreeing_with_history_falls_back_to_concurrent_only(world):
    store = world[0]
    exp = _exp(world)
    _promo(store, version=3, lift=0.10)
    for day in range(-14, 3):
        _fact(store, day, 1, "V1", 500, 150)  # history at 30%
    for day in (3, 4, 5):
        _fact(store, day, 3, "V1", 60, 36)    # the world changed: control is at 60% now
        _fact(store, day, 3, "V2", 340, 238)
    exp.daily(WID, base_config(), 6 * 1440 + 660)
    detail = json.loads(store.one("SELECT detail FROM decisions WHERE kind='decay_check'")["detail"])
    assert "disagreed" in detail["control_source"]


# --- incidents ----------------------------------------------------------------------------------
def _hour(store, prompt, hour, qa, halluc, did="D1", dials=None, connected=None, engaged=None):
    connected = qa if connected is None else connected
    store.x("INSERT INTO fact_hour VALUES(?,?,?,?,?,?,?,?,?)", WID, hour, prompt, did, dials if dials is not None else connected * 3, connected,
            engaged if engaged is not None else connected // 2, qa, halluc)


@pytest.fixture()
def inc(world):
    store, sim, specs, gov = world
    i = Incidents(store, sim, gov, specs)
    for h in range(-200, 0):
        _hour(store, "P1", h, 100, 1)
    i.compute_baselines()
    return i


def _open(store):
    return store.q("SELECT * FROM incidents WHERE status='open'")


def test_handful_of_flags_is_not_an_incident(world, inc):
    store = world[0]
    # Same shape as the false alarm: well above baseline on a normal-approx z, exact tail says noise.
    _hour(store, "P1", 10, 100, 6)
    inc.step(WID, base_config(), 11 * 60)
    assert not _open(store)


def test_real_spike_opens_one_incident_and_prefers_the_free_fix(world, inc):
    store, sim, _, _ = world
    cfg_ = base_config()
    cfg_["prompt_version"] = "P2"
    _hour(store, "P2", 10, 300, 40)
    inc.step(WID, cfg_, 11 * 60)
    inc.step(WID, cfg_, 11 * 60 + 15)
    assert len(_open(store)) == 1
    assert json.loads(_intents(store, "incident_fix")[0]["ops"])[0] == {"op": "set_prompt", "prompt": "P1"}
    assert not store.q("SELECT 1 FROM credit_ledger WHERE purpose='llm_suggest'")


def test_fix_validates_only_when_an_approver_can_read_it(world, inc):
    store = world[0]
    cfg_ = base_config()
    cfg_["prompt_version"] = "P2"
    _hour(store, "P2", 2, 300, 40)
    inc.step(WID, cfg_, 3 * 60)
    assert len(_open(store)) == 1 and not store.q("SELECT 1 FROM credit_ledger")


def test_failed_validation_asks_llm_and_picks_by_measured_safety(world, inc):
    store, sim, _, _ = world
    cfg_ = base_config()
    cfg_["prompt_version"] = "P2"
    sim.validation = {"P1": 0.90, "P3": 0.985, "P5": 0.975}
    sim.suggestions = [{"prompt_version": "P5", "summary": "s"}, {"prompt_version": "P3", "summary": "s"}]
    _hour(store, "P2", 10, 300, 40)
    inc.step(WID, cfg_, 11 * 60)
    assert json.loads(_intents(store, "incident_fix")[0]["ops"])[0]["prompt"] == "P3"


def test_incident_spend_is_capped(world, inc):
    store, sim, _, _ = world
    cfg_ = base_config()
    cfg_["prompt_version"] = "P2"
    sim.validation = {"P1": 0.5, "P3": 0.5}
    sim.suggestions = [{"prompt_version": "P3", "summary": "s"}]
    _hour(store, "P2", 10, 300, 40)
    inc.step(WID, cfg_, 11 * 60)
    spent = store.one("SELECT SUM(cost) c FROM credit_ledger")["c"]
    assert spent <= cfg.MAX_CREDITS_PER_INCIDENT
    assert json.loads(_open(store)[0]["detail"])["phase"] == "stuck"


def test_fix_that_kills_engagement_fails_verification(world, inc):
    store = world[0]
    cfg_ = base_config()
    cfg_["prompt_version"] = "P2"
    _hour(store, "P2", 10, 300, 40)
    inc.step(WID, cfg_, 11 * 60)
    row = _open(store)[0]
    detail = json.loads(row["detail"])
    detail.update({"phase": "verifying", "candidate": "P5", "fix_hour": 12, "pre_engagement": 0.5})
    store.x("UPDATE incidents SET detail=? WHERE incident_id=?", json.dumps(detail), row["incident_id"])
    _hour(store, "P5", 13, 300, 1, connected=300, engaged=30)  # nobody hallucinated, and nobody stayed
    cfg_["prompt_version"] = "P5"
    inc.step(WID, cfg_, 14 * 60)
    after = json.loads(_open(store)[0]["detail"])
    assert "P5" in after["failed"] and after["phase"] != "verifying"
    assert after["verification"]["kept_engagement"] is False


def test_supervisor_fixing_it_first_closes_the_incident(world, inc):
    store = world[0]
    cfg_ = base_config()
    cfg_["prompt_version"] = "P2"
    _hour(store, "P2", 2, 300, 40)
    inc.step(WID, cfg_, 3 * 60)
    inc.step(WID, base_config(), 3 * 60 + 15)  # supervisor put P1 back before approvers woke up
    assert not _open(store)
    assert store.one("SELECT status FROM incidents")["status"] == "superseded"


def test_degraded_caller_id_is_caught_against_peers(world, inc):
    store = world[0]
    _hour(store, "P1", 10, 90, 0, did="D1", dials=600, connected=90)
    _hour(store, "P1", 10, 200, 0, did="D2", dials=600, connected=200)
    inc.step(WID, base_config(), 11 * 60)
    assert store.one("SELECT did FROM did_status")["did"] == "D1"
    assert json.loads(_intents(store, "did_quarantine")[0]["ops"])[0]["did"] == "D1"


def test_ordinary_noise_between_caller_ids_is_ignored(world, inc):
    store = world[0]
    _hour(store, "P1", 10, 180, 0, did="D1", dials=600, connected=180)
    _hour(store, "P1", 10, 200, 0, did="D2", dials=600, connected=200)
    inc.step(WID, base_config(), 11 * 60)
    assert not store.q("SELECT 1 FROM did_status")


def test_too_few_dials_never_flags_a_number(world, inc):
    store = world[0]
    _hour(store, "P1", 10, 2, 0, did="D1", dials=40, connected=2)
    _hour(store, "P1", 10, 300, 0, did="D2", dials=1000, connected=300)
    inc.step(WID, base_config(), 11 * 60)
    assert not store.q("SELECT 1 FROM did_status")


# --- audit --------------------------------------------------------------------------------------
def test_every_lifecycle_step_is_in_the_audit_trail(world):
    store, sim, _, gov = world
    _intent(gov, store)
    gov.flush(WID, TEN)
    sim.decide("apr_1")
    gov.poll(WID, TEN + 60)
    kinds = [r["kind"] for r in store.q("SELECT kind FROM decisions ORDER BY id")]
    assert kinds == ["proposal_drafted", "proposal_sent", "proposal_approved", "proposal_applied"]


def test_audit_table_is_append_only_in_the_source():
    import pathlib
    src = "".join(p.read_text(encoding="utf-8") for p in pathlib.Path("controller").glob("*.py"))
    assert "UPDATE decisions" not in src and "DELETE FROM decisions" not in src
