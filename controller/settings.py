"""All tunables and feature flags in one place.

Nothing here is derived from simulator ground truth. Values that are priors
(rather than mechanical limits) are documented as such.
"""
from __future__ import annotations

# --- Feature flags: every lever stays OFF until its phase is green -----------
ENABLE_DID = False
ENABLE_HALLUC = False
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
