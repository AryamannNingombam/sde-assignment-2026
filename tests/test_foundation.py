"""Statistics, the shared cohort object, and exactly-once ingestion."""
import json

import httpx
import pytest

from controller import cohorts as ch
from controller import stats
from controller.ingest import Ingestor
from controller.store import Store


# --- statistics -------------------------------------------------------------------------------
def test_stratified_comparison_removes_simpsons_paradox():
    # Pooled, treatment looks worse because it ran mostly in the low-engagement stratum.
    # Inside every stratum it is better.
    strata = [(90, 100, 800, 1000), (300, 1000, 20, 100)]
    pooled_t = (90 + 300) / 1100
    pooled_c = (800 + 20) / 1100
    assert pooled_t < pooled_c
    assert stats.compare_stratified(strata).diff > 0


def test_arm_that_never_ran_is_not_evidence():
    assert stats.compare_stratified([(0, 0, 50, 100)]) is None


def test_stratum_missing_control_is_skipped_entirely():
    c = stats.compare_stratified([(40, 100, 30, 100), (99, 100, 0, 0)])
    assert (c.x_t, c.n_t) == (40, 100)


def test_obf_spends_little_early_and_everything_at_the_end():
    assert stats.obf_alpha_spent(0.2, 0.05) < 0.0005
    assert stats.obf_alpha_spent(1.0, 0.05) == pytest.approx(0.05, abs=1e-9)


def test_holm_stops_at_first_failure():
    assert stats.holm_rejections({"a": 0.001, "b": 0.04, "c": 0.5}, 0.05) == {"a"}


def test_bh_is_less_strict_than_bonferroni():
    pvals = {i: 0.01 * (i + 1) for i in range(5)}
    assert len(stats.bh_rejections(pvals, 0.05)) == 5
    assert all(p > 0.05 / 5 for p in list(pvals.values())[1:])


def test_sample_size_matches_textbook():
    # (1.96 + 0.8416)^2 * 2 * 0.3 * 0.7 / 0.045^2 = 1627.9, rounded up
    assert stats.sample_size_per_arm(0.3, 0.15, 0.05, 0.8) == 1628


def test_guardrail_probability():
    assert stats.prob_drop_exceeds(-0.05, 0.01, 0.02) > 0.99
    assert stats.prob_drop_exceeds(0.01, 0.01, 0.02) < 0.01


# --- cohorts ----------------------------------------------------------------------------------
def test_same_predicate_gets_same_id_regardless_of_key_order():
    a = ch.Cohort.build({"age_band": ["60+"], "lang": ["ta"]})
    b = ch.Cohort.build({"lang": ["ta"], "age_band": ["60+"]})
    assert a == b and a.id == "c_age_band_60p__lang_ta"


def test_supervisor_cohort_keeps_its_id():
    cs = ch.from_config({"cohorts": [{"id": "senior_ta", "where": {"age_band": ["60+"], "lang": ["ta"]}}]})
    assert cs[0].id == "senior_ta"


def test_first_match_wins_like_the_dialler():
    cs = [ch.Cohort.build({"lang": ["ta"]}, "ta"), ch.Cohort.build({"age_band": ["60+"]}, "senior")]
    assert ch.assign(cs, {"lang": ["ta"][0], "age_band": "60+"}) == "ta"
    assert ch.assign(cs, {"lang": "hi", "age_band": "60+"}) == "senior"
    assert ch.assign(cs, {"lang": "hi", "age_band": "18-30"}) == ch.DEFAULT


def test_where_is_or_within_feature_and_across_features():
    c = ch.Cohort.build({"lang": ["ta", "kn"], "age_band": ["60+"]})
    assert c.matches({"lang": "kn", "age_band": "60+"})
    assert not c.matches({"lang": "kn", "age_band": "18-30"})


def test_candidate_slices_cover_one_and_two_features_only():
    slices = ch.candidate_slices({0: {"lang": "ta", "city_tier": "1", "age_band": "60+", "value_band": "low"}})
    assert {s.specificity for s in slices} == {1, 2}
    assert len(slices) == 4 + 6


# --- ingestion --------------------------------------------------------------------------------
TS = "2027-01-04T09:03:00+05:30"


def _lead(lead_id="w:l1", campaign="w:c1"):
    return {"type": "lead", "ts": TS, "workflow_id": "w", "campaign_id": campaign, "lead_id": lead_id,
            "person_id": "w:p1", "features": {"lang": "hi", "city_tier": "1", "age_band": "18-30", "value_band": "low"}}


def _call(lead_id="w:l1", connected=True, engaged=True, halluc=False):
    ev = {"type": "call", "ts": TS, "workflow_id": "w", "campaign_id": "w:c1", "lead_id": lead_id,
          "attempt_no": 1, "config_version": 1, "cohort_id": "default",
          "variant": {"welcome_message": "W1", "voice": "V1", "caller_id": "D1", "prompt_version": "P1"},
          "connected": connected, "engaged": engaged}
    if connected:
        ev["qa"] = {"hallucination_flag": halluc, "flow_adherence": 0.9}
    return ev


class FakeFeed:
    def __init__(self, chunks, fail_chunk_after=None):
        self.data = chunks
        self.fail_chunk_after = fail_chunk_after

    def chunks(self, after):
        return [{"chunk": n, "kind": "events", "last_event_id": n} for n in sorted(self.data) if n > after]

    def chunk_lines(self, n):
        for i, ev in enumerate(self.data[n]):
            if self.fail_chunk_after and self.fail_chunk_after[0] == n and i == self.fail_chunk_after[1]:
                raise ConnectionError("killed mid-chunk")
            yield json.dumps(ev)


@pytest.fixture()
def store(tmp_path):
    s = Store(str(tmp_path / "c.db"))
    yield s
    s.close()


def _totals(store):
    r = store.one("SELECT SUM(dials) d, SUM(connected) c, SUM(engaged) e, SUM(halluc) h FROM fact_arm")
    return r["d"], r["c"], r["e"], r["h"]


def test_rollups_join_lead_features(store):
    Ingestor(store, FakeFeed({0: [_lead(), _call(halluc=True)]})).ingest_new()
    assert _totals(store) == (1, 1, 1, 1)
    assert store.one("SELECT seg FROM fact_arm")["seg"] == 0
    assert store.one("SELECT leads, concluded FROM campaign_seg")[1] == 1


def test_replay_of_a_committed_chunk_is_a_noop(store):
    feed = FakeFeed({0: [_lead(), _call()]})
    Ingestor(store, feed).ingest_new()
    Ingestor(store, feed).ingest_new()  # a restarted process sees the same world
    assert _totals(store) == (1, 1, 1, 0)


def test_partial_chunk_is_never_counted_and_is_reread(store):
    data = {0: [_lead(), _call(), _call(connected=False, engaged=False)]}
    with pytest.raises(ConnectionError):
        Ingestor(store, FakeFeed(data, fail_chunk_after=(0, 2))).ingest_new()
    assert store.one("SELECT COUNT(*) n FROM chunks")["n"] == 0
    assert store.one("SELECT COUNT(*) n FROM fact_arm")["n"] == 0
    Ingestor(store, FakeFeed(data)).ingest_new()
    assert _totals(store) == (2, 1, 1, 0)


class FlakyFeed(FakeFeed):
    """Drops the connection on the first read of every chunk, part-way through."""

    def __init__(self, chunks):
        super().__init__(chunks)
        self.failed = set()

    def chunk_lines(self, n):
        for i, ev in enumerate(self.data[n]):
            if i == 1 and n not in self.failed:
                self.failed.add(n)
                raise httpx.RemoteProtocolError("Server disconnected without sending a response.")
            yield json.dumps(ev)


def test_dropped_connection_is_retried_without_double_counting(store):
    # Found in a real run: the simulator closed an idle keep-alive connection and the process died.
    Ingestor(store, FlakyFeed({0: [_lead(), _call(), _call(connected=False, engaged=False)]})).ingest_new()
    assert _totals(store) == (2, 1, 1, 0)
    assert store.one("SELECT leads FROM campaign_seg")["leads"] == 1


def test_lead_join_survives_restart(store):
    Ingestor(store, FakeFeed({0: [_lead()]})).ingest_new()
    Ingestor(store, FakeFeed({0: [_lead()], 1: [_call()]})).ingest_new()
    assert store.one("SELECT seg FROM fact_arm")["seg"] == 0


def test_supervisor_edit_is_recorded(store):
    ev = {"type": "config_changed", "ts": TS, "workflow_id": "w", "version": 2, "actor": "supervisor",
          "changed_dims": ["prompt_version"], "proposal_id": None, "approval_id": None}
    Ingestor(store, FakeFeed({0: [ev]})).ingest_new()
    row = store.one("SELECT actor, changed_dims, applied_minute FROM config_versions")
    assert row["actor"] == "supervisor" and json.loads(row["changed_dims"]) == ["prompt_version"]
    assert row["applied_minute"] == 9 * 60 + 3


def test_old_leads_are_evicted_but_rollups_remain(store):
    create = {"type": "campaign_created", "ts": TS, "workflow_id": "w", "campaign_id": "w:c1", "leads": 1,
              "config_version_at_creation": 1}
    ing = Ingestor(store, FakeFeed({0: [create, _lead(), _call()]}))
    ing.set_cadences([{"workflow_id": "w", "cadence": [2, 2]}])
    ing.ingest_new()
    assert ing.evict_old_leads(2 * 1440) == 0
    assert ing.evict_old_leads(10 * 1440) == 1
    assert not ing.lead_seg and store.one("SELECT COUNT(*) n FROM leads")["n"] == 0
    assert _totals(store)[0] == 1
