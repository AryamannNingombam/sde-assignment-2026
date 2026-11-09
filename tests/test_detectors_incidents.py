"""Detector verdicts, caller-ID rotation, and the incident fix rules."""
from controller.detectors import cid_verdict, hallu_verdict, rotate_off
from controller.incidents import _risky, validation_passes
from controller.metrics import Counts


def c(dials, connected):
    return Counts(dials=dials, connected=connected)


def test_cid_needs_both_self_and_peer_evidence():
    hist = c(5000, 1350)                                         # 27% at these hours historically
    assert cid_verdict(c(450, 50), hist, c(450, 125))["fire"]    # 11% vs own 27% and vs peers 28%
    v = cid_verdict(c(450, 105), hist, c(450, 105))              # workflow-wide dip: peers equally low
    assert v["eligible"] and not v["fire"]


def test_cid_always_slightly_worse_number_is_not_flagged():
    hist = c(5000, 1100)                                         # this number has always been ~22%
    assert not cid_verdict(c(450, 99), hist, c(450, 130))["fire"]


def test_cid_minimum_n_and_special_cases():
    assert not cid_verdict(c(200, 5), c(5000, 1350), c(450, 125))["eligible"]       # below 300 dials
    assert cid_verdict(c(450, 50), c(0, 0), c(450, 130))["rule"].startswith("no own history")
    assert cid_verdict(c(900, 120), c(9000, 2400), None)["rule"].startswith("solo")
    assert not cid_verdict(c(900, 120), c(0, 0), None)["eligible"]


def test_rotation_prefers_evidence_and_never_feeds_a_flagged_number():
    ev = {"D1", "D2"}
    out, untested = rotate_off({"D1": 0.5, "D2": 0.5}, "D2", ["D1", "D2", "D3"], set(), ev)
    assert out == {"D1": 0.95, "D2": 0.05} and not untested           # D3 has no evidence: not used
    out, untested = rotate_off({"D1": 0.95, "D2": 0.05}, "D1", ["D1", "D2", "D3", "D4"], {"D2"}, ev)
    assert untested and out == {"D1": 0.05, "D2": 0.05, "D3": 0.45, "D4": 0.45}   # caller must ask approval
    assert rotate_off({"D1": 1.0}, "D1", ["D1"], set(), {"D1"}) == (None, False)


def test_untested_numbers_in_use_are_capped_at_the_exploration_cap():
    out, untested = rotate_off({"D1": 0.5, "D2": 0.25, "D3": 0.25}, "D1", ["D1", "D2", "D3"], set(), {"D1", "D2"})
    assert out == {"D1": 0.05, "D2": 0.85, "D3": 0.1} and not untested


def test_untested_number_is_held_to_the_workflow_norm():
    """Review: D4 ran at 17.4% vs a 26.9% workflow norm and nothing fired, because its peers were weak too."""
    v = cid_verdict(c(400, 70), c(0, 0), c(400, 85), wf_matched=c(20000, 5380))
    assert v["fire"] and v["z_vs_workflow"] < -3
    assert not cid_verdict(c(400, 105), c(0, 0), c(400, 100), wf_matched=c(20000, 5380))["fire"]


def test_hallucination_poisson_rule():
    assert hallu_verdict(16, 350, 0.0137, 200)["fire"]
    assert not hallu_verdict(6, 350, 0.0137, 200)["fire"]
    assert not hallu_verdict(16, 150, 0.0137, 200)["eligible"]                    # too few connected calls


def test_validation_margin_rejects_lucky_runs():
    assert validation_passes(0.986, 500, 0.97)[0]
    assert not validation_passes(0.972, 500, 0.97)[0]                              # raw pass, no margin
    assert not validation_passes(0.965, 500, 0.97)[0]


def test_risky_prompt_filter_matches_whole_words():
    assert _risky("Strict: near-verbatim compliance script")
    assert not _risky("Grounded: benefit claims restricted to policy-schedule fields")
