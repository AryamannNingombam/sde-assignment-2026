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
