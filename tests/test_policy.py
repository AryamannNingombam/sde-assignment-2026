"""Policy helpers: TV distance, auto-apply eligibility, approver timing, quota, and the rollback routing rule for
each of the three public workflow policies (SUBMISSION §5, rollback routing)."""
import pytest

from controller import configs, policy, store
from controller.clock import parse

ALLOC = {"welcome_message": {"W1": 1.0}, "voice": {"V1": 1.0}, "caller_id": {"D1": 0.5, "D2": 0.5}}


def cfg(**dims):
    return {"cohorts": [], "allocations": {"default": {**ALLOC, **dims}}, "prompt_version": "P1",
            "schedule": {"hour_weights": {}, "lead_preferred_hour": {}}}


def spec(auto_enabled=True, dims=("schedule", "caller_id"), max_shift=0.5, hours=(10, 19), latency=(30, 240),
         tenant="northwind_life", quota=3, ttl=24):
    return {"workflow_id": "wf", "tenant_id": tenant, "governance": {
        "auto_apply": {"enabled": auto_enabled, "allowed_dims": list(dims), "max_shift": max_shift},
        "approver_hours": list(hours), "approver_latency_minutes": list(latency), "proposal_ttl_hours": ttl,
        "apply_window_hours": 2, "max_requests_per_24h": quota}}


RENEWAL = spec()
KESTREL = spec(dims=("schedule", "caller_id", "welcome_message", "voice"), max_shift=0.2, latency=(20, 120),
               tenant="kestrel_finance", quota=4, ttl=12)
KYC = spec(auto_enabled=False, dims=(), max_shift=0, hours=(10, 18), latency=(60, 480), quota=2)


def test_tv_matches_the_simulators_probe_case():
    old, new = cfg(voice={"V1": 0.85, "V2": 0.15}), cfg(voice={"V2": 1.0})
    assert configs.tv_shift(old, new) == pytest.approx(0.85)
    assert configs.changed_dims(old, new) == ["voice"]


def test_auto_apply_eligibility():
    rotate = cfg(caller_id={"D1": 0.95, "D2": 0.05})
    assert policy.auto_apply_eligible(RENEWAL, cfg(), rotate)[0]                       # 0.45 <= 0.5
    ok, why = policy.auto_apply_eligible(RENEWAL, cfg(), cfg(voice={"V1": 0.9, "V2": 0.1}))
    assert not ok and "not permitted" in why[0]
    assert not policy.auto_apply_eligible(KYC, cfg(), rotate)[0]                        # disabled


@pytest.mark.parametrize("pol, expected", [
    (RENEWAL, ["approval"]),                  # voice not auto-appliable
    (KESTREL, ["auto", "approval"]),          # de-risk step of max_shift, then the full revert via approval
    (KYC, ["approval"]),                      # auto-apply disabled
])
def test_post_promotion_rollback_routes(pol, expected):
    promoted, control = cfg(voice={"V3": 0.9, "V1": 0.1}), cfg()
    route = policy.route_change(pol, promoted, control)
    assert [r[0] for r in route] == expected
    if len(route) == 2:
        step = route[0][1]
        assert configs.tv_shift(promoted, step) <= pol["governance"]["auto_apply"]["max_shift"]
        assert policy.auto_apply_eligible(pol, promoted, step)[0]
        assert route[1][1] == control


def test_abort_within_max_shift_is_a_single_auto_apply_on_kestrel():
    exploring = cfg(voice={"V1": 0.8, "V2": 0.1, "V3": 0.1})
    abort = cfg(voice={"V1": 0.9, "V3": 0.1})
    assert [r[0] for r in policy.route_change(KESTREL, exploring, abort)] == ["auto"]


def test_approver_window_edges_and_tenant_hour():
    assert not policy.can_submit_now(RENEWAL, parse("D1 09:45"), urgent=False)[0]
    assert policy.can_submit_now(RENEWAL, parse("D1 10:00"), urgent=False)[0]
    assert not policy.can_submit_now(RENEWAL, parse("D1 16:30"), urgent=False)[0]      # p75 latency 187m spills
    assert policy.can_submit_now(RENEWAL, parse("D1 16:30"), urgent=True)[0]           # decided before expiry
    assert not policy.can_submit_now(KESTREL, parse("D1 10:30"), urgent=True)[0]       # Kestrel: after 11:00


def test_routine_proposals_expire_at_end_of_approver_day():
    assert policy.expires_in_hours(RENEWAL, parse("D1 11:00"), urgent=False) == 8
    assert policy.expires_in_hours(RENEWAL, parse("D1 11:00"), urgent=True) == 24


def test_quota_keeps_a_reserved_slot():
    conn = store.connect(":memory:")
    for i, m in enumerate((parse("D1 10:00"), parse("D1 12:00"))):
        conn.execute("INSERT INTO proposals(proposal_id, wf, path, state, submitted_minute) VALUES(?, 'wf',"
                     " 'approval', 'PENDING', ?)", (f"p{i}", m))
    now = parse("D1 15:00")
    assert policy.quota_left(conn, RENEWAL, "wf", now, urgent=False) == 0               # 3 - 1 reserved - 2 used
    assert policy.quota_left(conn, RENEWAL, "wf", now, urgent=True) == 1
    assert policy.quota_left(conn, RENEWAL, "wf", parse("D2 12:30"), urgent=False) == 2  # rolling 24h


def test_tenant_cap_is_stricter_than_policy():
    conn = store.connect(":memory:")
    conn.execute("INSERT INTO proposals(proposal_id, wf, path, state, submitted_minute) VALUES('p', 'wf', 'approval',"
                 " 'PENDING', ?)", (parse("D1 11:00"),))
    now = parse("D1 12:00")
    assert policy.quota_left(conn, KESTREL, "wf", now, urgent=False) == 0     # 2/day (memo 04) - 1 reserved - 1 used
    assert policy.quota_left(conn, KESTREL, "wf", now, urgent=True) == 1
    conn.execute("INSERT INTO proposals(proposal_id, wf, path, state, submitted_minute) VALUES('p2', 'wf', 'approval',"
                 " 'PENDING', ?)", (parse("D1 11:30"),))
    assert policy.quota_left(conn, KESTREL, "wf", now, urgent=True) == 0                     # preference reached
    assert policy.quota_left(conn, KESTREL, "wf", now, urgent=True, safety_incident=True) == 2  # policy allows 4


def test_apply_patch_rebases_onto_a_moved_config():
    patch = {"allocations": {"default": {"voice": {"V1": 0.5, "V2": 0.5}}}}
    moved = cfg(caller_id={"D1": 0.95, "D2": 0.05})                                      # our own rotation landed
    out = configs.apply_patch(moved, patch)
    assert out["allocations"]["default"]["voice"] == {"V1": 0.5, "V2": 0.5}
    assert out["allocations"]["default"]["caller_id"] == {"D1": 0.95, "D2": 0.05}
    assert configs.patch_dims(patch) == {"voice"}
