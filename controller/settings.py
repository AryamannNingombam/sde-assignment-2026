"""Every tunable in one place. Section references (§N) point into SUBMISSION.md."""

# --- loop (§4)
STEP_MINUTES = 60                   # one advance per loop; keeps apply-window risk <= 1h
DB_PATH = "state/controller.db"
HTTP_TIMEOUT_S = 120
GET_RETRIES = (1, 2, 4)             # backoff seconds for read-only GETs on 5xx / connection errors

# --- experiments (§5)
ALPHA = 0.05                        # one-sided family-wise alpha for promotions
POWER = 0.8
HARM_ALPHA = 0.05                   # uncorrected on purpose: a false harm-stop only costs time
STAGE1_SHARES = (0.10, 0.10)        # 80/10/10: two challengers per dimension
STAGE1_DAYS = 2
STAGE2_SHARE = 0.50                 # 50/50 confirmation
STAGE2_MDE = {"engagement_rate": 0.05, "pickup_rate": 0.04}
STAGE2_LOOKS = 2                    # looks at n/2 and n, Bonferroni across looks
MAX_UNTESTED_TOTAL = 0.20
MAX_UNTESTED_PER_ARM = 0.10
HOLDBACK = 0.10                     # control share kept after promotion, to measure decay
DECAY_CHECK_HOUR = 13
DECAY_WINDOW_MIN = 1440             # non-overlapping 24h windows
PRODUCTION_DECAY_DAYS = 30          # D_max when the scenario end is unknown
DECAY_METRICS = 2                   # primary and guardrail share the decay alpha: alpha / (D_max * 2)
DECAY_CONFIRM_WINDOWS = 2           # consecutive non-overlapping daily windows before a FULL revert
RECENT_WINDOW_MIN = 1440            # a promotion also needs the latest 24h not to show the challenger behind
PROMOTE_MAX_ASKS = 2                # a promotion that keeps lapsing or expiring is asked for at most twice
BAND_SAFETY_ALPHA = 0.05 / 4        # per-age-band harm check at promotion
SPLIT_FEATURE = "age_band"          # the one pre-declared cohort split dimension
MAX_COHORTS_PER_WF = 3
GUARDRAIL_CI_Z = 1.96               # lower 95% bound for non-inferiority
EXPERIMENT_DIMS = {                 # which levers can move each primary KPI
    "engagement_rate": ("welcome_message", "voice"),
    "pickup_rate": ("caller_id",),
}
# A "fast" 25/25 exposure profile is deliberately not implemented: it needs a recorded client approval.

# --- caller-ID health (§5, C5)
CID_WINDOW_MIN = 180
CID_MIN_DIALS = 300
CID_SELF_Z = -3.0
CID_PEER_RATIO = 0.8
CID_PEER_RATIO_NO_HISTORY = 0.7
CID_SOLO_Z = -4.0
CID_PERSIST = 2                     # consecutive windows that must agree
CID_EXPLORE_SHARE = 0.05            # weight left on a flagged number so recovery stays visible
CID_MIN_HISTORY_DIALS = 500         # below this a number counts as having no history of its own

# --- hallucination (§7, C8)
HALLU_WINDOW_MIN = 180
HALLU_P = 0.001
HALLU_PERSIST = 2
HALLU_MIN_CONNECTED = 200
HALLU_BASELINE_FLOOR = 0.005        # guards against a near-zero history rate
HALLU_SKIP_WORDS = ("strict", "near-verbatim")   # catalogue entries known to kill engagement (memo 04)
HALLU_PREFER_WORDS = ("grounded",)
VALIDATION_N = 500
VALIDATION_Z = 1.64                 # pass if pass_rate - z*SE >= min_rate - VALIDATION_SLACK
VALIDATION_SLACK = 0.01
VERIFY_AFTER_MIN = 360              # look at a fix this long after it lands
INCIDENT_MAX_ASKS = 2               # a validated fix may be asked for again once, after the other candidates
NO_FIX_COOLDOWN_MIN = 24 * 60       # after paging a human, don't reopen the same prompt's incident for a day

# --- credits (§7)
CREDIT_RESERVE_FRAC = 0.60          # optional spend never takes credits below this share of the start budget
CREDIT_CAP_PER_INCIDENT = 25
SUGGEST_COST = 3

# --- KPI drift (§5)
DRIFT_CHECK_HOUR = 21
DRIFT_Z = -3.0

# --- governance (§6)
RESERVED_SLOTS_PER_WF = 1           # held back for rollbacks and incidents
TENANT_EARLIEST_HOUR = {"kestrel_finance": 11}    # stated preference (memo 04), stricter than policy
TENANT_MAX_REQUESTS_PER_24H = {"kestrel_finance": 2}   # "two requests a day, maximum" (memo 04); policy allows 4
LATENCY_QUANTILE = 0.75
IMPACT_NORMALISER = 0.10
EXPLORE_IMPACT_FACTOR = 0.1
DERISK_EXPIRY_MIN = 48 * 60
DRY_RUN_DAYS = 3

# --- observability (§10)
PAGE_INGEST_STALL_TICKS = 2
PAGE_REPEATED_5XX = 5
