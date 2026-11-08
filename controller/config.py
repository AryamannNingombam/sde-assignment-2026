"""Every tunable in one place, each with the reason it has this value.

Nothing here is fitted to a scenario. Values come from power calculations, the published API
contract, or a stakeholder memo.
"""

TICK_MINUTES = 15

# --- Experiment design -----------------------------------------------------------------------
ALPHA_FAMILY = 0.05       # family-wise error per (experiment, dimension), spent across daily looks
POWER = 0.80
MDE_RELATIVE = 0.15       # smallest relative lift worth a supervisor's attention
CONTROL_SHARE = 0.50      # control keeps half: favours limiting exposure over raw test power (memo 02)
MAX_EXPERIMENT_DAYS = 5   # after this the look spends all remaining alpha and the experiment ends
MIN_REMAINING_DAYS = 3    # do not start what cannot finish before the horizon
HARM_ALPHA = 0.005        # one-sided, per look: drop an arm that is clearly worse than control
HARM_MIN_CONNECTED = 200  # no harm call below this many connected calls per arm

# --- Cohorts -----------------------------------------------------------------------------------
# At p=0.3, 200 connected per arm gives a standard error near 4.6 points, so only large
# subgroup effects are claimed. Below this a slice is noise, and BH correction cannot rescue it.
MIN_SLICE_CONNECTED = 200
MIN_SLICE_LEAD_SHARE = 0.05   # a cohort under 5% of leads costs more governance than it returns
SLICE_FDR_Q = 0.05            # Benjamini-Hochberg across every (slice, arm) hypothesis scanned
MAX_NEW_COHORTS = 4           # per workflow; platform limit is 20, attention is the real limit

# --- Promotion and decay -----------------------------------------------------------------------
HOLDOUT_SHARE = 0.15          # control kept after promotion so decay is measured concurrently
DECAY_WINDOW_DAYS = 3
DECAY_MIN_HOLDOUT_CONNECTED = 150
DECAY_Z = 2.58                # one-sided p<0.005 per daily look, about 3.5% across a week of looks
DECAY_LIFT_FRACTION = 0.5     # alarm when lift is credibly below half of the lift at promotion

# --- Guardrail ---------------------------------------------------------------------------------
GUARDRAIL_BLOCK_PROB = 0.20   # block a winner if P(true drop exceeds the policy limit) is above this

# --- Caller-ID ---------------------------------------------------------------------------------
DID_EXPLORE_SHARE = 0.05      # per unused caller ID, so an unproven number cannot do much damage
DID_WINDOW_HOURS = 6
DID_MIN_DIALS = 150
DID_Z = 4.0                   # checked every tick on every number, so the bar is high
DID_MAX_PICKUP_RATIO = 0.70   # require a material drop as well as a significant one

# --- Hallucination -----------------------------------------------------------------------------
HALLUC_WINDOW_HOURS = 3
HALLUC_MIN_QA = 100
HALLUC_Z = 4.0
HALLUC_MIN_RATIO = 2.0
HALLUC_MIN_ABS_DELTA = 0.01
HALLUC_DEFAULT_BASELINE = 0.01   # only used when a workflow has no flagged history at all
FIX_VERIFY_MIN_QA = 200
FIX_MAX_ENGAGEMENT_DROP = 0.15   # a safe prompt nobody stays on is not a fix (memo 04)
KNOWN_GOOD_MIN_QA = 500

VALIDATION_N = 500
VALIDATION_N_LLM = 400
CREDIT_RESERVE_FRACTION = 0.25   # never spend the last quarter except on an open incident
MAX_CREDITS_PER_INCIDENT = 40

# --- Drift -------------------------------------------------------------------------------------
DRIFT_MIN_DIALS = 500
DRIFT_Z = 4.0
DRIFT_MIN_RELATIVE = 0.10

# --- Governance --------------------------------------------------------------------------------
MAX_PROPOSAL_ATTEMPTS = 3       # after this an intent is dropped and the drop is audited
RETRY_BACKOFF_MINUTES = 1440    # a rejected change is retried with fresh data the next day
INCIDENT_RESERVED_REQUESTS = 1  # routine work never uses the last request of a 24h window
AUTO_APPLY_DIMS_WE_USE = ("caller_id",)  # customer-facing dims always go to a human (memo 02, 04)

# Client asks that are tighter than the signed policy (memo 04). Both only narrow what the policy
# allows, so honouring them can never break it. Incidents may bypass earliest_hour, not the cap.
TENANT_PREFS = {
    "kestrel_finance": {"max_requests_per_24h": 2, "earliest_hour": 11},
}
