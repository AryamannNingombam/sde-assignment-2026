"""Review fixes 8-11: persistence, flat-curve strictness, flag expiry + re-probe, observed shares, all keys."""
import pytest

from controller import incidents, settings
from controller.desired import PlanContext
from controller.detectors import did
from controller.detectors import did_eval as de
from controller.detectors import did_plan as dp
from controller.detectors.fatigue_curve import FatigueCurve
from controller.stats import ratio_drop_test


def step(drop, p, did_="D1"):
    t = ratio_drop_test(60, 200, 90, 200, 100, 400, 190, 400)  # shape only; fields overridden below
    t = type(t)(drop, 5.0, p, 0.2, 0.3)
    return de.StepResult(did_, 3, 300, 300, 600, t, 0.5, 0.5)


def test_a_sudden_15_percent_drop_with_enough_n_is_detectable():
    # 15% drop in pickup ratio, ~8000 dials per side: z > 4.3 (smaller n cannot resolve 15% at p<1e-5; see docs/THRESHOLDS.md)
    t = ratio_drop_test(int(8000 * 0.30 * 0.85), 8000, 8000 * 0.30, 8000, 20000 * 0.30, 20000, 20000 * 0.30, 20000)
    assert t.drop == pytest.approx(0.15, abs=0.01) and t.p < settings.DID_FLAG_P
    assert step(t.drop, t.p).flagged()


def test_min_drop_gate_and_stricter_level_for_a_flat_curve():
    assert step(0.15, 1e-6).flagged() and not step(0.08, 1e-9).flagged()
    assert not step(0.15, 1e-6).flagged(settings.DID_FLAG_P_UNFITTED)  # flat curve: stricter p needed
    assert step(0.15, 1e-9).flagged(settings.DID_FLAG_P_UNFITTED)


def test_flag_must_persist_over_consecutive_evaluations():
    ctx = lambda now: type("C", (), {"now": now})()
    st = {"pending": {}}
    cand = step(0.3, 1e-9)
    assert not did._persisted(ctx(1000), st, cand)
    assert did._persisted(ctx(1015), st, cand)
    assert not did._persisted(ctx(2000), st, cand)
    assert not did._persisted(ctx(2015), st, None) and st["pending"] == {}  # a clean look restarts the count
    assert not did._persisted(ctx(2030), st, cand)
    assert not did._persisted(ctx(2030 + settings.DID_FLAG_PERSIST_GAP_MINUTES + 1), st, cand)  # too far apart


def ev_with(shares, dials=1000):
    ev = de.Evaluation(100, FatigueCurve.flat(), {"D1": 0.0, "D2": 0.0})
    ev.shares, ev.share_dials = shares, dials
    return ev


def test_h_bar_uses_observed_shares_when_known():
    class Curve:
        def h(self, load):
            return 1.0 - load  # health falls with load
    ev = ev_with({"D1": 0.9, "D2": 0.1})
    ev.curve = Curve()
    ev.loads_now = {"D1": 0.5, "D2": 0.0}
    assert did.h_bar(ev, {"D1": 0.5, "D2": 0.5}) == pytest.approx(0.9 * 0.5 + 0.1 * 1.0)
    ev.share_dials = 0  # unknown: fall back to the config allocation
    assert did.h_bar(ev, {"D1": 0.5, "D2": 0.5}) == pytest.approx(0.75)


def ctx_at(store, now):
    return PlanContext(store, None, {"w": {}}, now)


def test_evacuation_incident_closes_on_observed_share_not_config(store):
    store.store_config_body("w", 1, "controller", {"allocations": {"default": {"caller_id": {"D1": 1.0}}},
                                                   "cohorts": [], "prompt_version": "P1", "schedule": {}})
    inc_id = incidents.open_incident(store, "w", "did_flagged", 10, {"did": "D2"})
    did._close_evacuated(ctx_at(store, 5000), "w", ev_with({"D1": 0.8, "D2": 0.2}), {})
    assert store.conn.execute("select state from incidents where id=?", (inc_id,)).fetchone()[0] == "open"
    did._close_evacuated(ctx_at(store, 5100), "w", ev_with({"D1": 1.0}), {})
    assert store.conn.execute("select state from incidents where id=?", (inc_id,)).fetchone()[0] == "closed"
    inc2 = incidents.open_incident(store, "w", "did_flagged", 10, {"did": "D2"})
    did._close_evacuated(ctx_at(store, 5200), "w", ev_with({"D1": 1.0}, dials=10), {})  # unknown share: stays open
    assert store.conn.execute("select state from incidents where id=?", (inc2,)).fetchone()[0] == "open"


def test_config_share_looks_at_every_allocation_key(store):
    cfg = {"allocations": {"default": {"caller_id": {"D1": 1.0}}, "c1": {"caller_id": {"D1": 0.5, "D2": 0.5}}},
           "cohorts": [{"id": "c1"}]}
    assert did._config_share(cfg, "D2") == 0.5 and did._keys(cfg) == ["default", "c1"]


def test_flag_expires_after_cooldown_into_a_reprobe(store):
    st = {"flagged": {"D2": {"minute": 100}}, "tested": {"D2": 5}, "reprobe": {}, "weak": {}, "pending": {}}
    did._expire_flags(ctx_at(store, 100 + settings.DID_FLAG_COOLDOWN_MINUTES - 1), "w", None, st)
    assert "D2" in st["flagged"]
    did._expire_flags(ctx_at(store, 100 + settings.DID_FLAG_COOLDOWN_MINUTES), "w", None, st)
    assert "D2" not in st["flagged"] and "D2" not in st["tested"] and "D2" in st["reprobe"]
    open_ = {"flagged": {"D3": {"minute": 0}}, "tested": {}, "reprobe": {}, "weak": {}, "pending": {}}
    incidents.open_incident(store, "w", "did_flagged", 0, {"did": "D3"})
    did._expire_flags(ctx_at(store, 10 * settings.DID_FLAG_COOLDOWN_MINUTES), "w", None, open_)
    assert "D3" in open_["flagged"]  # still being evacuated: not expired


def test_reprobe_status_until_it_has_its_own_fresh_dials():
    st = {"flagged": {}, "weak": {}, "tested": {}, "reprobe": {"D2": {"minute": 0}}}
    ev = de.Evaluation(500, FatigueCurve.flat(), {})
    ev.total_dials, ev.first_hour = {"D2": 20}, {"D2": 490}
    assert did.status_of(ev, "D2", st) == dp.REPROBE


def test_expiry_invalidates_the_tick_memo_so_the_reprobe_window_is_applied(store):
    key = (str(store.path), "w")
    did.MEMO[key] = (0, "stale evaluation", {})
    st = {"flagged": {"D2": {"minute": 0}}, "tested": {}, "reprobe": {}, "weak": {}, "pending": {}}
    did._expire_flags(ctx_at(store, settings.DID_FLAG_COOLDOWN_MINUTES), "w", None, st)
    assert key not in did.MEMO  # otherwise the producer would judge D2 on its pre-flag history and spread onto it
