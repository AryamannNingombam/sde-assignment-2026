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


def test_rotation_never_sends_traffic_to_a_flagged_number():
    out = rotate_off({"D1": 0.95, "D2": 0.05}, "D1", ["D1", "D2", "D3"], flagged={"D2"})
    assert out == {"D1": 0.05, "D2": 0.05, "D3": 0.9}
    out = rotate_off({"D1": 0.5, "D2": 0.5}, "D2", ["D1", "D2", "D3"], flagged=set())
    assert out == {"D1": 0.95, "D2": 0.05}
    assert rotate_off({"D1": 1.0}, "D1", ["D1"], flagged=set()) is None


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
