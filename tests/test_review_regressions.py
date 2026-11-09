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


def test_inconclusive_keeps_a_challenger_that_is_ahead_and_reverts_one_that_is_not():
    """Review: 'inconclusive' means not proven better, not that control is better (pre-registered rule)."""
    from controller.metrics import Counts
    spec = {"workflow_id": "wf", "objective": {"primary": "engagement_rate",
                                                "guardrail": {"pickup_rate_max_drop": 0.02}}}
    for ch_rate, expect_keep in ((0.524, True), (0.490, False)):
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
        if expect_keep:
            assert action is None and state == "PROMOTED"          # split kept, monitored daily, no request
        else:
            assert action.kind == "conclude" and action.patch["allocations"]["default"]["voice"] == {"V1": 1.0}
