"""A7: a lost state dir must not collide with approvals the sim already holds."""
from controller import proposal_repo as pr
from controller.loop import Controller
from controller.store import Store
from tests.controller.helpers import make_controller, registry_of, run_until, uniform_hours

PID1 = "nw_renewal:1:daily_bundle"


def test_fresh_store_seeds_plan_seq_and_does_not_adopt_an_old_approval(client, store, world, tmp_path):
    ctl = make_controller(client, store, uniform_hours())
    assert run_until(ctl, lambda: len(world.approvals) == 1)
    assert {a["proposal_id"] for a in world.approvals.values()} == {PID1}
    store.close()
    fresh = Store(tmp_path / "lost" / "again.db")  # the state dir was lost
    ctl2 = Controller(client, fresh, registry=registry_of(uniform_hours(hours={str(h): 1 for h in range(10, 20)})))
    ctl2.startup()
    assert ctl2.gov.repo.next_plan_seq("nw_renewal") == 2
    run_until(ctl2, lambda: len(world.approvals) >= 2 or client.state()["sim_minute"] > 1400, limit=300)
    ids = [a["proposal_id"] for a in world.approvals.values()]
    assert len(ids) == len(set(ids))
    assert all(r[0] != PID1 for r in fresh.conn.execute("select proposal_id from proposals"))


def test_adopt_remote_refuses_an_approval_with_a_different_base_version(client, store, world):
    ctl = make_controller(client, store, uniform_hours())
    assert run_until(ctl, lambda: len(world.approvals) == 1)
    (a,) = world.approvals.values()
    gov = ctl.gov
    row = gov.repo.get(PID1)
    # pretend our row (INTENT) targets another base version than the sim's approval under the same id
    store.conn.execute("update proposals set state='INTENT', base_version=?, approval_id=NULL where proposal_id=?",
                       (a["base_version"] + 7, PID1))
    row = gov.repo.get(PID1)
    out = gov._adopt_remote(row, 10)
    assert out.state == pr.STALE
    assert gov.repo.next_plan_seq("nw_renewal") == 2
