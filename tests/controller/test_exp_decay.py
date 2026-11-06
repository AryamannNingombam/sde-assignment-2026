"""C7: CUSUM on the winner's composition-adjusted engagement + holdout confirmation; analysis groups."""
import math

from controller import exp_decay as xd, exp_state as xs, settings


def blocks(ratios, n=150, p=0.5):
    out = []
    for r in ratios:
        e = n * p
        out.append((float(n), r * e, e, n * p * (1 - p)))
    return out


def test_stable_level_never_alarms():
    c = xd.cusum(blocks([1.0, 1.02, 0.98, 1.01, 0.99, 1.0, 1.03, 0.97, 1.0, 1.01] * 3))
    assert not c["alarm"] and c["blocks"] == 30


def test_decay_after_the_reference_blocks_alarms():
    stable = [1.0] * settings.EXP_CUSUM_REF_BLOCKS
    c = xd.cusum(blocks(stable + [0.97, 0.92, 0.88, 0.85, 0.85, 0.85]))
    assert c["alarm"] and c["first_alarm_block"] is not None and c["last_ratio"] < c["ref_ratio"]


def test_too_few_blocks_cannot_alarm():
    assert not xd.cusum(blocks([1.0, 0.5, 0.5]))["alarm"]


def test_rollback_needs_cusum_plus_holdout_direction_or_significance():
    alarm = {"alarm": True, "S": 5.0, "ref_ratio": 1.0, "last_ratio": 0.9}
    quiet = {"alarm": False, "S": 0.0, "ref_ratio": 1.0, "last_ratio": 1.0}
    assert xd.decide(alarm, {"recent_lift": -0.05, "holdout_connects": 100})[0]
    assert not xd.decide(alarm, {"recent_lift": 0.04, "holdout_connects": 100})[0]  # holdout disagrees: no rollback
    assert not xd.decide(quiet, {"recent_lift": -0.05, "holdout_connects": 100})[0]
    assert xd.decide(quiet, {"since_z": -2.4, "since_lift": -0.1, "holdout_connects": 100})[0]
    assert not xd.decide(quiet, {"since_z": -2.4, "since_lift": -0.1, "holdout_connects": 10})[0]


def test_desired_matching_and_patch_shape():
    cfg = {"allocations": {"default": {"voice": {"V1": 0.9, "V2": 0.1}}, "c1": {"voice": {"V2": 1.0}}}}
    assert xs.desired_matches(cfg, "voice", {"weights": {"V1": 0.9, "V2": 0.1}, "cohort_weights": {"c1": {"V2": 1.0}}})
    assert not xs.desired_matches(cfg, "voice", {"weights": {"V1": 0.8, "V2": 0.2}})
    p = xs.desired_patch("voice", {"weights": {"V1": 1.0}, "cohort_weights": {"c1": {"V2": 0.9, "V1": 0.1}}})
    assert p["allocations"]["c1"]["voice"] == {"V2": 0.9, "V1": 0.1} and p["allocations"]["default"]["voice"] == {"V1": 1.0}
    assert xs.top_option({"V1": 0.5, "V2": 0.5}) == "V1" and xs.top_option({"V1": 0.2, "V3": 0.8}) == "V3"


def test_pre_promotion_reference_catches_a_decay_that_was_already_under_way():
    # level before promotion 1.10; the winner goes live already at ~1.0: relative to its first post blocks nothing changes
    flat_after = blocks([1.0] * 10)
    assert not xd.cusum(flat_after)["alarm"]
    ref = (600.0, 1.10 * 300, 300.0, 600 * 0.25)  # (n, engaged, expected, variance) over the last 48 h before promotion
    c = xd.cusum(flat_after, ref)
    assert c["alarm"] and c["reference"].startswith("pre-promotion")


def test_registry_veto_returns_the_first_reason_and_clear_removes_hooks():
    from controller.desired import Registry
    reg = Registry()
    reg.register_veto(lambda ctx, wid, kind: None)
    assert reg.veto(None, "w", "experiment_promote") is None
    reg.register_veto(lambda ctx, wid, kind: f"stale {kind}")
    assert reg.veto(None, "w", "experiment_promote") == "stale experiment_promote"
    reg.clear()
    assert reg.veto(None, "w", "experiment_promote") is None
