"""Decision rule (exp_rules) and allocation arithmetic (exp_alloc)."""
import random

import pytest

from controller import exp_alloc, exp_rules as er, exp_stats as es, settings


def rows(n_leads, rate, per_lead=2, seed=0, offset=0):
    rng = random.Random(seed)
    return {offset + i: (float(per_lead), float(sum(rng.random() < rate for _ in range(per_lead)))) for i in range(n_leads)}


def arm_data(rate, n_leads=900, recent_rate=None, seed=0, offset=0, pickup=0.3):
    eng = rows(n_leads, rate, seed=seed, offset=offset)
    rec = rows(n_leads // 5, rate if recent_rate is None else recent_rate, seed=seed + 1, offset=offset)
    rng = random.Random(seed + 2)
    pick = {offset + i: (4.0, float(sum(rng.random() < pickup for _ in range(4)))) for i in range(n_leads)}
    return er.ArmData(eng, rec, pick)


def look(data, **kw):
    args = dict(control="C", active=["A"], family=1, alpha=0.05, arm_t={}, looks_taken=0, ramped=[], exposure_days=3.0,
                max_drop=0.02)
    args.update(kw)
    return er.daily_look(data, args.pop("control"), args.pop("active"), args.pop("family"), args.pop("alpha"), **args)


def test_alloc_entry_respects_the_cap_and_catalogue_order():
    assert exp_alloc.entry_shares(["A", "B", "C", "D"]) == {"A": 0.075, "B": 0.075, "C": 0.075}
    assert exp_alloc.weights("X", {"A": 0.075})["X"] == pytest.approx(0.925)


def test_alloc_ramp_keeps_control_at_least_forty_percent():
    s = exp_alloc.next_shares({"A": 0.075, "B": 0.075, "C": 0.075}, ["A", "B", "C"], [])
    assert sum(s.values()) <= 0.6 + 1e-9 and all(v >= 0.075 for v in s.values())
    s = exp_alloc.next_shares({"A": 0.075, "B": 0.075}, ["A"], ["B"])
    assert s == {"A": 0.2}


def test_alloc_rotates_an_untested_option_in_when_room_exists():
    s = exp_alloc.next_shares({"A": 0.075, "B": 0.075, "C": 0.075}, [], ["B"], ["D"])
    assert set(s) == {"A", "C", "D"}
    assert exp_alloc.next_shares({"A": 0.2, "B": 0.2}, [], [], ["D"]) == {"A": 0.2, "B": 0.2}


def test_promotion_weights_leave_a_ten_percent_holdout():
    assert exp_alloc.promotion_weights("W3", "W1") == {"W3": 0.9, "W1": 0.1}


def test_harm_stop_needs_z_and_volume():
    s = {"A": {"ok": True, "z": -3.2, "n_arm": 160}, "B": {"ok": True, "z": -3.5, "n_arm": 100},
         "C": {"ok": True, "z": -2.6, "n_arm": 200}, "D": {"ok": True, "z": -1.0, "n_arm": 900}}
    assert er.harm_stops(s) == {"A": "now", "C": "fold"}


def test_ramp_a_non_negative_arm_and_drop_a_losing_one():
    data = {"C": arm_data(0.5, seed=1, offset=10_000), "A": arm_data(0.5, seed=2), "B": arm_data(0.4, seed=3, offset=20_000)}
    out = look(data, active=["A", "B"], family=2)
    assert "B" in out.drop and "A" not in out.drop
    assert out.ramp in (["A"], [])  # point estimate decides; A is at parity
    out = look(data, active=["A", "B"], family=2, exposure_days=0.5)
    assert out.drop == [] and out.ramp == []


def test_clear_stable_winner_is_promoted():
    data = {"C": arm_data(0.45, 4000, seed=1, offset=100_000), "A": arm_data(0.55, 4000, seed=2)}
    out = look(data)
    assert out.took_look and out.winner == "A"
    rec = out.records["A"]
    assert rec["winner_ok"] and rec["lift"] > 0.2 and rec["boundary"] and rec["rank"] == 1 and rec["pickup_ok"]


def test_decaying_arm_is_never_promoted():
    data = {"C": arm_data(0.45, 4000, seed=1, offset=100_000), "A": arm_data(0.55, 4000, recent_rate=0.44, seed=2)}
    data["C"] = er.ArmData(data["C"].engaged, rows(800, 0.45, seed=9, offset=100_000), data["C"].pickup)
    out = look(data)
    rec = out.records["A"]
    assert rec["rejected"] and not rec["recent_ok"] and out.winner is None


def test_small_lift_and_failed_guardrail_block_promotion():
    big = {"C": arm_data(0.5, 20000, seed=1, offset=1_000_000), "A": arm_data(0.512, 20000, seed=2)}
    out = look(big)
    assert out.records["A"]["lift"] < settings.EXP_MIN_POINT_LIFT and out.winner is None
    bad_pickup = {"C": arm_data(0.45, 4000, seed=1, offset=100_000), "A": arm_data(0.55, 4000, seed=2, pickup=0.2)}
    out = look(bad_pickup)
    assert not out.records["A"]["pickup_ok"] and out.winner is None


def test_look_gating_and_information_history():
    data = {"C": arm_data(0.5, 100, seed=1, offset=100_000), "A": arm_data(0.5, 100, seed=2)}
    out = look(data)
    assert not out.took_look and out.arm_t == {}  # information below the first planned fraction: no look taken
    full = {"C": arm_data(0.45, 4000, seed=1, offset=100_000), "A": arm_data(0.55, 4000, seed=2)}
    assert look(full, looks_taken=4).took_look is False  # at most four planned looks


def test_same_data_same_decision():
    data = {"C": arm_data(0.45, 4000, seed=1, offset=100_000), "A": arm_data(0.5, 4000, seed=2)}
    assert look(data).records == look(data).records


def test_design_information_matches_the_power_formula():
    assert er.design_information() == pytest.approx(680, rel=0.01)
