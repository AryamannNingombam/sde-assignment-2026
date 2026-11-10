"""Crash safety: governance transitions and reconcile against a fake simulator, and ingest idempotency.

Every test that "loses a response" models a timeout or a kill -9 between the server acting and us recording it.
"""
import json

import pytest

from controller import configs, governance, store
from controller.clock import Clock, parse
from controller.ingest import Ingestor
from tests.fakes import FakeSim, call_line, campaign_line, lead_line

SPEC = {"workflow_id": "wf", "tenant_id": "t", "mid_flight": "allowed", "cadence": [2, 3, 3],
        "daily_batch": {"size": 100}, "objective": {"primary": "engagement_rate"},
        "governance": {"auto_apply": {"enabled": True, "allowed_dims": ["caller_id"], "max_shift": 0.5},
                       "approver_hours": [10, 19], "approver_latency_minutes": [30, 240], "proposal_ttl_hours": 24,
                       "apply_window_hours": 2, "max_requests_per_24h": 3}}
VOICE = {"allocations": {"default": {"voice": {"V1": 0.8, "V2": 0.2}}}}
CID = {"allocations": {"default": {"caller_id": {"D1": 0.95, "D2": 0.05}}}}


class Recorder:
    def __init__(self):
        self.applied, self.terminal = [], []

    def revalidate(self, conn, p, minute):
        return True, "ok"

    def on_applied(self, conn, p, version, minute):
        self.applied.append((p["proposal_id"], version))

    def on_terminal(self, conn, p, state, minute):
        self.terminal.append((p["proposal_id"], state))


@pytest.fixture
def env():
    sim, conn, owner = FakeSim(), store.connect(":memory:"), Recorder()
    clock = Clock("2027-01-04T00:00:00+05:30")
    configs.sync(conn, sim, clock, "wf")
    gov = governance.Governance(conn, sim, clock, {"wf": SPEC}, {"o": owner})
    return sim, conn, owner, gov


def draft(conn, patch=VOICE, path="approval", urgent=False, minute=None):
    minute = parse("D1 10:00") if minute is None else minute
    did = store.record_decision(conn, minute, "wf", "test", "test", {}, "draft")
    return governance.draft(conn, minute, "wf", "test", patch, {"change_summary": "s", "rationale": "r",
                                                                "impact_score": 0.1},
                            owner="o", refs={}, decision_id=did, path=path, urgent=urgent)


def state(conn, pid):
    return conn.execute("SELECT state FROM proposals WHERE proposal_id=?", (pid,)).fetchone()[0]


def test_happy_path_submit_approve_apply(env):
    sim, conn, owner, gov = env
    pid = draft(conn)
    sim.now = parse("D1 11:00")
    gov.step(sim.now)
    assert state(conn, pid) == "PENDING"
    sim.decide("apr_00001", "approved")
    gov.step(sim.now)
    assert state(conn, pid) == "APPLIED" and owner.applied == [(pid, 2)]
    assert configs.current(conn, "wf")[1]["allocations"]["default"]["voice"] == {"V1": 0.8, "V2": 0.2}
    assert conn.execute("SELECT COUNT(*) FROM decisions WHERE proposal_id=?", (pid,)).fetchone()[0] >= 4


def test_lost_submit_response_is_reconciled_not_resubmitted(env):
    sim, conn, owner, gov = env
    pid = draft(conn)
    sim.now = parse("D1 11:00")
    sim.lose_response.add("submit_approval")
    gov.step(sim.now)
    assert state(conn, pid) == "SUBMITTING"          # unknown outcome: intent row stays
    gov.step(sim.now)                                # reconcile finds it by proposal_id
    assert state(conn, pid) == "PENDING" and sim.calls["submit_approval"] == 1
    assert len(sim.store) == 1


def test_submit_that_never_landed_is_resent_with_the_same_id(env):
    sim, conn, owner, gov = env
    pid = draft(conn)
    conn.execute("UPDATE proposals SET state='SUBMITTING', base_version=1, config_json=?, payload_json=?"
                 " WHERE proposal_id=?", (json.dumps(configs.apply_patch(sim.config("wf")["config"], VOICE)),
                                          json.dumps({"rationale": "r", "body": {"proposal_id": pid, "base_version": 1}}),
                                          pid))       # as if we died right after committing the intent
    gov.reconcile("wf", parse("D1 11:00"))
    assert state(conn, pid) == "PENDING" and sim.store["apr_00001"]["proposal_id"] == pid


def test_lost_apply_response_never_applies_twice(env):
    sim, conn, owner, gov = env
    pid = draft(conn)
    sim.now = parse("D1 11:00")
    gov.step(sim.now)
    sim.decide("apr_00001", "approved")
    sim.lose_response.add("apply")
    gov.step(sim.now)
    assert state(conn, pid) == "APPLYING"
    gov.step(sim.now)
    assert state(conn, pid) == "APPLIED" and sim.calls["apply"] == 1 and len(sim.versions) == 2


def test_stale_because_of_supervisor_is_not_reproposed(env):
    sim, conn, owner, gov = env
    pid = draft(conn)
    sim.now = parse("D1 11:00")
    gov.step(sim.now)
    sim.decide("apr_00001", "approved")
    sim.supervisor_edit(voice={"V3": 1.0})
    gov.step(sim.now)
    assert state(conn, pid) == "STALE" and owner.terminal == [(pid, "STALE")]
    assert conn.execute("SELECT COUNT(*) FROM proposals").fetchone()[0] == 1
    assert sim.versions[-1]["config"]["allocations"]["default"]["voice"] == {"V3": 1.0}     # their edit stands


def test_stale_because_of_our_own_change_is_rebased(env):
    sim, conn, owner, gov = env
    pid = draft(conn)
    sim.now = parse("D1 11:00")
    gov.step(sim.now)                                # voice request is pending
    draft(conn, CID, path="auto", urgent=True, minute=sim.now)
    gov.step(sim.now)                                # our caller-ID rotation auto-applies: base moves to v2
    sim.decide("apr_00001", "approved")
    gov.step(sim.now)                                # apply -> 409 stale -> same patch re-drafted on v2
    rows = conn.execute("SELECT proposal_id, state, parent_proposal_id FROM proposals ORDER BY created_minute,"
                        " proposal_id").fetchall()
    redraft = [r for r in rows if r["parent_proposal_id"] == pid]
    assert state(conn, pid) == "STALE" and len(redraft) == 1


def test_lapse_and_expiry_notify_the_owner(env):
    sim, conn, owner, gov = env
    pid = draft(conn)
    sim.now = parse("D1 11:00")
    gov.step(sim.now)
    sim.decide("apr_00001", "approved", at=sim.now)
    sim.now += 180                                    # missed the 2h apply window
    gov.step(sim.now)
    assert state(conn, pid) == "LAPSED" and owner.terminal == [(pid, "LAPSED")]
    pid2 = draft(conn, minute=sim.now)
    sim.now = parse("D2 11:00")
    gov.step(sim.now)
    sim.decide("apr_00002", "expired")
    gov.step(sim.now)
    assert state(conn, pid2) == "EXPIRED"


def test_auto_apply_403_falls_back_to_approval_and_pages(env):
    sim, conn, owner, gov = env
    sim.auto_dims = ()                                # policy changed under us
    pid = draft(conn, CID, path="auto", urgent=True)
    sim.now = parse("D1 11:00")
    gov.step(sim.now)
    assert state(conn, pid) == "NOT_PERMITTED"
    child = conn.execute("SELECT path FROM proposals WHERE parent_proposal_id=?", (pid,)).fetchone()
    assert child["path"] == "approval"
    assert conn.execute("SELECT COUNT(*) FROM alerts WHERE severity='page'").fetchone()[0] == 1


def test_draft_is_dropped_when_supervisor_edits_its_dimension(env):
    sim, conn, owner, gov = env
    pid = draft(conn, minute=parse("D1 09:00"))
    sim.now = parse("D1 09:30")
    sim.supervisor_edit(voice={"V2": 1.0})
    configs.sync(conn, sim, Clock("2027-01-04T00:00:00+05:30"), "wf")
    gov.step(parse("D1 11:00"))
    assert state(conn, pid) == "DROPPED" and not sim.store


# ---------------------------------------------------------------- ingest
def _ingestor(sim, conn):
    return Ingestor(conn, sim, Clock("2027-01-04T00:00:00+05:30"))


def _agg(conn):
    return conn.execute("SELECT * FROM agg ORDER BY 1,2,3,4,5,6,7,8,9").fetchall(), \
        conn.execute("SELECT * FROM campaign_kpi").fetchall(), conn.execute("SELECT COUNT(*) FROM calls_log").fetchone()


@pytest.fixture
def chunked():
    sim = FakeSim()
    sim.chunk_lines = {0: [campaign_line(), lead_line("wf:l1"), lead_line("wf:l2")],
                       1: [call_line(lead="wf:l1"), call_line(lead="wf:l2", connected=False, engaged=False,
                                                              disposition="no_answer"),
                           call_line(lead="wf:l2", minute=700, voice="V2", engaged=False, disposition="short_hangup")]}
    return sim


def test_ingest_twice_changes_nothing(chunked):
    conn = store.connect(":memory:")
    ing = _ingestor(chunked, conn)
    ing.catch_up()
    once = _agg(conn)
    ing.catch_up()
    ing.ingest_chunk(1, "events")
    assert _agg(conn) == once and store.get_meta(conn, "last_chunk") == 1
    dials, connected, concluded = conn.execute("SELECT SUM(dials), SUM(connected), SUM(concluded) FROM agg").fetchone()
    assert (dials, connected, concluded) == (3, 2, 1)
    assert tuple(conn.execute("SELECT uploaded, declared_leads, concluded FROM campaign_kpi").fetchone()) == (2, 2, 1)


def test_crash_before_commit_then_reingest_gives_identical_aggregates(chunked):
    clean = store.connect(":memory:")
    _ingestor(chunked, clean).catch_up()

    conn = store.connect(":memory:")
    ing = _ingestor(chunked, conn)
    ing.ingest_chunk(0, "events")

    def boom(n):
        raise RuntimeError("killed mid-ingest")
    ing.before_commit = boom
    with pytest.raises(RuntimeError):
        ing.ingest_chunk(1, "events")
    assert store.get_meta(conn, "last_chunk") == 0 and conn.execute("SELECT COUNT(*) FROM agg").fetchone()[0] == 0
    ing.before_commit = lambda n: None
    ing.catch_up()
    assert _agg(conn) == _agg(clean)


def test_engaged_disposition_mismatch_raises_an_alert_not_a_crash():
    sim = FakeSim()
    sim.chunk_lines = {0: [campaign_line(leads=1), lead_line(), call_line(engaged=False)]}
    conn = store.connect(":memory:")
    _ingestor(sim, conn).catch_up()
    assert conn.execute("SELECT COUNT(*) FROM alerts WHERE severity='page'").fetchone()[0] == 1
