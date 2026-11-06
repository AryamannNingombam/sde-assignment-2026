"""All tunables and feature flags in one place.

Nothing here is derived from simulator ground truth. Values that are priors
(rather than mechanical limits) are documented as such.
"""
from __future__ import annotations

# --- Feature flags: every lever stays OFF until its phase is green -----------
ENABLE_DID = True  # Phase 3 green
ENABLE_HALLUC = True  # Phase 3 green
ENABLE_SCHEDULE = True  # Phase 5 green
ENABLE_EXPERIMENTS = False
ENABLE_PERSON_ANALYSIS = False

# --- Time stepping -----------------------------------------------------------
TICK_MINUTES = 15
LONG_STEP_MINUTES = 60
MINUTES_PER_DAY = 1440
EPOCH_DATE = "2027-01-04"  # "Day 0" (documented in docs/SIMULATOR.md section 1)

# --- HTTP client -------------------------------------------------------------
HTTP_TIMEOUT_S = 60.0
ADVANCE_TIMEOUT_S = 900.0
CHUNK_TIMEOUT_S = 300.0
RETRY_ATTEMPTS = 5
RETRY_BASE_DELAY_S = 0.5
RETRY_MAX_DELAY_S = 8.0
ADVANCE_SETTLE_POLL_S = 1.0  # poll interval while waiting for sim_minute to stabilise
ADVANCE_SETTLE_MAX_S = 120.0

# --- Ingest ------------------------------------------------------------------
LEAD_CACHE_MAX = 600_000
TS_CACHE_MAX = 8192
INGEST_SUBBATCH_LINES = 50_000  # parse/flush granularity inside one chunk transaction
SQLITE_BUSY_TIMEOUT_MS = 30_000
WAL_AUTOCHECKPOINT_PAGES = 20_000  # rarer checkpoints: each one fsyncs the whole DB
SQLITE_CACHE_KB = 200_000

# --- Loop --------------------------------------------------------------------
STARTUP_WAIT_S = 300.0
DEFAULT_STATE_DIR = "state"

# --- Proposals / C10 ----------------------------------------------------------
DRYRUN_WINDOW_DAYS = 3
DRYRUN_MIN_ARM_N = 30  # fewer observations than this: the arm is labelled no_evidence
SCHEDULE_LIFT_HAIRCUT = 0.5  # a hour re-weighting replay has no CI; count half of its point lift

# --- Governance / planner -------------------------------------------------------
# Soft per-workflow caps layered on the policy's max_requests_per_24h. ks_cancel's values come
# from the stakeholder memo 04 (Anita, Kestrel ops): at most 2 requests/day and none before
# 11:00. Routine requests only: incidents may use the reserved slot and the approver's opening.
# Default for any other workflow id: no soft cap.
SOFT_CAPS: dict[str, dict[str, int]] = {
    "ks_cancel": {"max_per_day": 2, "not_before_hour": 11},
}
AUTO_APPLY_MIN_GAP_MINUTES = 60  # A5: one auto-apply step per workflow per hour ...
AUTO_APPLY_INCIDENT_GAP_MINUTES = 15  # ... or per tick in incident mode
MONITOR_MINUTES = 1440  # APPLIED/AUTO_APPLIED proposals are MONITORING for a day, then CLOSED
JOB_DAILY_BUNDLE = "daily_bundle"


# --- Statistics (priors, never derived from simulator truth) -----------------------------
Z_ONE_SIDED_P001 = 3.0902  # one-sided p < 0.001

# --- C5 caller-ID health --------------------------------------------------------------
# Every threshold below is derived in docs/THRESHOLDS.md (name, value, derivation, sensitivity) from the
# guardrail magnitude, effect-size/power arithmetic or the workflow's own policy values; none is fitted to a
# public scenario's truth.
_GUARDRAIL = 0.02  # the harmful line used by the brief's guardrails: -2% on the guarded KPI
DID_PROBE_BASE_STEP = 0.015  # tolerated worst-case DID-health step: harmful line is -2%, keep 0.5pp margin
DID_H_FLOOR = 0.25  # PRIOR (A9): a spam-labelled number answers ~1/4 as often (carrier labels cut answer rates ~75%)
DID_PROBE_MAX_SHARE = 0.25  # hard cap on any probe share (also used when h_bar <= h_floor, where the formula diverges)
DID_REPROBE_HARM_BUDGET = _GUARDRAIL / 4  # a re-probe of an expired-flag DID may cost at most a quarter of the line
DID_FATIGUE_TAU_GRID_DAYS = (0.25, 0.5, 1.0, 2.0, 3.0, 5.0, 8.0)  # decay windows tried by fit
DID_CURVE_MIN_OBS = 8  # (DID, day) observations needed before a curve is trusted; else flat
DID_FLAG_WINDOWS_HOURS = (1, 2, 3, 6)  # rolling windows for the step test (3 h as in CONTEXT C5; 6 h adds power)
DID_FLAG_MIN_DIALS = 150  # each side of the step test
# CONTEXT C5 says p < 0.001 per test; the test is repeated every tick on 4 overlapping windows (~130 looks/DID-day),
# so the per-look level is tightened (Bonferroni-style: 0.001 / ~100) to keep false flags rare.
DID_FLAG_P = 1e-5
DID_FLAG_P_UNFITTED = 1e-7  # stricter level while the fatigue curve is flat/cold: load effects cannot be adjusted away
# Effect-size gate. A DID holding share s whose pickup falls by d costs the workflow s*d; at the smallest useful
# even split of 2 DIDs a 12% step costs 6% = 3x the 2% guardrail, so smaller steps are not worth an incident.
DID_FLAG_MIN_DROP = 0.12
DID_FLAG_PERSIST_EVALS = 2  # the flag condition must hold on this many consecutive evaluations before opening
DID_FLAG_PERSIST_GAP_MINUTES = 120  # ... evaluations further apart than this restart the count
DID_FLAG_REF_HOURS = 24  # "prior day"
DID_FLAG_SHARE_BAND = (0.5, 2.0)  # share must be roughly unchanged between window and reference
DID_FLAG_COOLDOWN_MINUTES = 2 * MINUTES_PER_DAY  # a flag expires after this; the DID is then re-probed at the reprobe cap
DID_EVAC_FAST_RATIO = 0.6  # estimated ratio below this: evacuate at once despite in-flight approvals
DID_SHARE_WINDOW_HOURS = 12  # trailing window for OBSERVED per-DID traffic shares (config lags next_campaign_only)
DID_SHARE_MIN_DIALS = 50  # fewer dials than this in the window: the observed share is unknown, use the config
DID_EVAC_CLOSE_SHARE = 0.005  # an evacuation incident closes when the DID's observed share is below this
DID_PASS_MIN_DIALS = 100  # dials a probed DID needs before it can be judged
DID_PASS_MIN_AGE_HOURS = 24  # "after >= 1 day passing"
DID_WEAK_MIN_DIALS = 150
# Materiality of a weak base: a DID whose pickup at comparable load is >= 15% below its peers costs, at a 3-way
# split, 5% = 2.5x the 2% guardrail, so removing it is clearly worth an approval slot; smaller gaps are not.
DID_WEAK_MARGIN = 0.15
# Passing needs the point estimate of the load-adjusted pickup ratio above 1 - 1.5 x margin (= 0.775: halfway
# between "healthy" and the materiality line, widened by the ~15% standard error at the minimum n=100) AND not
# significantly (one-sided p<0.05) below the materiality line. A DID that misses the bar is "suspect": it keeps at
# most the probe cap and is re-judged every tick as its n grows, so a healthy DID is delayed, never stranded.
DID_PASS_RATIO = 1.0 - 1.5 * DID_WEAK_MARGIN
DID_PASS_Z = 1.645
DID_WEAK_WINDOW_HOURS = 48
DID_WEAK_LOAD_SLACK = 1.25  # "comparable load": own load <= peers' load x slack
DID_STEP_SAFETY = 0.95  # use at most this fraction of max_shift per auto-apply step
DID_MIN_TV = 0.005  # smaller allocation moves are not worth an auto-apply
DID_MIN_TV_APPROVAL = 0.03  # ... nor an approval request (one of the scarce daily slots)
DID_EVAL_MIN_DIALS_ACTIVE = 1  # evaluate only when the window has dials

# --- C8 hallucination incidents ---------------------------------------------------------
HALLUC_VALIDATION_N = 300
HALLUC_VALIDATION_N_STEPS = (300, 200, 100, 50)  # scaled down when credits are tight; 50 is the floor
HALLUC_BAD_EXPIRY_MINUTES = 2880  # a prompt we blacklisted is reconsidered after 2 days (evidence ages)
HALLUC_RECHECK_FAILS = 4  # consecutive ticks on which the spike no longer holds before a false alarm closes
HALLUC_REOPEN_COOLDOWN_MINUTES = 720  # after a false alarm the same prompt is not re-flagged for 12 h
HALLUC_FLAG_MARGIN_FRACTION = 1 / 3  # non-inferiority margin = this x the workflow's (1 - min pass rate)
INCIDENT_CREDIT_DAILY_CAP = 30.0  # per workflow per sim day, all incident-mode + validation spend
# CONTEXT C8 says p < 0.001; the segment test is re-run every tick (and on a rolling day for drift), so the
# per-look levels are tightened: 1e-4 for a fresh prompt segment, 1e-5 for same-prompt drift vs history.
HALLUC_P = 1e-4
HALLUC_P_DRIFT = 1e-5
HALLUC_MIN_CONNECTS = 200
HALLUC_ADHERENCE_DROP = 0.02
HALLUC_WINDOW_MINUTES = 1440  # rolling window for drift
HALLUC_VERIFY_MIN_CONNECTS = 400  # non-inferiority needs n: se(0.6%, n=400) ~ 0.4% << margin
HALLUC_VERIFY_MAX_CONNECTS = 1500  # non-inferiority at a 1pp margin needs ~1000 connects when the base rate is ~2%; past this the fix fails
HALLUC_VERIFY_P = 0.01
HALLUC_BASELINE_MIN_CONNECTS = 200  # a prompt needs this much history to count as a baseline
ENGAGEMENT_VERIFY_MAX_DROP = 0.02  # absolute; overridden by the workflow's own guardrail if it names engagement
CREDIT_RESERVE_PER_WORKFLOW = 25.0  # kept for incidents; routine spend never dips below W x this
INCIDENT_CREDIT_CAP = 25.0  # one incident spends at most its workflow's reserve
SUGGEST_FIXES_COST = 3.0

# --- C3 baselines --------------------------------------------------------------------------
BASELINE_MIN_DAYS = 3  # history days needed to call a baseline complete
BASELINE_REFRESH_MINUTES = 1440  # incomplete (cold-start) baselines are recomputed daily

# --- A1 solo-DID own-history step test (docs/THRESHOLDS.md) -------------------------------
DID_SOLO_REF_HOURS = 48  # reference = the two days before the window (same hours-of-day appear in it)
DID_SOLO_SHRINK_N = 30  # (hour, cell) reference rates are shrunk toward the hour's pooled rate with this many dials
DID_SOLO_P_FACTOR = 0.1  # solo test level = DID_FLAG_P x this (no peers to absorb a common shock: stricter)
DID_SOLO_DAYS_BACK = 4  # cube days loaded for the test (window + reference)

# --- A2 sibling prompt safety check (docs/THRESHOLDS.md) ----------------------------------
SIBLING_MAX = 3  # catalogue siblings validated per workflow, in catalogue order (never chosen by summary text)
SIBLING_N = 200  # modest validation size: 2 credits each
SIBLING_TOPUP_N = 300  # one top-up (3 credits) for a sibling that looks clearly better but is not yet separated
SIBLING_BOUND_Z = 1.645  # one-sided 95% Wilson bounds: sibling upper bound must lie below the live prompt's lower bound

# --- Phase 5: shared cohorts (C2) and per-cohort call time (C4a) (docs/THRESHOLDS.md) ----
COHORT_MIN_DIALS_PER_HOUR = 100  # n_min per cohort = this x in-window hours: se_rel(100) = 15% per (cohort, hour) rate
COHORT_MAX = 20  # the sim's limit
COHORT_MIN_Z = 3.72  # a partition must beat the pooled hour profile at one-sided p<1e-4 (= 1e-3 / 10 candidate partitions)
COHORT_PAIR_MARGIN_Z = 2.0  # a feature pair must beat the best single feature by this much z (parsimony)
COHORT_FEATURE_SUBSETS = 2  # partitions use one feature or a pair of features
SCHEDULE_HISTORY_DAYS = 14  # days of calls used for the hour multipliers
SCHEDULE_WEIGHT_CLIP = (0.3, 3.0)  # CONTEXT C4a
SCHEDULE_MIN_LIFT = 0.005  # a REFRESH is proposed only if the estimated relative pickup lift is >= 0.5%
SCHEDULE_BUNDLE_MIN_LIFT = 0.0005  # the Day-0 bundle: the significant partition is the shared cohort object; tables must just not be a loss
SCHEDULE_ENG_SHRINK_N = 20  # connects of pseudo-evidence pulling a cohort-hour engagement toward the cohort mean
SCHEDULE_VERIFY_MIN_DIALS = 1500  # post-apply dials before the before/after pickup check is evaluated
SCHEDULE_VERIFY_DONE_DIALS = 4000  # ... and after which a passing check is final
SCHEDULE_VERIFY_P = 0.05  # one-sided p for "pickup fell by at least the guardrail"
SCHEDULE_MIN_HISTORY_DAYS_COLD = 1  # cold start: build cohorts from this many full days of live data
