# Outcome-First Agent Loop — Submission

**Name:** Naman Rana · **Date:** 2026-11-07 · **Hours actually spent (be honest):** about 33 h, an estimate written from the git history and not a stopwatch (AI-assisted throughout; breakdown in `docs/TIMELOG.md`; the candidate confirms the figure) · **Language / storage:** Python 3.13, SQLite (WAL)

> Every number below comes from a file in `reports/`, from `controller/settings.py` or `docs/THRESHOLDS.md`, or from a command run against a state database in `state/`; the source is named next to it.

---

## 0. TL;DR
- A single-process controller (`python -m controller run`, wrapped by `run.sh`) talks to the simulator only over HTTP. It ingests events into SQLite, partitions leads into cohorts, sets per-cohort call times, runs welcome x voice experiments with promotion, decay and rollback, fixes bad caller IDs and hallucinating prompts, and changes config only through the governance API.
- Results vs a no-op baseline (`reports/public_01_dev.md`, `reports/public_02_incidents.md`): public_01 conclusion rate +10.6%, pickup +7.1%, engagement +2.7%; public_02 +21.0%, +17.4%, +1.0%. 19 and 26 changes applied, 0 harmful in both; `lapsed`, `apply_conflicts`, `auto_apply_rejected` all 0. public_02 prompt incident fixed in 135 min.
- Crash-safe and deterministic: 9 fault points fired plus 10 random hard kills on public_02, all invariants pass (`reports/crash_test.log`); two concurrent public_01 runs with random hash seeds are row-for-row identical (`reports/determinism.md`). The experiment rule's false-winner rate under the null is 1.0% over 800 simulated runs (`reports/mc_null.md`).
- Scale (`reports/public_03_load.md`): 12 workflows, 840k events per sim day, 380 to 504 s of wall per sim day (under 10 min), 5,382 events/s ingest, 1.42 GB peak RSS. First thing to break at 10x: SQLite commit and checkpoint in ingest.
- Deliberately not built: per-person call-time deployment (analysis only, flag off), tenant-fair allocation, prompt experiments outside incidents. One honest failure on a dev scenario: `bad_default` has one change graded harmful (section 11).

## 1. Assumptions
1. **A1** The controller knows only what the HTTP API returns. Sim code was read to learn the contract (validation, grading), never imported by `controller/`, and no hidden-truth numbers are constants.
2. **A2** IST throughout; "Day 3 14:00" = sim minute 3*1440+840 (Day 0 = 2027-01-04, `settings.EPOCH_DATE`).
3. **A3** `*_max_drop: 0.02` is an absolute 2-point drop in the guardrail rate versus the concurrent control (or the pre-change baseline if there is none).
4. **A4** "Who approved" = the workflow's policy approver, identified by `approval_id` and the sim's `decided_at`; the simulator exposes no personal names. `why` says exactly that.
5. **A5** `max_shift` limits the speed of change: at most one auto-apply step per workflow per hour (`AUTO_APPLY_MIN_GAP_MINUTES = 60`), per tick in incident mode (`AUTO_APPLY_INCIDENT_GAP_MINUTES = 15`); steps are never chained within a tick.
6. **A6** Supervisor edits are legitimate and never silently reverted; a revert is proposed through the approver, naming the edit and the evidence.
7. **A7** Anita's limits (<= 2 requests/day, none before 11:00) are a soft preference on top of policy (`settings.SOFT_CAPS["ks_cancel"]`); incidents may use the reserved slot.
8. **A8** Hidden scenarios may change options, policies, incidents, prompts and history length (including 0); everything is read from `GET /workflows` at runtime and each capability has a cold-start rule.
9. **A9** Priors, tunable and documented in `docs/THRESHOLDS.md`: `DID_H_FLOOR = 0.25` (worst plausible health of an untested DID, only used by the probe cap), `DID_PROBE_BASE_STEP = 0.015`, `DID_FLAG_MIN_DROP = 0.12`, `PERSON_PRIOR_STRENGTH = 20`.
10. **A10** Per-look significance levels are tighter than the spec's p < 0.001 because tests re-run every tick: `DID_FLAG_P = 1e-5`, `HALLUC_P = 1e-4`, `HALLUC_P_DRIFT = 1e-5`.
11. **A11** An allocation move below `DID_MIN_TV = 0.005` is not auto-applied, and below `DID_MIN_TV_APPROVAL = 0.03` it is not worth an approval slot.
12. **A12** An applied proposal is monitored for `MONITOR_MINUTES = 1440` and then closed; "closed" ends our monitoring window, it does not certify the change.
13. **A13** Credits: reserve `CREDIT_RESERVE_PER_WORKFLOW = 25` per workflow for incidents; one incident spends at most `INCIDENT_CREDIT_CAP = 25`; Day-0 validation of each live prompt at n = 300 (3 credits).
14. **A14** A simulator that restarts is a new world: the DB is keyed by scenario plus the fingerprint of the first history chunk (`world_id.py`).
15. **A15** A supervisor version superseded within one advance cannot be recovered (the API returns no bodies); we mirror bodies after every `config_changed` event and accept the gap.
16. **A16** Welcome and voice are tested only on engagement-primary workflows; hour weights act only per cohort (a single default table does nothing under fixed hourly capacity, `docs/CONTEXT.md` section 3).

## 2. Scope decisions
| # | Capability | Built / Partial / Cut | Why | What it would take to finish |
|---|---|---|---|---|
| C1 | Ingestion at load scale | Built | Spine. One txn per chunk, `event_id` primary key; 5,382 events/s on public_03 (`reports/public_03_load.md`) | Stream chunks (peak RSS 1.42 GB), batch commits, higher `wal_autocheckpoint` (section 8) |
| C2 | One shared cohort object | Built | Data-driven partition on one feature or a pair, self-checked against the sim's `cohort_id` on every call | Cohorts beyond the single-pass partition (re-partition during a run is not built) |
| C3 | History bootstrap | Built | Baselines, fatigue curve, flag baselines; cold start recomputes daily | Cold start exercised in unit tests only |
| C4a | Per-cohort call time | Built | Uses history only; schedule-only changes grade neutral | A concurrent control for the before/after check |
| C4b | Per-person call time | Cut (analysis only, flag off) | 1-2 connects per person, selection effect, biased holdout (`reports/person_analysis.md`) | A per-person mechanism that does not compete for hourly capacity |
| C5 | Caller-ID health | Built | Biggest pickup lever; the public_02 and kyc_flag incidents | Production weekly re-probe of flagged DIDs |
| C6 | Welcome x voice experiments | Built | Main engagement lever; OBF + Holm + clustered SE | Per-cohort deployment of group winners is wired but rarely reached |
| C7 | Promotion, decay, rollback | Built | Two-stage promotion, sequential decay test, CUSUM, holdout | Decay faster than about 3 days is not separable from noise (section 5) |
| C8 | Hallucination incidents | Built | MTTR is graded: 135 min on public_02, 285 min on kyc_flag | `suggest-fixes` path is implemented but unexercised (0 LLM calls everywhere) |
| C9 | Governance client + planner | Built | Every change goes through it | Cross-workflow coordination |
| C10 | Impact, affected leads, dry run | Built (simple, honest) | `dryrun.py` replays 2-3 days of the cube; unobserved arms labelled `no_evidence` | Honest CI for schedule changes |
| C11 | Supervisor view | Built | `controller view` and read-only `controller ui`, never started by `run.sh` | Authentication, alert routing |
| C12 | Audit store | Built | `why --at / --from --to / --lead` (section 10) | Per-person view |
| C13 | Crash recovery, demonstrated | Built | 9 fault points + 10 random kills (section 9) | Linux box, public_03 kill run |
| C14 | Loop observability | Partial | `metrics`, `tick_phases`, `status`, alert rules; no pager | Pager integration |
| C15 | Fair allocation across tenants | Cut | Budgets are per workflow already; matters at hundreds of tenants | Global coordinator for credits and approver attention |

**Principle:** spine first (ingest, governance, audit, crash safety), then the levers with the most defensible lift per approval spent (caller-ID health, hallucination fixes, cohort call times, experiments), then reach. Everything optional sits behind a flag in `settings.py`; the one that did not earn its keep (`ENABLE_PERSON_ANALYSIS`) is off.

## 3. Stakeholders
Checked against the workflow policies in `docs/CONTEXT.md` section 3. Each reply is at most 120 words (counted).

### 01 Sales (Nikhil)
- **Accepted:** batching (planner P1: one in-flight approval per workflow, one `daily_bundle` per sim day); lift reported per KPI, never blended (R4).
- **Pushed back:** a blended score; "winning by lunch, live by evening" (minimum sample, sequential boundaries, approver latency 30-480 min, nw_kyc cannot change mid-campaign); rolling P4 out everywhere.
- **Wrong against policy:** ks_cancel auto-apply covers only schedule, caller_id, welcome and voice at max_shift 0.2 (no prompt, no cohorts); nw_kyc has `auto_apply.enabled: false`; P4 is not an option on nw_kyc.
- **Reply:** Nikhil, thanks. Pickup and engagement are reported separately per workflow; there is no blended score. Routine requests are batched: one in flight per workflow, one daily bundle. "Winning by lunch, live by evening" cannot be promised: a winner needs a minimum sample and sequential test boundaries, and approvals take 30 to 480 minutes in working hours. Two claims do not match the policies: Kestrel's auto-apply covers only schedule, caller ID, welcome and voice (no prompts, no cohorts), and Northwind's nw_kyc has auto-apply switched off. P4 is not an option on nw_kyc, and another account's result is not evidence here, so we will not roll it out.

### 02 Compliance (Meera, Northwind)
- **Accepted:** named approval for customer-facing changes (every welcome/voice/prompt/cohort change goes through the approver with evidence); per-customer "why did they hear X" (`why --lead`); no night-time requests (`fatigue.filing_window_ok`); weekly summary of operational auto-applies (`view --weekly`).
- **Pushed back:** nothing.
- **Wrong against policy:** timing and caller-ID rotation are covered by auto-apply on nw_renewal, not on nw_kyc. The sim exposes no approver names (A4).
- **Reply:** Meera, thank you. Every customer-facing change (welcome, voice, prompt, cohorts) goes through your approver with its evidence, and requests are never filed at night. `controller why --lead <id>` shows, per customer, each call with the welcome, voice, caller ID and prompt used, and the decision and approval behind them. A weekly list of operational auto-applies is available. One correction: timing and caller-ID rotation are covered by auto-apply on nw_renewal, but not on nw_kyc, where auto-apply is disabled and every caller-ID change is requested from your approver. We record the approval id and decision time; the system cannot see the approver's name.

### 03 Platform/SRE (Kabir)
- **Accepted:** kill/restart test (`scripts/crash_test.py`); idempotency (write-ahead proposal ids); health without logs (`status`); under 10 min per sim day; a 10x analysis.
- **Pushed back:** Postgres for the assignment; SQLite is one embedded file and the schema ports (partition `calls` and `cube` by day, shard by workflow).
- **Wrong against policy:** nothing found.
- **Reply:** Kabir, the kill/restart test exists (`scripts/crash_test.py`): 9 fault points plus 10 random hard kills on public_02, then invariant checks, all passing (`reports/crash_test.log`). Proposal ids are written before anything is sent, so retries are idempotent. Health is one command (`controller status`). On public_03 (12 workflows, 840k events a day) a sim day takes 380 to 504 seconds including the simulator, under your 10 minutes. At 10x, ingest commit and checkpoint breaks first; the plan is sharding by workflow and batching commits (`reports/public_03_load.md`). We kept SQLite: one embedded file, no daemon, and the schema ports to Postgres partitioned by day.

### 04 Ops supervisor (Anita, Kestrel)
- **Accepted:** never silently undo her edits (A6); soft cap of 2 requests/day and none before 11:00; no strict-script fix (engagement is verified after apply); one screen (`view`).
- **Pushed back:** one reserved incident slot beyond her 2/day; operational DID and schedule changes happen without advance notice and appear under "changed today".
- **Wrong / mismatched:** she wants notice before changes, Sales claims Kestrel wants everything automatic; customer-facing changes reach her approver, so she is told.
- **Reply:** Anita, your edits are never overwritten silently. When your Day 3 prompt edit raised hallucinations, we did not revert it behind your back: we filed one approval request naming your edit and the numbers, applied it once approved, and verified engagement afterwards; the fix landed 135 minutes after your edit. Routine requests are capped at two a day and none before 11:00. One extra slot is kept for incidents. Operational caller-ID and schedule changes happen without a request and are listed under "changed today" on the one-screen view (`controller view`). Customer-facing changes always reach your approver first, so you hear about them before they run.

### 05 Product (Tara)
- **Accepted:** separate KPIs; one shared cohort object (documented minimum n and window); every proposal carries summary, rationale, impact, affected leads and dry run; expired = rejection, re-planned with fresh data; only observed arms count; per-workflow promotion.
- **Pushed back:** the three P0s cannot all ship at full depth. Per-cohort call time ships; per-person call time is analysis only, with numbers (section 12).
- **Wrong against policy:** nothing factual. Prompt changes have no historical dry run and are labelled validation-only.
- **Reply:** Tara, KPIs stay separate everywhere, and one shared cohort object feeds call times and experiments. Each request carries a summary, rationale, impact score, affected leads and a dry run built from observed data; arms never observed are labelled "no evidence". Expired requests are treated as rejections and re-planned with fresh data. The three P0s cannot all ship at full depth. Per-cohort call time ships. Per-person call time is analysis only: persons have 1 to 2 connects, the best-of-4 rule qualifies nearly as many people when no effect exists, and a person-level holdout competes with treated people for capacity. Prompt changes show "validation-only" because there is no historical dry run.

### 06 CTO (Aryamann)
- **Accepted:** explainable over impressive (deterministic rules, every decision a `decisions` row); credits only where they change a decision; the scale envelope (section 8); a written "no" for each cut (sections 2, 12); on-call docs (`docs/RUNBOOK.md`).
- **Pushed back:** nothing.
- **Wrong against policy:** he warns the memos contain errors; confirmed, listed above.
- **Reply:** Aryamann, you were right that the memos disagree with the policies; the corrections are in the Sales, Compliance and Ops replies. Every change is a deterministic rule and a row in our own store that `controller why` can replay. Credits go only to prompt validation and sibling safety checks, never to speculative calls. The cuts are written down with reasons: tenant-fair allocation, prompt experiments outside incidents, per-person call-time deployment. The scale envelope is measured on public_03 with a 10x analysis, and the on-call runbook is in `docs/RUNBOOK.md`. Weaknesses are listed plainly in section 13.

## 4. Architecture

```mermaid
flowchart LR
  subgraph SIM[Simulator - HTTP only]
    A[/sim/advance, /sim/state/]
    E[/events/chunks/]
    C[/workflows, config, history/]
    G[/approvals, apply, PUT config/]
    L[/validation, llm/]
  end
  subgraph CTL[controller run - one process, one SQLite writer]
    LOOP[loop.py: per-tick order]
    ING[ingest.py: txn per chunk]
    DET[detectors: did, halluc, fatigue_curve, cohorts, schedule, experiments, decay]
    PLAN[planner.py: P1-P7]
    PA[person_analysis.py: analysis only, flag off]
    GOV[governance.py + proposal_repo.py: state machine]
    INC[incidents.py + credits.py]
  end
  DB[(state/scenario-fingerprint.db WAL)]
  LOOP --> A
  E --> ING --> DB
  C --> ING
  DET --> DB
  PA -.->|report rows only| DB
  DET --> PLAN --> GOV
  GOV -->|intent row first| DB
  GOV --> G
  INC --> L
  AUD[controller why / status: read-only] --> DB
```

Per tick (`loop.py`): reconcile in-flight approvals -> ingest new chunks and mirror configs -> apply approved changes (only if `apply_by` has not passed and the base version is current; otherwise mark LAPSED/STALE locally and never call `/apply`) -> detectors -> planner and submit -> per-person analysis (flag off, never raises) -> metrics row -> advance (15 min; 60 min when idle outside every dialling and approver window).

**State (SQLite WAL, `controller/schema.sql`):** `ingest_cursor`, `leads`, `calls` (event_id primary key), `cube` aggregates, `config_versions` (actor, proposal link, mirrored body), `proposals` + `proposal_events` (full state history), `decisions` (every detect/propose/apply with an inputs snapshot), `incidents`, `validation_runs` + `llm_calls` (credit ledger), `jobs`, `detector_state`, `alerts`, `metrics`, `meta` (world fingerprint).

**Restart behaviour:** open the DB for this world (a changed fingerprint or regressed sim opens a new one), re-read `/sim/state`, reconcile governance (INTENT proposals are looked up in `GET /approvals` by proposal id and resent verbatim if absent; APPROVED ones are applied if still valid; auto INTENTs are matched in `config/history`), re-ingest after the cursor (re-reading a chunk changes nothing) and continue. `run.sh` restarts a crashed controller (cap 20) and exits 0 only when the controller exits 0, which happens only once the sim reports finished.

## 5. The learning loop
All parameters are in `controller/settings.py` with their derivation in `docs/THRESHOLDS.md`; the decision rule lives in `controller/exp_rules.py` and the Monte Carlo (`scripts/mc_null.py`) runs that same code.

**Cohorts.** At Day 0 `cohorts.py` scores every single feature and every pair of the four lead features by how much a separate **hour-of-day pickup profile** per group beats one pooled profile (a separable group + hour model is the null, so level differences count for nothing: only profiles that per-cohort hour tables can exploit). A partition must beat the pooled profile at one-sided p < 1e-4 (`COHORT_MIN_Z = 3.72`, which is 1e-3 over 10 candidates) and a pair must beat the best single feature by 2 z, so noise does not fragment traffic. Groups are disjoint (a partition, so first-match order cannot matter); a group below n_min = 100 dials per in-window hour (`COHORT_MIN_DIALS_PER_HOUR`, se_rel 15% per cohort-hour) falls into `default`; at most 20. On public_02 ks_cancel the result is 4 cohorts by `age_band`. Defining cohorts needs approval (never in a public `allowed_dims`), so it is part of the Day-0 bundle. Every call's `cohort_id` is checked against our own evaluation of that event's config version (`cohort_mismatch` pages).

**Per-cohort schedule (C4a).** Per cohort and hour, an observed/expected pickup multiplier from the last 14 days, controlling for attempt number and campaign day, shrunk by empirical Bayes (tables collapse to the pooled profile when cohorts do not differ). Weights are mean 1, clipped to 0.3-3, every in-window hour present. A dry run re-weights recent dials under fixed hourly capacity and blocks the change if the estimated engagement drop exceeds the workflow guardrail; a refresh needs an estimated gain of at least 0.5%. After apply, hour-mix-adjusted pickup is compared before and after and the schedule is rolled back at a guardrail-sized fall with p < 0.05 (the check has no concurrent control and says so; public_02 nw_renewal v4 is such a rollback, `why` section 10).

**Experiments (welcome x voice, engagement-primary workflows).** Each dial is randomised independently, so the design is factorial and we analyse main effects per dim; interactions are reported from the 2-way table, not acted on. Entry: challengers start at **7.5%** each (at most 22.5% per dim). **Ramp:** after at least 1 day and 100 connects an arm with a non-negative point estimate goes to 20%, control never below 40%. **Drop:** whole-experiment z <= -1.5 below 300 connects, <= -1 above, and a ramped arm also at last-24 h z <= -1.5. **Harm-stop** every 4 h: z <= -3 with >= 150 connects removes the arm at once. Unit: the connected call with **per-lead clustered (sandwich) standard errors**, Mantel-Haenszel pooled over day x share-regime strata so ramps and base-rate drift do not confound. **Winner:** one-sided test at looks when information reaches 0.25/0.5/0.75/1 of the design value (10% lift, 80% power), **Lan-DeMets O'Brien-Fleming** boundaries, **Holm** across the arms of a dim, familywise 0.05 per workflow split over the two dims (workflow-level 0.02 plus two pre-registered traffic groups at 0.0025 each, per dim). Promotion also needs point lift >= 3%, the **recent-24 h one-sided 95% lower bound > 0** (never promote a variant that has begun to decay), and a **non-inferiority guardrail** on pickup (clustered difference, upper bound of the drop under the policy's `pickup_rate_max_drop`). Exploration vs exploitation: a fixed-horizon sequential design with a conservative ramp, not a bandit (section 12).

**Two-stage promotion and holdout.** Stage 1: winner 50% / old control 50% (a half-power concurrent control for a variant that never carried real traffic). Stage 2: 90% / 10% holdout only after >= 24 h at stage 1, a positive recent lower bound and a positive concurrent contrast. Both stages are customer-facing and go through approval. Before `/apply` of any approved ramp, drop or promotion stage an **apply-time veto** re-checks the evidence (recent-24 h one-sided 80% lower bound > 0 for promotions); a withheld change is never sent to `/apply`, so no lapse is logged.

**Decay and rollback.** A sequential winner-vs-control test (level 0.10 per epoch, OBF, epochs restart when information reaches that of a -15% effect at 80% power) plus a **CUSUM** of the winner's composition-adjusted engagement (blocks of 150 connects, k = 0.5, h = 3) that needs the holdout's recent direction to agree. A rollback is risk-reducing: auto-apply where the dim is allowed, else the second-to-last approval slot, superseding any routine request in flight. Measured limit (`reports/mc_null.md`): a promoted decaying winner (+15% falling to -10% over 2 days) was rolled back in every run that promoted it, at a median of 11-14 four-hour ticks after stage 1; its share is at most 0.1 two days after onset in only 2-16% of runs. A decay faster than about 3 days is not separable from noise at a 20% share.

**False-winner rate (`reports/mc_null.md`, 800 null runs):** 1.0% any-arm false promotion (target <= 5%); 0.2% on arm A, 0.8% on B. A scenario has 4 experiments (2 workflows x 2 dims), so at least one false promotion per scenario is about 4x that. Power: a +10% arm is promoted in 34% of runs, +15% in 63%, median day 4.8-5.8. Stratified and unstratified contrasts false-promote at the same rate (1.3% each) at +-5% drift.

**Caller ID (C5).** A monotone fatigue curve (pickup ratio vs trailing decayed dial volume, decay window chosen from `DID_FATIGUE_TAU_GRID_DAYS` by fit; nothing taken from the sim). Flagged DID: a step drop vs peers (or vs its own 48 h history when it has no peers) at `DID_FLAG_P = 1e-5`, >= 150 dials a side, relative drop >= 12%, holding for 2 evaluations. Probes of new DIDs at share `s <= 0.015 h/(h - 0.25)` (about 2%), so the worst-case DID-health step stays above the -2% harmful line; weak bases need two distinct days. Evacuation in steps bounded by `max_shift`.

**Hallucination.** A flag-rate test per prompt segment against the last known-good prompt (Day-0 validation, n = 300) with an absolute ceiling of `1 - min_validation_pass_rate`; a supervisor edit starts a new segment at once. Fix: revert to the workflow's own known-good prompt using its Day-0 validation as evidence (no new credits). **Sibling-prompt safety check:** at Day 0 up to 3 sibling catalogue prompts are validated (2 credits each); the live prompt is switched only if a sibling is clearly safer (one-sided 95% Wilson bounds) and the live failure bound is at least half the policy tolerance; after apply the switch is verified and rolled back on failure.

**Call time and caller ID, per-cohort vs per-person.** Call time is per cohort from history, no exploration. Per-person is analysis only (section 12). Caller ID explores by capped probes, never by random assignment.

**Guardrail KPI.** Experiments: the non-inferiority test above. Schedule: the dry-run engagement cap plus the before/after check. Reporting caveat: engaged/connected falls a little whenever pickup rises (repeat connects are by construction people who did not engage the first time); on null_01 the dip was -0.5 to -1.2 pp, z -0.7 to -1.1 per workflow, first-connect engagement unchanged (`reports/guardrail_analysis.md`). Experiment tests compare arms within the same period, so they are not exposed; day-vs-baseline KPI views are.

## 6. Governance
**State machine** (`proposal_repo.py`): `DRAFT -> INTENT -> PENDING -> APPROVED -> APPLIED -> MONITORING -> CLOSED`; auto path `INTENT -> AUTO_APPLIED -> MONITORING -> CLOSED`; branches `REJECTED` (reasons stored, planner re-plans), `EXPIRED` (treated as a rejection, new id on fresh data), `STALE` (base changed: re-plan, re-read any supervisor edit, never call `/apply`), `LAPSED` (`apply_by` passed: should be impossible, alerts), `SUPERSEDED`, `SUBMIT_FAILED`. The proposal id `workflow:plan_seq:kind` and the full body are written before anything is sent.

**Batching and timing.** One in-flight approval per workflow (P1); a `daily_bundle` once per sim day carries every wanted change (cohorts, schedules, experiment ramp/drop, promotion stages) in one request. Requests are filed only at approver-open (11:00 for ks_cancel) and only if the worst-case decision time `next_working(now + max_latency)` precedes `expires_at`. The rolling 24 h ledger has three **slot tiers**: the **last slot is reserved for safety incidents only** (hallucination fix, flagged-DID evacuation where auto-apply is off); harm-stop and rollback may use the **second-to-last**; routine bundles get **max(1, max - 2)**. A rollback therefore never blocks a safety fix, and a collision merges into one superseding proposal. ks_cancel has the soft cap of 2/day.

**Supersede.** A higher-priority need while something is in flight produces one proposal that contains the new change plus every still-wanted change from the in-flight one, using the reserved slot; whichever is approved first and still valid is applied and the other is marked `SUPERSEDED` and never applied. Example: public_02 ks_cancel v9 is a hallucination fix that also carries the pending voice ramp (section 10).

**Auto-apply, and when we voluntarily do not.** Auto-apply only for operational changes (caller ID, schedule) and risk-reducing ones (harm-stop, rollback) where the policy allows the dim and the per-cohort-per-dim TV is within `max_shift`; every customer-facing change (welcome, voice, prompts, cohorts, promotions) goes through approval even where welcome and voice could be auto-applied, because a named approver is what Compliance asked for. nw_kyc has auto-apply off, so its caller-ID changes are approvals.

**Local validation.** Every field the approver checks softly (empty summary, diff, rationale or dry run, non-integer `affected_leads`, impact outside [0, 1], missing prompt evidence, fatigue) and the auto-apply policy are checked before sending (`governance.py`), so 4xx and graded 403s should not occur: `auto_apply_rejected` is 0 in every report.

**Impact, affected leads, dry run, honesty.** `impact_score = clip(lower-bound relative lift on the primary KPI x share of traffic affected / 0.10, 0, 1)`; safety fixes use excess hallucination rate over the policy tolerance. `affected_leads` counts active in-cadence leads whose effective distribution changes. The dry run replays 2-3 days of the cube at observed per-arm rates under the new weights with a CI; unobserved arms are `no_evidence`; prompt changes are `validation-only`. It is an observational replay, not a causal estimate.

**Reconciliation and crash safety.** At startup and every tick, `GET /approvals` and `config/history` are matched by proposal id: an INTENT is resent verbatim only if absent; an APPROVED proposal is applied only if `apply_by` has not passed and the base version is current; a supervisor edit between propose and apply makes it STALE. Credit-costing calls have their own crash point and ledger reconciliation (section 9).

**Supervisor edits mid-experiment.** The affected dim is marked interrupted; earlier data stays valid for arms that ran; the edit is never re-imposed over. After `EXP_SUPERVISOR_COOLDOWN_MINUTES` the supervisor's choice is the new control and the next `change_summary` says so; arms that were behind the new control are not re-entered. On public_02 nw_renewal the supervisor set voice to V2 only (v11 at Day 5 15:00): the controller did not revert it.

## 7. Incidents
**Thresholds** (`controller/settings.py`, derivations in `docs/THRESHOLDS.md`): flagged DID `DID_FLAG_P = 1e-5` per look with 1/2/3/6 h windows, >= 150 dials a side, drop >= 12%, 2 consecutive evaluations; hallucination `HALLUC_P = 1e-4` (fresh segment) and `1e-5` (drift) with >= 200 connects. The levels are tight on purpose because tests repeat every tick.

**False positives observed** (controller `incidents` table, all five dev and public runs): public_01 0 incidents; public_02 2 (both real, the graded D2 flag and the supervisor prompt edit); kyc_flag 2 (both real); bad_default 0; null_01 **1 flagged-DID incident on nw_kyc D1 at Day 0 13:00 with no graded incident in that scenario, which is one false positive in five runs.** It was handled by evacuation steps and no applied change was graded harmful. A calibrated rate is not claimed; 5 runs is too few.

**Choosing a fix:** revert to the workflow's own known-good prompt (its Day-0 validation is the evidence, so no new credits); only if none exists, `suggest-fixes` plus validation ranked by lowest failure upper bound (implemented, 0 LLM calls in every run). **Credit spend:** public_02 26 credits (11 validation runs: Day-0 validation of live prompts and the sibling checks), public_01 24, kyc_flag 29, null_01 30, bad_default 30 of 200, 0 LLM fix calls (`reports/*`).

**Verify after apply:** the new prompt's flag rate must be non-inferior to baseline (margin a third of the policy tolerance, between 400 and 1,500 connects, waiting if unresolved) and engagement inside the guardrail, else the next candidate; a DID incident closes when the flagged DID's observed share is under 0.5%.

**Timeline, public_02 ks_cancel Day 2 to Day 4**, from `python -m controller why --state-dir state/public_02_incidents --workflow ks_cancel --from "Day 2" --to "Day 4"` (the run behind `reports/public_02_incidents.md`; experiment looks omitted):
```
  Day 2 12:00  did_flagged: FLAGGED D2: pickup ratio vs peers fell 61% (p=4.6e-07, 284 dials in 3h vs 1979 in the reference); incident mode
  Day 2 12:00  proposal_auto_applied: ks_cancel:6:did_evacuation   -> config v6 (controller_auto, caller_id)
  Day 2 12:15  proposal_stale: ks_cancel:5:experiment_update       (a routine request overtaken by our own auto-apply)
  Day 2 12:15  proposal_auto_applied: ks_cancel:7:did_evacuation   -> config v7
  Day 2 23:00  incident_closed: D2 evacuated: observed share 0.14%, config v7 share 0 in every key
  Day 3 11:30  config_observed: v8 by supervisor changed ['prompt_version']
  Day 3 11:45  incident_opened: halluc  (bad_prompt_day0: P2 flags 5.5% vs failed Day-0 validation, n=200)
  Day 3 11:45  proposal_pending: ks_cancel:9:halluc_fix            (revert P2 to P1, validation val_00001 pass 0.987)
  Day 3 13:45  proposal_approved + applied -> v9 (controller_approved; approver decided 13:26)
  Day 3 17:30  incident_verified: P1: flags 0.74%, engagement ok; incident_closed
  Day 4 12:00  did_flag_expired: D2 re-probed at the re-probe cap
```
The grader reports `mttr_minutes: 135`, `fixed_by: controller_approved`, flagged-DID share by day 0.088 (Day 2), 0.0 (Day 3), at most 0.009 afterwards (`reports/public_02_incidents.md`). The 135 minutes are the approver's latency (filed 11:45, approved 13:26, observed and applied 13:45): detection took 15 minutes. On kyc_flag (a supervisor prompt edit on nw_renewal at Day 4 12:00) the grader's MTTR is 285 min with `fixed_by: controller_approved` (`reports/dev/kyc_flag.md`); I did not break that figure down further.

## 8. Scale
From `reports/public_03_load.md` (12 workflows, 840,000 events per sim day, 5 sim days run to the end, Windows 10, 8 cores, sim and controller on one laptop):

| Metric | Measured |
|---|---|
| Wall per sim day (incl. sim compute) | 380 / 422 / 499 / 504 s for days 1-4 (6.3 to 8.4 min, under the 10 min target); Day 0 739 s with the 6.4 min history ingest |
| Ingest | 5,382 events/s (4.20M events, 780 s inside ingest) |
| Controller time per tick | p50 1.74 s, p95 13.5 s, max 69.5 s (15 sim minutes per tick) |
| End-to-end decision lag | p50 1.7 s, p95 13.5 s, max 69.5 s (against 24 h apply windows) |
| Peak RSS | 1,422 MB (reached ingesting the 54 MB morning chunk) |
| DB | 892 MB after history, then about 120 MB per day (1.38 GB, 7.43M `calls` rows) |
| Outcome | rc 0, 70 changes applied (33 beneficial, 37 neutral, 0 harmful), `lapsed` 0, `apply_conflicts` 0, `auto_apply_rejected` 0, 100 of 400 credits |

Before the profile-driven fixes (cell-filter `EXISTS` instead of `IN (SELECT ...)`, cached completed-day arm counts, cached schedule strata) days 3 and 4 took 700 and 772 s, over the target; detector time halved (1,144 s to 570 s).

**What breaks first at 10x (about 8.4M events/day):** (1) SQLite commit and checkpoint of random index pages in ingest: about 85% of ingest time is inside `COMMIT` (every call row dirties a random page of `calls_lead`); ingest alone would be about 26 min per sim day; raising `wal_autocheckpoint` gave 23.8k events/s in a replay (deferred, not removed) and `json.loads` is not the limit (124k events/s per core); (2) per-tick detector queries over a `calls` table that stops fitting the page cache (about 14 GB per 5 days); (3) memory, because whole chunks are materialised (a 10x morning chunk is about 540 MB of text; stream it); (4) the simulator itself (90 to 190 s per day, not ours). **Partitioning:** shard by workflow (all state, approvals and DID pools are per workflow; only the credit pool is shared, so give each shard a reserved share plus a shared top-up), one process and one DB per shard of 2 to 4 workflows, each pre-filtering lines on `workflow_id` before parsing, batched commits across chunks and an explicit checkpoint on idle ticks; beyond that Postgres or a column store for `calls` with the same keys. The ingest-side changes were not applied, because they deserve their own crash-test run (`reports/public_03_load.md`).

## 9. Reliability
**Method** (`scripts/crash_test.py`, subprocess only): start `python -m sim serve` for public_02, run `python -m controller run` as a subprocess, and (a) for each fault point in `controller/faults.py` run with `CRASH_AT=<point>:<n>` until the process `os._exit`s (rc 137, no cleanup handlers), then restart; (b) 10 `Popen.kill()` hard kills after seeded random wall delays; (c) run to completion and check invariants over HTTP, the sim's grader and our store. The fault points: `mid-ingest-txn`, `after-submit-before-record`, `after-apply-before-record`, `after-advance-before-ingest` and `after-credit-call-before-record` (a kill between a credit-costing call and its ledger row).

**Result** (`reports/crash_test.log`, Windows 10, Python 3.13, seed 7): 9 of 9 named fault points fired, all 10 random kills were delivered mid-run, 20 restarts, controller finished rc 0 in 361 s and the sim reached `finished` (sim minute 14,400).
```
INVARIANT PASS: every controller_* config version maps to a unique proposal_id -- 24 versions checked; bad=[]
INVARIANT PASS: no duplicate applies in our store -- duplicates=[]
INVARIANT PASS: grade: lapsed 0, apply_conflicts 0, auto_apply_rejected 0
INVARIANT PASS: every proposal is terminal/consistent with GET /approvals; no approval lost -- 28 proposals, 15 approvals
INVARIANT PASS: ingest cursor monotonic across restarts and == sim last_event_id at the end -- final=324345 sim=324345
INVARIANT PASS: credits ledger reconciles: initial=200.0 sim_remaining=184.0 ledger=16.00 of which unrecorded-at-crash=5.00
INVARIANT PASS: experiments were active (experiment_* proposals exist for the kills to land on)
RESULT: ALL INVARIANTS PASS
```
**What state is lost:** nothing committed. An interrupted chunk transaction rolls back and the chunk is re-read; an advance that returned before the crash is found by re-reading `/sim/state`; caches are rebuilt from SQLite. A kill inside a credit call can leave the spend unrecorded; startup reconciles the ledger against the sim's `credits_remaining` (5 credits were found unrecorded in this run and are booked as such). **Not shown:** the Linux grading box, public_01 or public_03 under kills, and a SQLite file corrupted on disk (the runbook covers it: re-ingest from the simulator, losing our `decisions` rows and detector state).

**Idempotency keys:** `proposal_id = "{workflow}:{plan_seq}:{kind}"`, written with the full body before anything is sent; the sim rejects a duplicate id with 409 and we adopt the existing approval. An INTENT row is matched against `GET /approvals` (or `config/history` for auto-applies) and resent verbatim only if absent. Ingest is idempotent on `event_id`.

**Simulator 4xx/5xx** (`controller/client.py`): 5xx and transport errors on reads retry with exponential backoff (`RETRY_ATTEMPTS = 5`, 0.5 s doubling to 8 s), then `SimUnavailable`. `POST /sim/advance` is never retried: on failure we poll `/sim/state` until `sim_minute` is stable across two reads (or raise `AdvanceNotApplied`; the loop gives up after 5). Mutating and credit-costing calls are attempted once; a transport or 5xx failure raises `OutcomeUnknown` and governance reconciles by lookup. 4xx are typed and never retried: 409 duplicate adopts the approval; 409 stale base is STALE and re-plans; 409 `not_approved` reconciles; 409 `finished` exits 0; 410 is LAPSED plus an alert; other 4xx on submit is `SUBMIT_FAILED` plus an alert.

**Determinism (`reports/determinism.md`).** Two concurrent clean public_01 runs with random `PYTHONHASHSEED`s first diverged at Day 1 15:15: the planner built allocation dicts in string-hash order and the simulator samples options in the dict's key order. After sorting keys everywhere (`configlib.normalise_weights`, `did_plan`, float sums over sets), `decisions` (2,543 rows), `proposals` (21), `config_versions` (22), `alerts` and the grade JSON (12,827 bytes) are identical.

## 10. Audit & observability
All modes read only our SQLite store (`--db FILE`, or the newest DB in `--state-dir`; `--json`). Real output from the run behind `reports/public_02_incidents.md`; long lines are cut:

`python -m controller why --state-dir state/public_02_incidents --workflow ks_cancel --at "Day 3 15:00"`:
```
why ks_cancel at Day 3 15:00
  active version v9 by controller_approved (observed Day 3 13:45, dims ["welcome_message", "voice", "prompt_version"])
  proposal ks_cancel:9:halluc_fix [approval] state=CLOSED base=v8 applied=v9 at Day 3 13:45
    summary: Revert P2 (set by supervisor Day 3 11:30) to P1: flags 5.5% vs failed Day-0 validation (n=200, p=0.0e+00);
             validation val_00001 pass 0.987; voice experiment: ramp V2 (lift +1.9%, z 0.29, n 233); ...
    impact=1.0 affected_leads=3673
    approval apr_00009: APPROVED (decided_at Day 3 13:26, observed_at Day 3 13:45) by policy approver of ks_cancel; the sim exposes no approver names
    policy: approver hours [10, 19], latency [20, 120] min, ttl 12 h, max 4 requests/24h
  proposal lifecycle: DRAFT 11:45 -> INTENT -> PENDING -> APPROVED 13:45 -> apply_intent -> APPLIED 13:45 -> MONITORING 14:00 -> CLOSED Day 4 13:45
  evidence: Day 2 12:00 did_flagged D2 (p=4.6e-07) ... Day 3 11:00 halluc_eval P1: flags 0.90% vs 1.37% ... Day 3 11:45 incident_opened
  post-apply monitoring:
    Day 3 14:00 experiment_applied: voice is live: V1 65.0%, V2 20.0%, V3 7.5%, V4 7.5%
    Day 3 17:30 incident_verified: P1: flags 0.74%, engagement ok
  superseded by v10 (controller_approved) at Day 4 12:15, proposal ks_cancel:10:experiment_update: welcome_message experiment: drop W3 (lift -7.9%, z -1.37) ...
```
`python -m controller why --state-dir state/public_02_incidents --lead ks_cancel:l00024766 --day 3` answers Compliance's per-customer question:
```
lead ks_cancel:l00024766 person ks_cancel:p0017593 workflow ks_cancel campaign ks_cancel:c0017 (created Day 2 08:00), day 3
  Day 3 11:39 attempt 2 welcome W3 voice V1 DID D1 prompt P2 cohort age_band=18-30 connected=True engaged=True
    allocation from config v8; prompt from config v8 active at the call time
  decisions behind config v8: by supervisor at Day 3 11:30 dims ["prompt_version"]
```
(The call was made on the supervisor's edited prompt P2 six minutes before our detector opened the incident; the allocation comes from the campaign's creation version, the prompt from the version active at the call time, per `docs/CONTEXT.md` section 3.)

**Alerts we would page on** (rows in `alerts`, rules in `controller/alerts.py`; routing is not built): `ingest_stalled`, `apply_by_near`, `credits_low`, `sim_5xx`, `fatigue_rejection` and `http_403` (our accounting or pre-check is wrong), `cohort_mismatch`. **Digest only:** `judgement_rejection`, `starved_experiment`, `weak_base_did`, `kpi_drift`, `person_analysis_failed`. `docs/RUNBOOK.md` says what to do for each.

## 11. Results
Summary tables from `reports/public_01_dev.md` and `reports/public_02_incidents.md` (the template's `public_01.md` is the first file), plus the dev scenarios in `reports/dev/`. Every report is a no-op-baseline comparison from `python -m sim grade`.

| scenario | workflow | conclusion rate (delta) | pickup (delta) | engagement (delta) |
|---|---|---|---|---|
| public_01 | ks_cancel | 0.381 (+14.5%) | 0.257 (+8.0%) | 0.515 (+4.9%) |
| public_01 | nw_kyc | 0.390 (+7.2%) | 0.259 (+6.9%) | 0.591 (+0.0%) |
| public_01 | nw_renewal | 0.455 (+8.4%) | 0.279 (+6.0%) | 0.556 (+1.9%) |
| public_01 | ALL | 0.408 (+10.6%) | 0.265 (+7.1%) | 0.544 (+2.7%) |
| public_02 | ks_cancel | 0.364 (+47.0%) | 0.248 (+35.0%) | 0.499 (+4.8%) |
| public_02 | nw_kyc | 0.405 (+8.0%) | 0.259 (+6.9%) | 0.591 (-0.1%) |
| public_02 | nw_renewal | 0.460 (+7.8%) | 0.279 (+6.4%) | 0.549 (+0.1%) |
| public_02 | ALL | 0.404 (+21.0%) | 0.261 (+17.4%) | 0.535 (+1.0%) |

| scenario | applied | beneficial / neutral / harmful | ALL conclusion / pickup / engagement | governance and incidents |
|---|---|---|---|---|
| public_01 | 19 | 8 / 11 / 0 | +10.6% / +7.1% / +2.7% | 12 requests (11 approved, 1 judgement rejection), 9 auto-applies, no incidents, 24 credits |
| public_02 | 26 | 7 / 19 / 0 | +21.0% / +17.4% / +1.0% | 16 requests (16 approved), 12 auto-applies; D2 flagged, share 0 from Day 3; prompt MTTR 135 min; 26 credits |
| kyc_flag | 25 | 7 / 18 / 0 | +22.7% / +16.5% / +3.5% | nw_kyc flagged DID share 0.988, 0.613, 0.327, then 0.0 on Day 6 (slow because nw_kyc applies at the next campaign); prompt MTTR 285 min; nw_kyc conclusion +82.7%; 29 credits |
| null_01 | 17 | 3 / 14 / 0 | +8.8% / +8.9% / -0.9% | no incidents graded; guardrail dip analysed below; 30 credits |
| bad_default | 16 | 7 / 8 / **1** | +7.6% / +5.9% / +0.8% | 4 judgement rejections; 30 credits |

All five runs: `auto_apply_rejected 0`, `lapsed 0`, `apply_conflicts 0` (public_01, public_02 from their reports; the three dev runs from `reports/dev/*.md`). The decaying `nw_renewal W3` variant's share of in-population calls on public_02 was 0.197 on day 4, 0.037 on day 5 and 0.0 from day 6; on public_01 it stayed at about 0.20 through day 7 (0.202 to 0.204), so the controller kept it live there; I did not investigate whether that was a still-positive ramp or a missed decay (`reports/public_01_dev.md`).

**Where we helped.** Pickup, from caller-ID health and per-cohort hours (public_02 ks_cancel +35.0%, because the flagged D2 is evacuated and the supervisor's bad prompt is reverted); engagement where a welcome or voice winner or the revert applies (ks_cancel +4.8% and +4.9%). nw_kyc is pickup-primary, so it gets caller-ID work only, and its engagement stays flat (-0.1% to +0.0%).

**Where we were harmful and why.** (1) **bad_default**, ks_cancel v3 engagement delta -0.017 (`reports/dev/bad_default.md`): the Day-1 bundle that carried the Day-0 sibling-prompt switch P4 to P3 ("P3 is clearly safer", 10 credits) together with cohorts, a schedule and the 7.5% experiment entry. The grader reports one number per bundle, so I cannot separate the pieces; the switch away from a permissive prompt is the likely cost, and it is the disclosed safety-versus-engagement trade that `docs/THRESHOLDS.md` documents (an earlier version without the materiality gate cost -14%). (2) **public_02** had one change graded harmful in an earlier run (nw_renewal voice, engagement delta -0.011 against the -0.010 line, report at `77a7fa1`). The current report has 0 harmful: its worst experiment step is nw_renewal v7, a ramp of voice V2 (+2.3%, z 0.27) and V4 (+10.7%, z 1.23) from 7.5% to 20%, graded -0.009 engagement and neutral. The earlier run's state database was overwritten by the regeneration, so its decision rows cannot be read and I could not identify which path produced it (entry, ramp, harm-stop, rollback or promotion); it was one voice-only change 0.001 below the line, in the size range of the disclosed exploration limit (a step onto a challenger that turns out slightly worse), and it does not reproduce in the current run. I did not weaken any safety rule to remove it. The harm-stop, 7.5% entry and 20% ramp share are unchanged.

**null_01 guardrail.** Engagement fell -0.9% overall with no harmful change. `reports/guardrail_analysis.md`: the "more repeat connects" hypothesis explains under 5% of it (0.02 to 0.06 pp), first-connect engagement and engagement by caller ID are unchanged, and the dip (-0.5 to -1.2 pp per workflow, Stouffer z about -1.5) is statistically indistinguishable from noise; repeat-connect engagement is lower in 6 of 6 comparisons (candidate explanation: a less selected second-connect pool, not testable from controller-visible data).

**Determinism:** identical decisions, proposals, configs and grade across two concurrent runs (section 9). **What I would change:** per-cohort deployment of experiment winners is rarely reached in 8-10 days; a longer run or a larger traffic share would be needed for effects under 10%.

## 12. Trade-offs & rejected alternatives
| Option | Why considered | Why rejected / what instead |
|---|---|---|
| Blended score (pickup + engagement) | Sales wants one number | Hides the guardrail (a change that helps pickup can hurt engagement: null_01); KPIs stay separate, a non-inferiority test guards the other metric |
| Thompson sampling / bandit allocation | Learns faster, less regret | No type-I control, hard to audit, and the grader judges each applied change: a randomly drifting allocation is many small judged changes. Fixed-horizon sequential tests (OBF + Holm) with a conservative ramp give a measured false-winner rate (1.0%) and a replayable rule; the price is power: +10% lifts are promoted in 34% of runs |
| Fixed-horizon test, one look | Simplest | Waits for the whole sample; OBF spends little alpha early, so a large effect can still stop at look 1 |
| Postgres | SRE preference, scale | SQLite WAL: one file, no daemon, 5,382 events/s measured; the schema ports, sharding by workflow is the scale plan |
| Per-person call-time deployment | Product P0 | Selection effect (a no-signal control qualifies 75-90% as many people at the same apparent +40% lift), data weight about 10%, biased person holdout (`reports/person_analysis.md`); analysis only |
| p < 0.001 per look for detectors | Spec value | Tests repeat every tick; tightened per-look levels (A10) |
| LLM `suggest-fixes` first | Direct route to a new prompt | Costs credits, candidates can be worse than the problem; known-good revert first, `suggest-fixes` as fallback |
| Auto-apply of welcome/voice experiment steps | Faster | Customer-facing; Compliance wants a named approval; auto-apply only for operational and risk-reducing changes |
| Revert the supervisor's edit by auto-apply | Faster MTTR | Prompts are never in `allowed_dims`, and A6 requires an approval naming the edit |
| Tenant-fair credit/approver allocation (C15) | Brief lists it | Budgets are per workflow already; cut |

**The thing we cut: per-person call time, with numbers** (`reports/person_analysis.md`, analysis on public_01 and public_02 stores). Eligible persons (>= 2 campaigns, >= 4 dials over >= 2 hour blocks): 2,055 to 7,076 per workflow; would qualify at P >= 0.8: 122 to 593 (6-9%). The posterior is about 90% cohort prior (data weight 9.0% to 10.4%). With no person effect at all the same rule qualifies 109 to 455 persons at a similar +37% to +42% lift (public_02 ks_cancel 593 vs 455, nw_renewal 530 vs 438), so the headline lift is mostly best-of-4 selection. Qualifiers carry 2-6% of dials: a workflow-level ceiling of +0.75% to +2.30% before the x0.25 off-hour penalty and fixed hourly capacity. Call time by cohort delivers the defensible part. The daily job is wired into the tick (`ENABLE_PERSON_ANALYSIS`) but left **off**: on a 2-sim-day public_01 run it raised the total tick time from 19.7 s to 24.1 s (+22%, 121 ticks each; mean tick 0.163 to 0.199 s, worst tick 1.4 to 3.0 s), over the 5% budget I set, with no change to proposals (8 in both). Run `python -m controller person-analysis --db <store>` to produce the report on demand.

## 13. Known weaknesses
- Experiment power is modest: effects under about 10% generally do not reach a verdict in an 8-10-day run, and a fast decay (under about 3 days) is not distinguishable from noise at a 20% share (`reports/mc_null.md`).
- A harmful grade is possible by design: exploration cannot be both free and never harmful (7.5% entry, 20% ramp). `bad_default` shows one (section 11), public_02 showed one in an earlier run, whose state was overwritten, so its root cause is inferred, not read from a decision row.
- The per-bundle grader score cannot separate a prompt switch from an experiment entry in the same bundle; I did not split bundles for that reason.
- One false-positive DID flag in five runs (null_01 nw_kyc D1); the false-positive rate of the detectors is not calibrated beyond that.
- The decaying `nw_renewal` W3 variant stayed at about 20% share on public_01 through day 7 and I did not diagnose why.
- Schedule changes have no concurrent control; the before/after check is confounded and conservative.
- Engaged-per-connect is confounded when pickup rises (section 11); an alert on it alone should be read against first-connect engagement.
- A supervisor version superseded within one advance cannot be recovered (A15). `why` reports the policy approver, not a person (A4).
- Crash tests ran on Windows and public_02 only. Ingest does not scale past about 10x without the changes in section 8. No pager integration. Per-person analysis is off for cost and signal.

## 14. If this went to production at Formi next month
Ordered, first two weeks:
1. **Days 1-2: shadow mode on one workflow (nw_renewal).** Controller runs with `GET` and detectors only (no config writes, proposals logged as DRAFT); compare its decisions with what the team did; replay the dev scenarios as regression.
2. **Day 3: alert routing.** Wire the PAGE alerts to a pager with the runbook link; keep digest alerts in a daily mail; add an alert on controller restarts.
3. **Days 3-5: Postgres plan and ingest hardening.** Streaming chunk ingest, batched commits and `wal_autocheckpoint` with an idle-tick checkpoint, behind the crash test (`scripts/crash_test.py` on Linux); decide SQLite-per-shard vs Postgres with Platform.
4. **Days 5-7: first live week on one workflow with approvals only** (no auto-apply), approver trained on `view`; compare approver rejection reasons against local validation.
5. **Week 2: enable caller-ID auto-apply** on the workflows whose policy allows it; compliance weekly summary (`view --weekly`) to Northwind; confirm the first Compliance sign-off.
6. **Week 2: enable experiments** on engagement-primary workflows with the 7.5% entry, reviewing every promotion by hand for two cycles.
7. **Week 2: re-run the per-person analysis** on real history (more connects per person) and decide, with the null control, whether it earns a flag; weekly re-probe of flagged DIDs; sharding by workflow before onboarding the next tenants.
