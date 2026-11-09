"""Regression tests for code-review findings: each pins a failure mode that once existed."""
import json

from controller import configs, stats, store
from controller.clock import Clock, parse
from controller.experiments import Experiments
from controller.incidents import Incidents
from controller.ingest import Ingestor
from controller.main import Controller
from controller.sim_client import SimError
from tests.fakes import FakeSim, call_line, campaign_line, lead_line

CLOCK = "2027-01-04T00:00:00+05:30"


def test_interrupted_chunk_is_reread_from_scratch_not_double_counted():
    """Review #1: a stream that dies mid-chunk must not hand already-consumed lines over twice."""
    lines = [campaign_line(), lead_line("wf:l1"), call_line(lead="wf:l1"), call_line(lead="wf:l1", minute=700)]

    class Flaky(FakeSim):
        attempts = 0

        def chunk(self, n):
            self.attempts += 1
            if self.attempts == 1:
                yield from lines[:3]
                raise SimError("connection dropped mid-chunk")
            yield from lines

    sim = Flaky()
    sim.chunk_lines = {0: lines}
    conn = store.connect(":memory:")
    Ingestor(conn, sim, Clock(CLOCK)).catch_up()
    assert sim.attempts == 2
    assert conn.execute("SELECT SUM(dials) FROM agg").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0] == 1


def test_unknown_lead_is_skipped_and_paged_not_a_crash_loop():
    sim = FakeSim()
    sim.chunk_lines = {0: [campaign_line(leads=1), lead_line(), call_line(lead="wf:l_missing"), call_line()]}
    conn = store.connect(":memory:")
    Ingestor(conn, sim, Clock(CLOCK)).catch_up()
    assert conn.execute("SELECT SUM(dials) FROM agg").fetchone()[0] == 1
    assert store.get_meta(conn, "last_chunk") == 0
    assert conn.execute("SELECT COUNT(*) FROM alerts WHERE message LIKE '%never saw%'").fetchone()[0] == 1


def test_business_outcome_counts_leads_not_calls():
    sim = FakeSim()
    sim.chunk_lines = {0: [campaign_line(leads=1), lead_line(), call_line(), call_line(minute=700)]}
    conn = store.connect(":memory:")
    Ingestor(conn, sim, Clock(CLOCK)).catch_up()
    assert tuple(conn.execute("SELECT uploaded, concluded FROM campaign_kpi").fetchone()) == (1, 1)


def _experiments_env():
    sim, conn = FakeSim(), store.connect(":memory:")
    configs.sync(conn, sim, Clock(CLOCK), "wf")
    spec = {"workflow_id": "wf", "objective": {"primary": "engagement_rate"}, "options": {"voice": ["V1", "V2"]}}
    return conn, Experiments(conn, {"wf": spec})


def test_invalidated_experiment_never_lets_its_request_go_out():
    """Review #2: after invalidation, a rebased request for that experiment must be dropped, not resubmitted."""
    conn, exps = _experiments_env()
    eid = conn.execute("INSERT INTO experiments(wf, dim, kpi, stage, state, control, arms_json, screened_json,"
                       " result_json) VALUES('wf','voice','engagement_rate',2,'PROMOTING','V1','[\"V2\"]','[]',?)",
                       (json.dumps({"pending": {"proposal_id": "wf:1:1", "prev_state": "STAGE2"}}),)).lastrowid
    conn.execute("INSERT INTO proposals(proposal_id, wf, kind, state, refs_json, parent_proposal_id) VALUES"
                 " ('wf:1:2','wf','promote','DRAFT',?, 'wf:1:1')",
                 (json.dumps({"owner": "experiments", "experiments": {str(eid): "PROMOTED"}}),))
    exps.invalidate("wf", "voice", parse("D2 12:00"), "caller-ID rotation")
    p = conn.execute("SELECT * FROM proposals WHERE proposal_id='wf:1:2'").fetchone()
    ok, why = exps.revalidate(conn, p, parse("D2 13:00"))
    assert not ok and "ended" in why
    assert "pending" not in json.loads(conn.execute("SELECT result_json FROM experiments").fetchone()[0])


def test_supervisor_edit_stored_by_a_restart_sync_is_still_observed():
    """Review #3: 'stored' is not 'observed'. A version the startup sync stored must still trigger reactions."""
    sim, conn = FakeSim(), store.connect(":memory:")
    clock = Clock(CLOCK)
    configs.sync(conn, sim, clock, "wf")
    calls = []

    class Spy:
        def __getattr__(self, name):
            return lambda *a, **k: calls.append(name)

    ctl = Controller.__new__(Controller)
    ctl.conn, ctl.client, ctl.clock, ctl.specs = conn, sim, clock, {"wf": {}}
    ctl.experiments = ctl.incidents = ctl.detectors = Spy()
    ctl._observe_config_changes(parse("D1 09:00"))           # observes v1 (business default): no reactions
    assert calls == []
    sim.supervisor_edit(voice={"V2": 1.0})
    configs.sync(conn, sim, clock, "wf")                       # the restart's sync stores v2 silently
    ctl._observe_config_changes(parse("D1 10:00"))
    assert calls == ["on_supervisor_edit"]
    assert conn.execute("SELECT COUNT(*) FROM decisions WHERE kind='supervisor_edit'").fetchone()[0] == 1
    ctl._observe_config_changes(parse("D1 11:00"))             # observed once, never twice
    assert calls == ["on_supervisor_edit"]


def _incident_env(current_prompt: str):
    sim, conn = FakeSim(), store.connect(":memory:")
    sim.versions[-1]["config"]["prompt_version"] = current_prompt
    configs.sync(conn, sim, Clock(CLOCK), "wf")
    spec = {"workflow_id": "wf", "prompt_catalog": {}, "governance": {"min_validation_pass_rate": 0.97}}
    inc = Incidents(conn, sim, {"wf": spec})
    ctx = {"bad_prompt": "P2", "candidate": "P1", "queue": [], "tried": [], "suggested": True, "asks": {"P1": 1},
           "validation": {"validation_run_id": "val_1", "pass_rate": 0.986, "n": 500},
           "detector": {"rate": 0.09, "baseline": 0.0137, "p": 1e-9, "connected": 238}}
    iid = conn.execute("INSERT INTO incidents(wf, kind, opened_minute, state, context_json, timeline_json)"
                       " VALUES('wf','hallucination',0,'PROPOSED',?, '[]')", (json.dumps(ctx),)).lastrowid
    conn.execute("INSERT INTO proposals(proposal_id, wf, kind, state, refs_json, payload_json) VALUES"
                 " ('wf:9:1','wf','incident_fix','DROPPED',?, '{}')", (json.dumps({"owner": "incidents",
                                                                                    "incident": iid}),))
    p = conn.execute("SELECT * FROM proposals").fetchone()
    return conn, inc, iid, p


def _state(conn, iid):
    return conn.execute("SELECT state FROM incidents WHERE id=?", (iid,)).fetchone()[0]


def test_incident_reproposal_is_bounded():
    """Review #4: a deterministic drop or used-up asks must never re-propose on every tick."""
    conn, inc, iid, p = _incident_env("P2")
    inc.on_terminal(conn, p, "DROPPED", 600)
    assert _state(conn, iid) == "OPEN"                                           # next candidate, no re-draft
    assert conn.execute("SELECT COUNT(*) FROM proposals").fetchone()[0] == 1

    conn, inc, iid, p = _incident_env("P2")
    inc.on_terminal(conn, p, "EXPIRED", 600)                                     # 1 ask used of 2: ask again
    assert _state(conn, iid) == "PROPOSED"
    conn.execute("UPDATE proposals SET state='EXPIRED' WHERE proposal_id != 'wf:9:1'")
    inc.on_terminal(conn, conn.execute("SELECT * FROM proposals ORDER BY rowid DESC").fetchone(), "EXPIRED", 700)
    assert _state(conn, iid) == "OPEN"                                           # cap reached

    conn, inc, iid, p = _incident_env("P1")                                      # the fix went live anyway
    inc.on_terminal(conn, p, "DROPPED", 600)
    assert _state(conn, iid) == "VERIFYING"

    conn, inc, iid, p = _incident_env("P3")                                      # someone else replaced P2
    inc.on_terminal(conn, p, "DROPPED", 600)
    assert _state(conn, iid) == "SUPERSEDED"


def test_poisson_tiny_tails_keep_their_precision():
    p = stats.poisson_upper_p(40, 3.0)
    assert 0 < p < 1e-25
    assert stats.poisson_upper_p(5000, 3.0) == 0.0                    # underflow terminates, no infinite loop


def test_inconclusive_changes_config_only_on_evidence_of_harm():
    """Pre-registered rule at an inconclusive final look: significantly worse -> back to control; ahead or tied ->
    keep the split, monitored; behind but not significantly -> step down to the screening share (no coin-flip full
    revert, and no 50% exposure on a challenger that is probably a little worse)."""
    from controller.metrics import Counts
    spec = {"workflow_id": "wf", "objective": {"primary": "engagement_rate",
                                                "guardrail": {"pickup_rate_max_drop": 0.02}}}
    for ch_rate, expect in ((0.524, "keep"), (0.500, "keep"), (0.493, "stepdown"), (0.440, "revert")):
        conn, exps = _experiments_env()
        store.set_meta(conn, "end_minute", parse("D10 00:00"))
        sim_cfg = configs.current(conn, "wf")[1]
        sim_cfg["allocations"]["default"]["voice"] = {"V1": 0.5, "V3": 0.5}
        conn.execute("UPDATE config_versions SET config_json=?", (json.dumps(sim_cfg),))
        eid = conn.execute("INSERT INTO experiments(wf, dim, kpi, stage, state, control, arms_json, screened_json,"
                           " result_json) VALUES('wf','voice','engagement_rate',2,'STAGE2','V1','[\"V3\"]','[]','{}')"
                           ).lastrowid
        exp = conn.execute("SELECT * FROM experiments WHERE id=?", (eid,)).fetchone()
        data = {"V3": Counts(dials=6000, connected=1500, concluded=round(1500 * ch_rate)),
                "V1": Counts(dials=6000, connected=1500, concluded=750)}
        verdict = exps.test_promotion(exp, spec, data)
        action = exps._end_inconclusive(exp, spec, data, verdict, {}, parse("D6 12:00"))
        state = conn.execute("SELECT state FROM experiments WHERE id=?", (eid,)).fetchone()[0]
        if expect == "keep":
            assert action is None and state == "MONITORING_SPLIT"   # kept, monitored, never shown as a promotion
        elif expect == "stepdown":
            assert action.kind == "stepdown" and action.next_state == "MONITORING_SPLIT"
            assert action.patch["allocations"]["default"]["voice"] == {"V1": 0.9, "V3": 0.1}
        else:
            assert action.kind == "conclude" and action.patch["allocations"]["default"]["voice"] == {"V1": 1.0}


def test_promotion_needs_the_latest_window_not_to_show_the_challenger_behind():
    """Linux trace (nw_renewal W3, public_01): pooled stage-2 p=0.007 carried by early days (+9pp, +5pp) while the
    last two days had W3 3pp behind; promoting it was graded harmful. The recency check blocks that promotion."""
    from controller.metrics import Counts
    spec = {"workflow_id": "wf", "objective": {"primary": "engagement_rate",
                                                "guardrail": {"pickup_rate_max_drop": 0.02}}}
    conn, exps = _experiments_env()
    eid = conn.execute("INSERT INTO experiments(wf, dim, kpi, stage, state, control, arms_json, screened_json,"
                       " result_json) VALUES('wf','welcome_message','engagement_rate',2,'STAGE2','W1','[\"W3\"]',"
                       "'[]','{}')").lastrowid
    exp = conn.execute("SELECT * FROM experiments WHERE id=?", (eid,)).fetchone()
    pooled = {"W3": Counts(dials=6000, connected=1590, concluded=919), "W1": Counts(dials=6000, connected=1593,
                                                                                   concluded=852)}
    fading = {"W3": Counts(dials=1800, connected=480, concluded=255), "W1": Counts(dials=1800, connected=471,
                                                                                  concluded=266)}
    holding = {"W3": Counts(dials=1800, connected=480, concluded=280), "W1": Counts(dials=1800, connected=471,
                                                                                   concluded=255)}
    assert exps.test_promotion(exp, spec, pooled)["primary_pass"]
    assert not exps.test_promotion(exp, spec, pooled, fading)["promote"]
    assert exps.test_promotion(exp, spec, pooled, holding)["promote"]


def _decay_env(alloc: dict, dim: str):
    """A promoted experiment on a Kestrel-like policy (welcome/voice auto-apply, max_shift 0.2), 4 days left."""
    conn, _ = _experiments_env()
    store.set_meta(conn, "end_minute", parse("D12 00:00"))
    cfg = configs.current(conn, "wf")[1]
    cfg["allocations"]["default"][dim] = alloc
    conn.execute("UPDATE config_versions SET config_json=?", (json.dumps(cfg),))
    spec = {"workflow_id": "wf", "tenant_id": "t",
            "objective": {"primary": "engagement_rate", "guardrail": {"pickup_rate_max_drop": 0.02}},
            "governance": {"auto_apply": {"enabled": True, "allowed_dims": ["welcome_message", "voice"],
                                          "max_shift": 0.2}}}
    exps = Experiments(conn, {"wf": spec})
    control = max(alloc, key=lambda o: -alloc[o])
    winner = max(alloc, key=alloc.get)
    eid = conn.execute("INSERT INTO experiments(wf, dim, kpi, stage, state, control, arms_json, screened_json,"
                       " result_json, start_version, start_minute) VALUES('wf',?, 'engagement_rate', 3, 'PROMOTED',"
                       " ?, ?, '[]', ?, 1, ?)", (dim, control, json.dumps([winner]), json.dumps({"d_max": 4}),
                                                 parse("D7 13:00"))).lastrowid
    return conn, exps, spec, eid


def _day(conn, dim, day, winner, w, control, c):
    """One day of calls: (dials, connected, concluded) per arm, inside the window ending at D<day> 13:00."""
    col = {"voice": "voice", "welcome_message": "wm"}[dim]
    for opt, (d, n, x) in ((winner, w), (control, c)):
        vals = {"wm": "W1", "voice": "V1", col: opt}
        conn.execute("INSERT INTO agg VALUES('wf', ?, 'hi|1|31-45|mid', 1, 'default', ?, ?, 'D1', 'P1', ?, ?, ?, 0,"
                     " 0, 0)", (parse(f"D{day} 13:00") // 60 - 5, vals["wm"], vals["voice"], d, n, x))


def _decay(conn, exps, spec, eid, day):
    exp = conn.execute("SELECT * FROM experiments WHERE id=?", (eid,)).fetchone()
    return exps._eval_decay(exp, spec, parse(f"D{day} 13:00"))


def test_decay_case_b_one_small_holdback_window_no_longer_reverts():
    """Traced case v13 (V3 -> V1, D9): engagement p=0.0073 on a holdback of 110 connected calls. Under the old
    alpha 0.05/D_max = 0.0125 it fired a full revert of a variant that was in fact better. With the alpha split
    across the two metrics (0.05 / (4 * 2) = 0.00625) the same window does not fire."""
    conn, exps, spec, eid = _decay_env({"V3": 0.9, "V1": 0.1}, "voice")
    _day(conn, "voice", 8, "V3", (3600, 990, 490), "V1", (400, 110, 68))
    assert _decay(conn, exps, spec, eid, 8) is None
    last = conn.execute("SELECT rule, inputs_json FROM decisions ORDER BY id DESC LIMIT 1").fetchone()
    assert last["rule"] == "decay check: no decay" and json.loads(last["inputs_json"])["alpha_decay"] == 0.00625


def test_decay_case_a_first_signal_only_derisks_and_needs_a_second_window():
    """Traced case v11 (W2 -> W1, D8): pickup guardrail p=0.0036, which still clears the split alpha. A single
    window now only cuts exposure by one in-policy step; the full revert needs the next fresh window too."""
    conn, exps, spec, eid = _decay_env({"W2": 0.9, "W1": 0.1}, "welcome_message")
    _day(conn, "welcome_message", 8, "W2", (3600, 870, 430), "W1", (400, 122, 60))
    first = _decay(conn, exps, spec, eid, 8)
    assert first.kind == "derisk"                                        # exposure cut, nothing reverted
    _day(conn, "welcome_message", 9, "W2", (3600, 990, 490), "W1", (400, 110, 54))     # a quiet day
    assert _decay(conn, exps, spec, eid, 9) is None                      # suspicion cleared, no revert
    _day(conn, "welcome_message", 10, "W2", (3600, 870, 430), "W1", (400, 122, 60))
    assert _decay(conn, exps, spec, eid, 10).kind == "derisk"            # a new first signal: still no revert
    _day(conn, "welcome_message", 11, "W2", (3600, 870, 430), "W1", (400, 122, 60))
    confirmed = _decay(conn, exps, spec, eid, 11)                        # second consecutive window
    assert confirmed.kind == "rollback" and confirmed.patch["allocations"]["default"]["welcome_message"] == {"W1": 1.0}


def test_unconfirmed_derisk_is_offered_back_once_after_clean_windows():
    """Review: one decay signal used to cut a proven winner's share for good. After DERISK_RESTORE_WINDOWS clean
    daily windows the pre-de-risk split is proposed back (routine, approval), once."""
    conn, exps, spec, eid = _decay_env({"W2": 0.9, "W1": 0.1}, "welcome_message")
    _day(conn, "welcome_message", 8, "W2", (3600, 870, 430), "W1", (400, 122, 60))
    assert _decay(conn, exps, spec, eid, 8).kind == "derisk"
    conn.execute("UPDATE experiments SET state='DERISKED' WHERE id=?", (eid,))          # the auto step landed
    for day in (9, 10):
        _day(conn, "welcome_message", day, "W2", (3600, 990, 490), "W1", (400, 110, 54))
        assert _decay(conn, exps, spec, eid, day) is None
    _day(conn, "welcome_message", 11, "W2", (3600, 990, 490), "W1", (400, 110, 54))
    restore = _decay(conn, exps, spec, eid, 11)
    assert restore.kind == "restore" and restore.next_state == "PROMOTED"
    assert restore.patch["allocations"]["default"]["welcome_message"] == {"W2": 0.9, "W1": 0.1}
    _day(conn, "welcome_message", 12, "W2", (3600, 990, 490), "W1", (400, 110, 54))
    assert _decay(conn, exps, spec, eid, 12) is None                                     # asked once only


def test_rejected_rollback_needs_fresh_confirmation_and_is_reasked_at_most_once():
    """Review: rejection cleared revert_requested but not the streak, so the next daily signal re-asked at once,
    every day, spending the tenant's request quota arguing with the client's decision."""
    conn, exps, spec, eid = _decay_env({"W2": 0.9, "W1": 0.1}, "welcome_message")
    bad = ("W2", (3600, 870, 430), "W1", (400, 122, 60))
    _day(conn, "welcome_message", 8, bad[0], bad[1], bad[2], bad[3])
    _decay(conn, exps, spec, eid, 8)
    _day(conn, "welcome_message", 9, *bad)
    assert _decay(conn, exps, spec, eid, 9).kind == "rollback"
    res = json.loads(conn.execute("SELECT result_json FROM experiments WHERE id=?", (eid,)).fetchone()[0])
    res["pending"] = {"prev_state": "PROMOTED", "proposal_id": "wf:1:9"}
    conn.execute("UPDATE experiments SET result_json=? WHERE id=?", (json.dumps(res), eid))
    p = {"refs_json": json.dumps({"experiments": {str(eid): "ROLLED_BACK"}}), "kind": "rollback",
         "proposal_id": "wf:1:9", "payload_json": json.dumps({"impact_score": 0.1})}
    exps.on_terminal(conn, p, "REJECTED", parse("D9 15:00"))
    _day(conn, "welcome_message", 10, *bad)
    assert _decay(conn, exps, spec, eid, 10) is None             # streak restarted: one window is not confirmation
    _day(conn, "welcome_message", 11, *bad)
    assert _decay(conn, exps, spec, eid, 11).kind == "rollback"  # fresh confirmation: one re-ask
    _day(conn, "welcome_message", 12, *bad)
    assert _decay(conn, exps, spec, eid, 12) is None             # cap reached: the client's decision stands


def test_cid_verdict_without_workflow_connections_does_not_crash():
    from controller import detectors
    from controller.metrics import Counts
    out = detectors.cid_verdict(Counts(dials=400, connected=40), Counts(), None, Counts(dials=1000, connected=0))
    assert out["eligible"] and not out["fire"]


def test_batched_proposal_callbacks_use_each_experiments_own_action():
    """Review: routine actions of one workflow share a proposal whose kind is e.g. "promote+restore+stepdown".
    revalidate/on_terminal compared that joined kind with a single kind, so a batched promotion was never
    re-checked and a rejected batched step-down/restore fell into the generic branch (terminal REJECTED,
    leaving a split with no monitoring)."""
    from controller.experiments import Action
    spec = {"workflow_id": "wf", "objective": {"primary": "engagement_rate",
                                                "guardrail": {"pickup_rate_max_drop": 0.02}}}
    conn, _ = _experiments_env()
    store.set_meta(conn, "end_minute", parse("D10 00:00"))
    exps = Experiments(conn, {"wf": spec})

    def exp(dim, state, control, arm, res):
        return conn.execute("INSERT INTO experiments(wf, dim, kpi, stage, state, control, arms_json, screened_json,"
                            " result_json, start_version) VALUES('wf',?,'engagement_rate',2,?,?,?,'[]',?,1)",
                            (dim, state, control, json.dumps([arm]), json.dumps(res))).lastrowid
    promote = exp("welcome_message", "STAGE2", "W1", "W2", {})
    stepdown = exp("voice", "STAGE2", "V1", "V3", {})
    restore = exp("caller_id", "DERISKED", "C1", "C2", {"d_max": 4})
    acts = [Action("promote", promote, "PROMOTED", {"allocations": {"default": {"welcome_message": {"W2": 0.9,
                                                                                                    "W1": 0.1}}}},
                   "s", "r", 0.1),
            Action("stepdown", stepdown, "MONITORING_SPLIT", {"allocations": {"default": {"voice": {"V1": 0.9,
                                                                                                  "V3": 0.1}}}},
                   "s", "r", 0.1),
            Action("restore", restore, "PROMOTED", {"allocations": {"default": {"caller_id": {"C2": 0.9,
                                                                                            "C1": 0.1}}}},
                   "s", "r", 0.1)]
    exps._make_draft("wf", acts, "approval", False, parse("D6 12:00"))
    p = conn.execute("SELECT * FROM proposals").fetchone()
    assert p["kind"] == "promote+restore+stepdown"
    ok, why = exps.revalidate(conn, p, parse("D6 13:00"))         # no data: the batched promotion must not pass
    assert not ok and "promotion no longer passes" in why
    exps.on_terminal(conn, p, "REJECTED", parse("D6 14:00"))
    state = {r["id"]: r["state"] for r in conn.execute("SELECT id, state FROM experiments")}
    assert state[promote] == "REJECTED"
    assert state[stepdown] == "MONITORING_SPLIT"                  # 50/50 kept, still monitored
    assert state[restore] == "DERISKED"                           # reduced share kept, still monitored


def test_decay_budget_is_fixed_at_first_entry_into_monitoring():
    """Review: re-entering monitoring recomputed D_max from the days left, dropping spent checks from the split."""
    conn, exps, spec, eid = _decay_env({"W2": 0.9, "W1": 0.1}, "welcome_message")    # d_max 4 at promotion
    exp = conn.execute("SELECT * FROM experiments WHERE id=?", (eid,)).fetchone()
    assert exps._d_max(json.loads(exp["result_json"]), parse("D10 13:00")) == 4      # 2 days left, budget stays 4
    assert exps._d_max({}, parse("D10 13:00")) == 2                                   # first entry: days left


def test_unexplained_rejection_is_requeued_once_from_fresh_data_on_the_next_approver_day():
    """Review: one random "approver declined (judgement call)" ended nw_renewal's whole experiment programme.
    Memo 05 treats an expiry as a rejection to re-queue with fresh data; an unexplained rejection gets the same,
    once. A second one, or a rejection with a specific reason, is final."""
    spec = {"workflow_id": "wf", "tenant_id": "t", "objective": {"primary": "engagement_rate",
                                                                 "guardrail": {"pickup_rate_max_drop": 0.02}},
            "options": {"voice": ["V1", "V2", "V3"]}, "governance": {"approver_hours": [10, 19]}}

    def rejected_explore(reason):
        conn, _ = _experiments_env()
        store.set_meta(conn, "end_minute", parse("D10 00:00"))
        exps = Experiments(conn, {"wf": spec})
        exps._stage1_mde = lambda exp, spec: {}                   # no call history in this fixture
        eid = conn.execute("INSERT INTO experiments(wf, dim, kpi, stage, state, control, arms_json, screened_json,"
                           " result_json) VALUES('wf','voice','engagement_rate',1,'PLANNED','V1','[]','[]','{}')"
                           ).lastrowid

        def cycle(minute):
            exp = conn.execute("SELECT * FROM experiments WHERE id=?", (eid,)).fetchone()
            act = exps._plan_stage1(exp, spec, parse(minute))
            if act is None:
                return None
            exps._make_draft("wf", [act], "approval", False, parse(minute))
            p = conn.execute("SELECT * FROM proposals ORDER BY rowid DESC LIMIT 1").fetchone()
            conn.execute("UPDATE proposals SET reasons=? WHERE proposal_id=?", (json.dumps([reason]),
                                                                              p["proposal_id"]))
            exps.on_terminal(conn, conn.execute("SELECT * FROM proposals WHERE proposal_id=?",
                                                (p["proposal_id"],)).fetchone(), "REJECTED", parse(minute))
            return p["proposal_id"]

        def state():
            return conn.execute("SELECT state FROM experiments WHERE id=?", (eid,)).fetchone()[0]
        return cycle, state

    cycle, state = rejected_explore("approver declined (judgement call)")
    first = cycle("D0 14:00")
    assert state() == "PLANNED"                                   # re-queued, not ended
    assert cycle("D0 18:00") is None and cycle("D1 09:59") is None  # not before the next approver day
    second = cycle("D1 10:00")
    assert second and second != first                             # re-derived: a new proposal, not a resubmit
    assert state() == "REJECTED"                                  # second rejection is final

    cycle, state = rejected_explore("approver fatigue: more than 4 requests in 24h for this workflow")
    cycle("D0 14:00")
    assert state() == "REJECTED"                                  # a specific reason is never re-queued
