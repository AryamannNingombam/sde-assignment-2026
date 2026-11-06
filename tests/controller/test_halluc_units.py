"""Unit tests: segment test, fix selection, credit reserve, tracker segments."""
import json

import pytest

from controller import incidents, settings
from controller.desired import PlanContext
from controller.detectors import halluc as hl
from controller.detectors import halluc_data as hd

WF = {"workflow_id": "w", "governance": {"min_validation_pass_rate": 0.97},
      "objective": {"primary": "engagement_rate", "guardrail": {"pickup_rate_max_drop": 0.02}}}


# ------------------------------------------------------------------ segment test
def test_segment_test_triggers_on_a_real_spike_with_enough_connects():
    base = [14000, 206, 14000 * 0.93, 7000]
    seg = [250, 14, 250 * 0.85, 120]  # 5.6% vs 1.5%
    t = hl.segment_test(seg, base)
    assert t["triggered"] and t["p"] < settings.HALLUC_P and t["corroborated"]


def test_segment_test_needs_min_connects_and_ignores_noise():
    base = [14000, 206, 13000.0, 7000]
    assert not hl.segment_test([120, 12, 110.0, 60], base)["triggered"]  # high rate, too few connects
    assert not hl.segment_test([400, 7, 372.0, 200], base)["triggered"]  # 1.75%: noise
    assert not hl.segment_test([400, 2, 372.0, 200], base)["triggered"]  # lower is never an alert


def test_adherence_drop_corroborates_a_borderline_rate():
    base = [14000, 206, 14000 * 0.93, 7000]
    seg = [220, 8, 220 * 0.89, 100]  # 3.6%: p between 0.001 and 0.01
    t = hl.segment_test(seg, base)
    assert 0.001 <= t["p"] < 0.01 and t["triggered"]
    seg_no_adh = [220, 8, 220 * 0.93, 100]
    assert not hl.segment_test(seg_no_adh, base)["triggered"]


def test_engagement_guardrail():
    base = [1000, 15, 930.0, 500]
    assert hl.engagement_ok([400, 5, 372.0, 190], base, 0.02)[0]  # 47.5% vs 50%: within noise
    assert not hl.engagement_ok([2000, 20, 1860.0, 800], base, 0.02)[0]  # 40%: strict-script trap


# ------------------------------------------------------------------ fix ranking
def test_ranking_uses_failure_upper_bound_not_just_the_bar():
    runs = [{"prompt": "P5", "pass_rate": 0.9933, "n": 300}, {"prompt": "P3", "pass_rate": 1.0, "n": 300},
            {"prompt": "P4", "pass_rate": 0.9733, "n": 300}, {"prompt": "P9", "pass_rate": 0.96, "n": 300}]
    ranked = hl.rank_by_failure_bound(runs, 0.97)
    assert [r["prompt"] for r in ranked] == ["P3", "P5", "P4"]  # P9 below the bar is dropped
    assert ranked[0]["fail_ub"] < ranked[1]["fail_ub"] < ranked[2]["fail_ub"]


# ------------------------------------------------------------------ credits
def test_credit_reserve_rules():
    assert incidents.can_spend(200, 3, 3)  # routine, far above 3 x 25
    assert not incidents.can_spend(77, 3, 3)  # would dip below the 75 reserve
    assert incidents.can_spend(40, 3, 3, incident_spent=0)  # incident may use the reserve
    assert not incidents.can_spend(2, 3, 3, incident_spent=0)  # never more than we have (no 402)
    assert not incidents.can_spend(200, 3, 3, incident_spent=24)  # one incident is capped at the reserve
    assert incidents.validation_cost(300) == 3 and incidents.validation_cost(50) == 1


class FakeClient:
    def __init__(self, credits=200.0, suggestions=("P3", "P4", "P5")):
        self.credits = credits
        self.suggest_calls = 0
        self.validations: list[tuple[str, int]] = []
        self.suggestions = suggestions
        self.rates = {"P1": 0.9933, "P3": 1.0, "P4": 0.9733, "P5": 0.9967, "P2": 0.9}

    def credits_remaining(self):
        return self.credits

    def suggest_fixes(self, wid, problem):
        self.suggest_calls += 1
        self.credits -= 3
        return {"suggestions": [{"prompt_version": p, "summary": ""} for p in self.suggestions],
                "credits_remaining": self.credits}

    def run_validation(self, wid, prompt, n):
        self.validations.append((prompt, n))
        self.credits -= -(-n // 100)
        return {"validation_run_id": f"val_{len(self.validations):05d}", "workflow_id": wid,
                "prompt_version": prompt, "n": n, "failures": 0, "pass_rate": self.rates[prompt],
                "credits_remaining": self.credits}


def ctx_for(store, client, now=5000, n_wf=3):
    return PlanContext(store, client, {f"w{i}": WF for i in range(n_wf)} | {"w": WF}, now)


def new_body(stats=None):
    return hl._new_body("P2", "P1", stats or {"rate": 0.055, "base_rate": 0.015, "n": 300, "p": 1e-6},
                        {"actor": "supervisor", "minute": 4000}, "prompt_flag_spike")


def state_with_known_good():
    st = hd.fresh_state()
    st["done"] = {"P1": {"c": [14000, 210, 13000.0, 7000], "last_ts": 3000}}
    return st


def test_revert_to_known_good_uses_stored_validation_and_no_credits(store):
    client = FakeClient()
    incidents.store_validation(store, {"validation_run_id": "val_x", "workflow_id": "w", "prompt_version": "P1",
                                       "n": 300, "pass_rate": 0.99}, 3, 0)
    body = new_body()
    hl.prepare_fix(ctx_for(store, client), "w", body, state_with_known_good(), "P2")
    assert body["target"] == "P1" and body["candidates"][0]["validation_run_id"] == "val_x"
    assert client.suggest_calls == 0 and client.validations == [] and body["credits_spent"] == 0


def test_without_known_good_asks_llm_validates_all_and_ranks(store):
    client = FakeClient()
    body = new_body()
    hl.prepare_fix(ctx_for(store, client), "w", body, hd.fresh_state(), "P2")
    assert client.suggest_calls == 1 and [p for p, _ in client.validations] == ["P3", "P4", "P5"]
    assert all(n == 300 for _, n in client.validations)
    assert [c["prompt"] for c in body["candidates"]] == ["P3", "P5", "P4"]  # lowest failure bound first
    assert body["target"] == "P3" and body["credits_spent"] == 12
    assert all(c["source"] == "llm" for c in body["candidates"])
    rows = store.conn.execute("select count(*) from llm_calls").fetchone()[0]
    assert rows == 4  # suggest + three validations all in the ledger


def test_verify_failure_moves_to_next_candidate_without_new_credit_use(store):
    client = FakeClient()
    body = new_body()
    hl.prepare_fix(ctx_for(store, client), "w", body, hd.fresh_state(), "P2")
    spent = client.credits
    body["tried"].append("P3")
    hl.prepare_fix(ctx_for(store, client), "w", body, hd.fresh_state(), "P3")
    assert body["target"] == "P5" and client.credits == spent


def test_incident_credit_cap_stops_spend_and_alerts(store):
    client = FakeClient()
    body = new_body()
    body["credits_spent"] = 23
    hl.prepare_fix(ctx_for(store, client), "w", body, hd.fresh_state(), "P2")
    assert client.suggest_calls == 0 and body["target"] is None  # 23 + 3 > 25: no speculative call
    assert store.conn.execute("select count(*) from alerts where code='suggest_fixes_unaffordable'").fetchone()[0] == 1


def test_low_credits_never_call_the_sim(store):
    client = FakeClient(credits=2.0)
    body = new_body()
    hl.prepare_fix(ctx_for(store, client), "w", body, hd.fresh_state(), "P2")
    assert client.suggest_calls == 0 and client.validations == []


def test_failing_known_good_validation_falls_back_to_llm(store):
    client = FakeClient()
    client.rates["P1"] = 0.90
    body = new_body()
    hl.prepare_fix(ctx_for(store, client), "w", body, state_with_known_good(), "P2")
    assert ("P1", 300) in client.validations and client.suggest_calls == 1 and body["target"] == "P3"


# ------------------------------------------------------------------ tracker segments
def add_calls(store, rows):
    for i, (ts, prompt, flag, adh, eng) in enumerate(rows):
        store.conn.execute("INSERT INTO calls(event_id, workflow_id, ts_minute, day, hour, lid, attempt_no,"
                           " config_version, cohort_id, welcome, voice, caller_id, prompt, connected, engaged,"
                           " halluc_flag, adherence) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (store.count("calls") + 1, "w", ts, ts // 1440, ts % 1440 // 60, 1, 1, 1, "default",
                            "W1", "V1", "D1", prompt, 1, eng, flag, adh))


def test_tracker_segments_start_at_prompt_change_and_baseline_freezes(store):
    hist = [(-600 + i, "P1", i % 50 == 0, 0.93, i % 2) for i in range(500)]
    add_calls(store, hist)
    st = hd.update(store, "w")
    assert st["seg"]["prompt"] == "P1" and st["seg"]["c"][0] == 500 and not st["base_frozen"]
    live = [(10 + i, "P1", 0, 0.93, 1) for i in range(100)] + [(200 + i, "P2", i % 10 == 0, 0.8, 0) for i in range(60)]
    add_calls(store, live)
    st = hd.update(store, "w")
    assert st["base_frozen"] and st["base"][0] == 500  # history only, live data never leaks into it
    assert st["seg"]["prompt"] == "P2" and st["seg"]["c"][0] == 60 and st["seg"]["start"] == 200
    assert st["done"]["P1"]["c"][0] == 600
    assert hd.known_good_candidates(st, "P2")[0][0] == "P1"
    assert hd.known_good_candidates(st, "P1") == []
    assert hd.window_counts(st, 300)[0] == 60  # buckets reset with the segment


def test_tracker_is_incremental_and_restart_safe(store):
    add_calls(store, [(i, "P1", 0, 0.9, 1) for i in range(100)])
    hd.update(store, "w")
    add_calls(store, [(100 + i, "P1", 1, 0.9, 1) for i in range(50)])
    st = hd.update(store, "w")
    again = hd.update(store, "w")
    assert st["seg"]["c"][0] == 150 == again["seg"]["c"][0] and again["seg"]["c"][1] == 50
