"""A2/A3/A4: probability-based filing window, safe soft caps, budget of one."""
import pytest

from controller import fatigue, settings
from controller.desired import Priority

# public policy values (docs/CONTEXT.md section 3)
NW_RENEWAL = {"approver_hours": [10, 19], "approver_latency_minutes": [30, 240], "proposal_ttl_hours": 24,
              "max_requests_per_24h": 3}
NW_KYC = {"approver_hours": [10, 18], "approver_latency_minutes": [60, 480], "proposal_ttl_hours": 24,
          "max_requests_per_24h": 2}
KS_CANCEL = {"approver_hours": [10, 19], "approver_latency_minutes": [20, 120], "proposal_ttl_hours": 12,
             "max_requests_per_24h": 4}


def at(day, hh, mm=0):
    return day * 1440 + hh * 60 + mm


@pytest.mark.parametrize("gov,wid", [(NW_RENEWAL, "nw_renewal"), (NW_KYC, "nw_kyc"), (KS_CANCEL, "ks_cancel")])
def test_public_policies_have_probability_one_at_every_in_hours_minute(gov, wid):
    lo, hi = gov["approver_hours"]
    for m in range(lo * 60, hi * 60, 7):
        if wid == "ks_cancel" and not 11 * 60 <= m <= 16 * 60:
            continue  # soft cap (not before 11:00); late filings under a 12 h ttl can expire unseen
        assert fatigue.decision_probability(at(1, 0, m), gov) == 1.0, (wid, m)
        assert fatigue.filing_window_ok(at(1, 0, m), gov, True, wid)[0], (wid, m)


def test_short_ttl_still_files_with_partial_probability():
    gov = {**NW_RENEWAL, "proposal_ttl_hours": 3}
    p = fatigue.decision_probability(at(0, 10), gov)
    assert 0.5 < p < 0.9  # latency 30..240 vs a 180 min ttl
    assert not fatigue.filing_window_ok(at(0, 10), gov, True, "x")[0]  # routine needs 0.9
    assert fatigue.filing_window_ok(at(0, 10), gov, False, "x")[0]  # urgent needs only 0.3
    assert fatigue.filing_window_ok(at(0, 10), {**gov, "proposal_ttl_hours": 4}, True, "x")[0]


def test_probability_matches_the_sim_rule_by_brute_force():
    gov = {"approver_hours": [14, 16], "approver_latency_minutes": [20, 240], "proposal_ttl_hours": 3,
           "max_requests_per_24h": 3}
    now = at(2, 14, 30)
    ok = sum(1 for u in range(20, 241)
             if fatigue.next_working(now + u, [14, 16]) <= now + 180)
    assert fatigue.decision_probability(now, gov) == pytest.approx(ok / 221)


@pytest.mark.parametrize("hours,inside,outside", [
    ([0, 24], [0, 5, 23], []),
    ([14, 16], [14, 15], [0, 13, 16, 23]),
    ([22, 6], [22, 23, 0, 5], [6, 12, 21]),  # wraps midnight
])
def test_in_hours_windows(hours, inside, outside):
    for h in inside:
        assert fatigue.in_hours(at(3, h, 30), hours), (hours, h)
    for h in outside:
        assert not fatigue.in_hours(at(3, h, 30), hours), (hours, h)


def test_next_working_mirrors_the_sim_exactly():
    from sim.world import World
    for hours in ([0, 24], [14, 16], [22, 6], [10, 19]):
        for t in range(0, 3 * 1440, 37):
            assert fatigue.next_working(t, hours) == World._next_working(t, hours), (hours, t)


def gov_ks(hours):
    return {**KS_CANCEL, "approver_hours": hours}


def test_soft_cap_honoured_on_public_ks_cancel():
    assert fatigue.soft_cap_ignored(KS_CANCEL, "ks_cancel") is None
    assert not fatigue.filing_window_ok(at(0, 10, 30), KS_CANCEL, True, "ks_cancel")[0]


def test_ks_cancel_with_approver_hours_9_to_11_still_files_routine_work():
    gov = gov_ks([9, 11])
    assert fatigue.soft_cap_ignored(gov, "ks_cancel")
    assert fatigue.filing_window_ok(at(1, 9, 0), gov, True, "ks_cancel")[0]


def test_soft_cap_ignored_when_expiry_rule_cannot_pass_after_it():
    gov = {**KS_CANCEL, "approver_hours": [10, 19], "proposal_ttl_hours": 2,
           "approver_latency_minutes": [20, 400]}
    # after 11:00 no minute reaches P >= 0.9, so the cap would only delay nothing useful: ignored
    assert fatigue.soft_cap_ignored(gov, "ks_cancel")


def test_soft_cap_max_per_day_is_only_a_min():
    assert fatigue.routine_budget(KS_CANCEL, "ks_cancel") == 2
    assert fatigue.routine_budget({**KS_CANCEL, "max_requests_per_24h": 2}, "ks_cancel") == 1


@pytest.mark.parametrize("total,routine,severe,incident", [(1, 1, 1, 1), (2, 1, 1, 2), (3, 1, 2, 3), (4, 2, 3, 4)])
def test_budget_tiers_for_totals_1_to_4(total, routine, severe, incident):
    gov = {"max_requests_per_24h": total}
    assert fatigue.routine_budget(gov, "x") == routine
    assert fatigue.severe_budget(gov) == severe
    assert fatigue.slot_limit(gov, Priority.INCIDENT, "x") == incident
    assert fatigue.slot_available(0, gov, Priority.ROUTINE, "x")[0]
    assert fatigue.slot_available(0, gov, Priority.SEVERE, "x")[0]
