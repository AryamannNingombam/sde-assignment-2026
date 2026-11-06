"""All tunables and feature flags in one place.

Nothing here is derived from simulator ground truth. Values that are priors
(rather than mechanical limits) are documented as such.
"""
from __future__ import annotations

# --- Feature flags: every lever stays OFF until its phase is green -----------
ENABLE_DID = True  # Phase 3 green
ENABLE_HALLUC = True  # Phase 3 green
ENABLE_SCHEDULE = False
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
DID_H_FLOOR = 0.35  # PRIOR (A9): worst plausible relative DID health, used only by the probe cap
DID_PROBE_BASE_STEP = 0.015  # tolerated worst-case DID-health step: harmful line is -2%, keep margin
DID_FATIGUE_TAU_GRID_DAYS = (0.25, 0.5, 1.0, 2.0, 3.0, 5.0, 8.0)  # decay windows tried by fit
DID_CURVE_MIN_OBS = 8  # (DID, day) observations needed before a curve is trusted; else flat
DID_FLAG_WINDOWS_HOURS = (1, 2, 3)  # rolling windows for the step test (3 h as in CONTEXT C5)
DID_FLAG_MIN_DIALS = 150  # each side of the step test
# CONTEXT C5 says p < 0.001 per test; the test is repeated every tick on 3 overlapping windows (~100
# looks/DID-day), so the per-look level is tightened (Bonferroni-style) to keep false flags rare.
DID_FLAG_P = 1e-5
DID_FLAG_MIN_DROP = 0.30  # relative pickup-ratio drop that counts as a step (effect-size gate)
DID_FLAG_REF_HOURS = 24  # "prior day"
DID_FLAG_SHARE_BAND = (0.5, 2.0)  # share must be roughly unchanged between window and reference
DID_EVAC_FAST_RATIO = 0.6  # estimated ratio below this: evacuate at once despite in-flight approvals
DID_PASS_MIN_DIALS = 100  # dials a probed DID needs before it can be judged
DID_PASS_MIN_AGE_HOURS = 24  # "after >= 1 day passing"
DID_PASS_RATIO = 0.8  # relative-health point estimate (vs comparable-load peers) to count as passing
DID_WEAK_MIN_DIALS = 150
DID_WEAK_MARGIN = 0.20  # weak base: significantly below (1 - margin) x expected at comparable load
DID_WEAK_WINDOW_HOURS = 48
DID_WEAK_LOAD_SLACK = 1.25  # "comparable load": own load <= peers' load x slack
DID_STEP_SAFETY = 0.95  # use at most this fraction of max_shift per auto-apply step
DID_MIN_TV = 0.005  # smaller allocation moves are not worth an auto-apply
DID_MIN_TV_APPROVAL = 0.03  # ... nor an approval request (one of the scarce daily slots)
DID_EVAL_MIN_DIALS_ACTIVE = 1  # evaluate only when the window has dials

# --- C8 hallucination incidents ---------------------------------------------------------
HALLUC_VALIDATION_N = 300
HALLUC_P = 0.001
HALLUC_MIN_CONNECTS = 200
HALLUC_ADHERENCE_DROP = 0.02
HALLUC_WINDOW_MINUTES = 1440  # rolling window for drift
HALLUC_VERIFY_MIN_CONNECTS = 200
HALLUC_VERIFY_P = 0.01
HALLUC_BASELINE_MIN_CONNECTS = 200  # a prompt needs this much history to count as a baseline
ENGAGEMENT_VERIFY_MAX_DROP = 0.02  # absolute; overridden by the workflow's own guardrail if it names engagement
CREDIT_RESERVE_PER_WORKFLOW = 25.0  # kept for incidents; routine spend never dips below W x this
INCIDENT_CREDIT_CAP = 25.0  # one incident spends at most its workflow's reserve
SUGGEST_FIXES_COST = 3.0

# --- C3 baselines --------------------------------------------------------------------------
BASELINE_MIN_DAYS = 3  # history days needed to call a baseline complete
BASELINE_REFRESH_MINUTES = 1440  # incomplete (cold-start) baselines are recomputed daily
