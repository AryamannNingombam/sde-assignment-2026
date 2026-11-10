"""Pure functions: stats (must reproduce SUBMISSION §3/§5), KPIs, cohorts."""
import pytest

from controller import kpi, stats
from controller.cohorts import Cohort, assign, from_config, segment_of, segments_in


# ---------------------------------------------------------------- stats
@pytest.mark.parametrize("p, delta, expected", [
    (0.547, 0.05, 1556),      # nw_renewal engagement, stage-2 sample size
    (0.493, 0.05, 1570),      # ks_cancel
    (0.265, 0.04, 1911),      # nw_kyc pickup
    (0.265, 0.03, 3398),
])
def test_stage2_sample_sizes_match_plan(p, delta, expected):
    assert stats.n_per_arm(p, delta, alpha=0.025, power=0.8) == pytest.approx(expected, rel=0.01)


def test_stage1_mde_matches_plan():
    daily = 939                                                 # nw_renewal connected/day
    n1, n0 = daily * 0.10, daily * 0.80                         # one day at 80/10/10
    assert stats.mde(0.547, n1, n0, 0.05, 0.8) == pytest.approx(0.135, abs=0.002)


def test_two_prop_directions_and_degenerate_inputs():
    assert stats.p_greater(600, 1000, 500, 1000) < 0.001
    assert stats.p_less(600, 1000, 500, 1000) > 0.999
    assert stats.p_greater(0, 0, 5, 10) == 1.0                 # empty arm is untestable, never "significant"
    assert stats.z_two_prop(0, 10, 0, 10) is None              # pooled rate 0


def test_holm_is_step_down_and_deterministic_on_ties():
    assert stats.holm({"V2": 0.01, "V3": 0.04}, 0.05) == {"V2": True, "V3": True}
    assert stats.holm({"V2": 0.03, "V3": 0.04}, 0.05) == {"V2": False, "V3": False}
    tie = {"V3": 0.02, "V2": 0.02}
    assert stats.holm(tie, 0.03) == stats.holm(dict(reversed(list(tie.items()))), 0.03)


def test_noninferiority_uses_absolute_margin():
    assert stats.noninferior(2700, 10000, 2700, 10000, 0.02)            # identical, big n: passes
    assert not stats.noninferior(240, 1000, 270, 1000, 0.02)           # 3pp worse: fails
    assert not stats.noninferior(0, 0, 10, 100, 0.02)                  # no data never passes


def test_poisson_upper_tail():
    assert stats.poisson_upper_p(0, 3.0) == 1.0
    assert stats.poisson_upper_p(1, 3.0) == pytest.approx(1 - 0.049787, abs=1e-5)
    assert stats.poisson_upper_p(16, 4.8) < 0.001
    assert stats.poisson_upper_p(5, 4.8) > 0.3


# ---------------------------------------------------------------- KPIs
def test_kpis_use_their_own_counters():
    assert kpi.pickup(dials=200, connected=50).value == 0.25
    assert kpi.engagement(connected=50, concluded=25).value == 0.5
    assert kpi.outcome(uploaded=100, concluded=40).value == 0.4


@pytest.mark.parametrize("fn", [kpi.pickup, kpi.engagement, kpi.outcome])
def test_zero_denominator_is_none_not_zero(fn):
    r = fn(0, 0)
    assert r.value is None and r.ci_low is None


def test_wilson_interval_brackets_the_rate():
    r = kpi.pickup(1000, 270)
    assert r.ci_low < 0.27 < r.ci_high and r.ci_high - r.ci_low < 0.06


# ---------------------------------------------------------------- cohorts
F = {"lang": "ta", "city_tier": "2", "age_band": "60+", "value_band": "high"}


def test_first_match_wins_and_default_fallback():
    cs = [Cohort("senior_ta", {"age_band": ("60+",), "lang": ("ta",)}), Cohort("senior", {"age_band": ("60+",)})]
    assert assign(cs, F) == "senior_ta"
    assert assign(cs, {**F, "lang": "hi"}) == "senior"
    assert assign(cs, {**F, "age_band": "18-30"}) == "default"


def test_and_across_features_or_within_one():
    c = Cohort("x", {"age_band": ("46-60", "60+"), "city_tier": ("1",)})
    assert not c.matches(F)                                     # tier 2 fails the AND
    assert c.matches({**F, "city_tier": "1"})


def test_every_segment_lands_in_exactly_one_cohort():
    cs = from_config({"cohorts": [{"id": "a", "where": {"age_band": ["60+"]}},
                                  {"id": "b", "where": {"lang": ["ta"]}}]})
    segs = [segment_of({"lang": l, "city_tier": "1", "age_band": a, "value_band": "low"})
            for l in ("hi", "ta") for a in ("18-30", "60+")]
    parts = [set(segments_in(cs, cid, segs)) for cid in ("a", "b", "default")]
    assert sum(len(p) for p in parts) == len(segs) and set().union(*parts) == set(segs)
