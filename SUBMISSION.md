# Outcome-First Agent Loop — Submission

**Name:** Rahul Siddappanor · **Date:** 2026-11-09 · **Hours actually spent (be honest):** ~3.5 ·
**Language / storage:** Python 3.11+ (`httpx`, `numpy`, stdlib `sqlite3`; `pytest` for tests) / one SQLite file
in WAL mode. No new dependencies beyond the repo's `requirements.txt`.

Runbook for on-call: README §11.

---

## 0. TL;DR
- One synchronous process: it ingests each chunk atomically with its checkpoint, decides at fixed points, and
  changes config only through a persisted proposal state machine (approval or in-policy auto-apply) that
  reconciles after any crash.
- Learning: a 2-stage welcome/voice test (KYC: caller ID). Stage 1 is a 2-day 80/10/10 harm screen. Stage 2 is
  a 50/50 confirmation on fresh data at a pre-declared MDE. Winners are promoted with a 10% holdback, decay is
  checked daily, and rollback follows the policy. Caller-ID health and hallucination incidents use
  population-level detectors with measured false-positive rates.
- Results on **Linux** (the graders' platform), over 3 runs per scenario (published seed + 2 reseeded
  worlds): **0 harmful changes in all 6**. **public_01:** conclusion rate **+3.0% to +4.4%** vs the no-op
  baseline (KYC pickup +17% to +21%). **public_02:** **+15.5% to +17.1%**; spam-flagged caller ID moved to
  ~5% the same day; the bad supervisor prompt fixed through approval in **330 minutes** in every run.
- Cut: per-person call time (C4), cross-tenant fairness (C15), LLM-led prompt search (only used as fallback), UI.

## 1. Assumptions
1. Guardrail `max_drop` (e.g. `pickup_rate_max_drop: 0.02`) is **absolute** (2pp), tested as non-inferiority on
   the lower 95% bound of the difference.
2. `engaged ⇔ disposition ∈ {concluded_interested, concluded_not_interested}`, verified on 141k history calls.
   Ingest counts from `disposition` and pages if the two ever disagree.
3. Uploaded leads = `lead` events (checked against `campaign_created.leads`). Business outcome is computed per
   campaign and never used to pick winners, because arms are sampled per dial, not per lead.
4. On `next_campaign_only` workflows the whole agent config, **caller ID included**, is locked per campaign.
   I checked the simulator's dialler; calls carry the campaign's `config_version`. All analysis filters by
   `config_version`, never by wall-clock time, so KYC needs no special case.
5. History (14 days, business default) is the baseline for every option that ran in it. Options that never ran
   are "unknown". No effect is predicted for them, only an exposure bound.
6. A memo's stated preference that is stricter than policy is honoured as policy: Kestrel's "after 11:00" and
   "two requests a day" (`settings.TENANT_*`).
7. An approver's judgement-call rejection is the client's decision. Content is re-asked once only for an open
   safety incident, after every other candidate has been tried.
8. A supervisor edit always stands. We never revert one except through an approval request that names it.
9. Simulated time is the only clock for logic. Wall time is used only for load metrics.

## 2. Scope decisions
| # | Capability | Built / Partial / Cut | Why | What it would take to finish |
|---|---|---|---|---|
| C1 | Ingestion at load scale | **Built** | Floor; SRE non-negotiable | Multiprocess parse at 3-5x (§8) |
| C2 | Shared cohort object | **Built** | One `Cohort` + segment-level `agg`: every consumer counts the same rows | — |
| C3 | History bootstrap | **Built** | Baselines on day 1 for free | — |
| C4 | Per-person call time | **Cut** | 20-40% returning leads with 6-8 attempts each is too sparse to learn a person's hour | Per-cohort hour weights first (stretch), per-person only with months of data |
| C5 | Caller-ID health | **Built** | Cheap, threshold-based, KYC's pickup lever | Recovery detection (we keep 5% on a flagged number but don't restore it) |
| C6 | Welcome/voice experiments | **Built** | Where the engagement lift is | Interaction test on the final pair (needs more n than 8 days give) |
| C7 | Promotion, decay, rollback | **Built** | Graded by hidden scenarios and by Compliance | — |
| C8 | Hallucination response | **Built (lean)** | Revert-first; LLM only as a fallback | — |
| C9 | Governance client | **Built** | Absolute constraint | — |
| C10 | Impact, affected leads, dry run | **Built** | Required on every proposal; evidence-classed | Per-cohort dry-run replay |
| C11 | Supervisor view | **Partial** | CLI one-screen (`status --supervisor`) | A web page over the same query |
| C12 | Audit store | **Built** | `decisions` row for every evaluation; `why` CLI | — |
| C13 | Crash recovery, demonstrated | **Built** | `scripts/crash_test.py` (4 kills incl. external) | — |
| C14 | Loop observability | **Partial** | status file + alerts table; no Grafana | Export the same snapshot as Prometheus metrics |
| C15 | Cross-tenant fairness | **Cut** | Per-workflow quotas already come from each policy | A global credit/approval budget allocator weighted by impact score |

The principle: build what hidden scenarios grade (governance hygiene, harmful changes, incident fix time, decay
rollback) and what can't be faked in review (crash safety, audit). Cut anything that needs data the simulator
doesn't provide in enough volume. Depth beats breadth: five capabilities done properly.

## 3. Stakeholders

### 01 Sales (Nikhil)
- **Accepted:** per-client lift numbers, reported per KPI with confidence intervals (`why`, grade tables).
- **Declined:** a blended score (pickup and engagement are separate KPIs by constraint). "Live for everyone by
  evening" (a variant gets a 2-day harm screen plus a fresh confirmation). Rolling "persuasive" P4 out
  everywhere: prompts are not an experiment lever here, need validation evidence, and winners don't transfer
  between clients.
- **Wrong:** "Kestrel turned on auto-apply for everything". Their policy covers 4 dimensions with
  `max_shift 0.2` and never prompts. "Northwind is fine with auto-apply on KYC": `nw_kyc` has
  `auto_apply.enabled: false`.
- **Reply:** "Nikhil, for the summit I can give you one honest lift number per client and per KPI, with the
  confidence interval, e.g. Northwind renewal engagement +x pp. I won't blend pickup and engagement into one
  score. That's a platform rule, and a regulated buyer will ask how it's computed. Two corrections before the
  demo: Kestrel's auto-apply covers 4 settings with small shifts and never scripts, and Northwind KYC has
  auto-apply switched off. 'Winning by lunch' is usually noise. We confirm on fresh data in about 3 days, and
  that's what makes the number safe to put on a screen. Persuasive P4 stays out until it passes validation per
  client."

### 02 Northwind Compliance (Meera)
- **Accepted:** named approval for every customer-facing change (welcome, voice, prompt, including promotions
  and reverts, even where policy would allow auto-apply). Validation evidence on every prompt change. The
  per-customer audit answer (`why --lead`), available in seconds. Approver hours. Slow and evidence-led changes
  (exposure capped at 10% per untested option, 20% in total).
- **Pushed back:** a rollback *toward the known control* within `max_shift` is auto-applied where the policy
  allows it (it reduces exposure), and reported in the summary.
- **Wrong:** the caller-ID and timing latitude exists on **renewal**, not on **KYC**. KYC auto-apply is
  disabled, so caller-ID rotations on KYC go through her approvers.
- **Reply:** "Meera, agreed on all five. Every change a customer can hear goes to your named approver with the
  evidence attached, and prompt changes carry a validation run id. For IRDAI, we can answer 'why did customer X
  hear Y on day Z' immediately: each attempt maps to the variant, config version and the approval that made it
  live. One correction: the policy we run allows caller-ID/timing auto-changes on renewal only. KYC has none,
  so KYC caller-ID changes will come to you. Untested options never reach more than 10% of calls each, and
  anything worse than control is stopped within a day."

### 03 Platform/SRE (Kabir)
- **Accepted:** all three non-negotiables. The kill/restart test kills the controller 4 times, including a
  hard external kill, and checks for no double apply, no lost approval, and ingest equal to the stream.
  Idempotency keys exist for every mutation (§9). Pages are actionable and summaries don't page (README §11).
  There's no new stateful infra (one SQLite file), the load numbers are measured (§8), and loop health is
  visible without logs.
- **Pushed back:** nothing. The 10x answer is honest: SQLite's single writer and single-threaded parsing break
  first (§8).
- **Reply:** "Kabir, it's one process and one SQLite file, so there's nothing new to operate at 2 a.m. Kill it
  anywhere: each chunk commits atomically with its checkpoint, and every approval/apply has an intent row and
  idempotency key, reconciled against the API before any retry. `scripts/crash_test.py` does 4 kills per run
  and asserts no double apply and no lost approval. Load: one simulated day of public_03 takes 34-40 s of wall time in steady state on Linux, measured on an 8-thread laptop with the simulator on the same box, against your 10-minute budget. At 10x the single writer and JSON parsing
  break first. The plan is a fan-out parse with one writer up to about 5x, then Postgres partitioned by
  workflow. `status.json` shows lag, decisions/hour and credit burn."

### 04 Kestrel Ops (Anita)
- **Accepted:** her edits are never undone silently (an edit ends our experiment on that dimension and stands).
  At most **2 requests a day, none before 11:00**, which is enforced in code and stricter than her policy's 4.
  One exception: a validated fix for a live hallucination incident may use the policy's own limit.
  Batched requests (welcome + voice in one). A one-screen view (`status --supervisor ks_cancel`). No
  word-for-word fix ("strict"/"near-verbatim" prompts are skipped as candidates).
- **Pushed back:** if her own prompt edit causes a hallucination spike, we will **propose** a revert with
  validation evidence, named as a reversal of her edit. We won't stay quiet, and that one request may exceed
  her two-a-day preference (never the policy), because customers are being misled until it lands. Caller-ID rotation off a
  spam-flagged number is auto-applied (within policy) and reported immediately rather than asked first,
  because waiting costs pickups on every call.
- **Reply:** "Anita, your edits stand. If you change something we're testing, we stop that test and keep your
  version. You'll get at most two requests a day, never before 11:00, each bundling everything we want to
  change; the only exception is a fix for a live hallucination incident. `status --supervisor ks_cancel` is your one screen: what's tested, what's winning, what we need from
  you, what changed today. Two things we'll do without asking first: move calls off a caller ID the networks
  have flagged, and stop a test option that's clearly worse. Both are reported the same hour. If a prompt edit
  starts hallucinating, we'll send you a revert with evidence. We never pick word-for-word scripts."

### 05 Product (Tara)
- **Accepted:** separate KPIs. One cohort object. Proposals with an impact score, diff, affected leads and dry
  run. Expired is treated as rejected and redrafted from fresh data. Only observed evidence counts
  (evidence-class tags, data filtered by config version). Promotion per workflow.
- **Answered (open question):** minimum size and window are *derived*: Stage 2 n = 1,556 connected/arm for a
  5pp engagement effect on renewal (about 3.3 days), 1,911 dials/arm for 4pp pickup on KYC. The cost is about
  6 days per full cycle, and small true effects end inconclusive. The false-winner rate is ≤ 2.5% one-sided
  per promotion.
- **Declined:** per-person call time as P0 (too sparse). Caller-ID health and a supervisor view are in.
- **Reply:** "Tara, cohort size and window: I derived them, not guessed. To detect a 5pp engagement change at
  a ≤2.5% false-winner rate with 80% power, renewal needs about 1,560 connected calls per arm, which is about
  3 days at 50/50. A full screen, confirm and promote cycle takes about 6 days, so smaller effects come back
  'inconclusive'. That's the price of not shipping noise. The impact score is conservative: lift lower bound ×
  share affected, 0 if not positive. Per-person call time is out: 6-8 attempts per person can't support it.
  Caller-ID health and the supervisor view are in."

### 06 CTO (Aryamann)
- **Accepted:** the whole frame. Choices and cuts are explicit (§2). It's revert-before-LLM: public_02's
  incident cost 5 credits. Scale claims come from measurements. The docs are written for the on-call
  engineer.
- **Wrong claims found:** listed under 01, 02 and 04.
- **Reply:** "Five capabilities done properly: ingest + crash safety, governance + audit, the
  screen→confirm→promote→decay loop, caller-ID health, and hallucination response. I said no to per-person
  call time, cross-tenant fairness and a UI. Every change is explainable from our own store in one command.
  The first thing to break at 10x is the single SQLite writer; the numbers and the plan are in §8."

## 4. Architecture
```
               ┌──────────────────────────── controller (one process) ───────────────────────────┐
 /sim/advance ─┤ main loop: decide(now) → advance(60m) → ingest → decide(now) …                   │
 /events/chunks│   ingest.py ── chunk → agg / leads / campaign_kpi / calls_log + last_chunk (1 txn)│
               │   configs.sync ── /config + /config/history → config_versions (supervisor edits)   │
               │   detectors.py (caller-ID, hallucination, drift) ─┐                               │
               │   incidents.py (validate → fix) ─────────────────┼─► governance.draft(patch)      │
               │   experiments.py (screen/confirm/promote/decay) ─┘        │                       │
               │   governance.py: DRAFT→SUBMITTING→PENDING→APPROVED→APPLYING→APPLIED (+auto path)   │
 /approvals ◄──┤      intent row committed before every POST/PUT; reconcile before any retry        │
 /apply, PUT ◄─┤   decisions table: every evaluation + every transition (audit)                     │
               │   status.json  ·  why CLI  ·  status --supervisor                                  │
               └───────────────────────────── state/controller.db (SQLite, WAL) ───────────────────┘
```
State lives only in SQLite. On restart: check that the store matches this simulator world (else archive it),
catch up chunks after `last_chunk`, reconcile every in-flight proposal against `GET /approvals` and
`config/history`, settle unknown credit calls as spent, then continue. A decision pass records the minute it
completed, so a restart within the same minute doesn't double-count detector windows.

## 5. The learning loop
- **Cohorts.** Every workflow starts with `default` only: a baseline difference (seniors engage more) isn't a
  reason to split. Cohorts are defensive. At promotion, each age band (the pre-declared split; largest
  baseline spread) is checked for harm at α = 0.05/4. A band where the winner is significantly worse becomes a
  cohort kept on control (at most 3 cohorts). Small groups such as 60+ (about 140 connected/day) can be
  protected but not optimised. Cohorts are an ordered first-match list over segments, so no call is counted
  twice (unit-tested).
- **Experiment design.** Welcome and voice are sampled independently, so one allocation is a factorial:
  main effects per dimension, both in one batched request. Stage 1 runs 2 days at 80/10/10. Challengers are
  taken in catalogue order (no history ranks them). A daily uncorrected harm stop runs at one-sided α=0.05.
  It's a **safety gate, not a selector**: at 10% it catches a challenger about 10-13pp worse (renewal 13.5pp
  after day 1, 9.6pp after day 2). The best survivor at or above control advances; otherwise the next two
  untested options are screened if days remain. Stage 2 is 50/50 on fresh data only (no winner's curse), with
  looks at n/2 and n. KYC uses the same machinery on caller ID (pickup primary).
- **Deciding a winner.** A one-sided two-proportion z-test at α\* = 0.05/2 looks = 0.025, the same α the
  sample size uses. Holm across challengers where m>1. The guardrail must pass non-inferiority (lower 95%
  bound > −2pp). The test is re-checked on data up to submission time before the request goes out. Ties break
  in fixed option order. **False-winner rate ≤ 2.5%** per confirmed promotion (one-sided). There is never a
  look beyond the pre-declared two. A promotion request that doesn't land (expired, lapsed, dropped) is
  re-proposed only if a look already passed *and* it still passes on data up to now (at most twice).
  Requiring both can only lower the error rate, so the α budget holds. **Recency check:** a promotion also needs
  the latest 24h window not to show the challenger behind control. A pooled test can be carried by strong early
  days of a variant that is already fading (Linux trace: nw_renewal W3 led by 9pp and 5pp on D3-D4, then
  trailed by 3pp on D5-D6, and promoting it at D6 was graded harmful). Being an extra requirement, it can only
  lower the false-winner rate. It is not free: it also blocks a real winner that has one noisy day, and
  `n_required` doesn't account for it. Monte Carlo at the MDE (true +5pp engagement on renewal, +4pp pickup on
  KYC) puts power at about 0.77-0.78 instead of 0.80, so the power figures above are slightly optimistic. A
  promotion is also revalidated at apply time, so one bad day in between can drop it.
- **Inconclusive at the final look (pre-registered rule): change config only on evidence.** Inconclusive
  means neither "proven better" nor "proven worse". Three cases: (a) *significantly worse* on the primary or the
  guardrail (one-sided α=0.05): back to control. (b) Not significantly worse and **ahead or tied** on the
  primary: the split stays exactly as it is, with no change request, in its own state, `MONITORING_SPLIT`
  (never shown as a promotion), under the daily decay monitor below. (c) **Behind but not significantly**: the
  challenger is stepped down to the 10% screening share (approval), then monitored. After a test powered for
  the MDE, a challenger that is behind is unlikely to be better, so 50% of traffic on it carries risk with no
  expected upside, and the decay monitor is too strict to move it quickly. A full revert of a non-significant
  difference is a coin flip; the step-down bounds exposure at the limit we already accept for an untested
  option. If the step-down is rejected, the 50/50 is kept and monitored (the client's call). History: "always
  revert" reverted a better challenger (−3.7% engagement in an independent reproduction), which is why a
  non-significant difference never triggers a full revert.
- **Decay and rollback.** The winner goes to 90% with a 10% concurrent holdback. Every day at 13:00, a
  non-overlapping 24h window compares winner vs holdback on the primary and on the guardrail. The decay α is split
  across both checks and all remaining days: **α = 0.05 / (D_max × 2)** (D_max = days left; 30 in production),
  so the family-wise false-rollback rate is ≤ 5%. One window of a 10% holdback is only about 110 connected
  calls, so **one window never triggers a full revert**: a first signal only cuts exposure by one in-policy
  de-risk step where the policy allows it (otherwise it is recorded and watched), and the full revert is
  requested only if the **next fresh window also fires**. A quiet window clears the suspicion. A de-risk step
  that never confirms is not one-way: after 3 consecutive clean daily windows the pre-de-risk split is proposed
  back once, through approval (never auto). This replaced a single-window rule after an independent
  reproduction traced two harmful full reverts to it on ks_cancel: W2 → W1 on a pickup p=0.0036 between welcome
  arms (welcome plays after pickup, so almost certainly noise), and V3 → V1 on an engagement p=0.0073 with a
  holdback of 110 calls. Under the split α the second no longer fires; under confirmation the first only
  de-risks (both are regression tests). In the final Linux runs a first signal produced exactly one de-risk step
  (graded neutral) and no full revert. *Deviation from the original design:* a significant guardrail drop, not
  the non-inferiority bound, because with a 10% holdback the bound's width alone would trigger rollbacks on
  noise. Routing of a confirmed revert: auto-apply if within `max_shift` and the dimension is allowed,
  otherwise approval. An approved-but-unresolved revert stalls after 48h with a page and is never chained. Once
  a client rejects a rollback, later rollbacks go to approval only, with no automatic step; asking again needs
  a fresh two-window confirmation, and the client is re-asked at most once (so a decision already made doesn't
  eat the tenant's daily request quota).
- **Call time and caller ID.** History gives each number's own pickup by hour. A number is flagged only if it
  is worse than *its own* history at matched hours (z ≤ −3) **and** worse than its peers now (ratio ≤ 0.8),
  with ≥300 dials in a 3h window, on 2 consecutive hourly evaluations. The windows overlap by 2h, so this is a
  debounce against one noisy hour, not two independent samples; the measured false-positive rate (§7) uses
  exactly this rule. An evaluation without enough data (e.g. overnight) resets the streak. Numbers without
  history use the peer test at 0.7, **and** are held to the workflow's own historical pickup at the same hours
  (all numbers that dialled in history): z ≤ −3 **and** ratio ≤ 0.7, the same significance-plus-effect pairing as
  the other branches, so an untested number that is simply bad is caught even when its peers are weak too, while
  a fine but slightly weaker new number is never rotated out. A solo number
  uses its own baseline at z ≤ −4. **Where traffic goes:** to healthy numbers *with evidence* first (≥500 dials
  of their own, history or live), keeping 5% on the flagged one (flagged numbers share at most a 20% watch
  budget, so many flagged numbers never crowd out the healthy ones). Untested numbers in use are capped at 10%
  each, the same cap as an untested variant. Only when no evidenced healthy number is left does volume move to
  untested numbers, and then never by auto-apply: it goes to approval, saying so. (An independent reproduction
  showed the earlier rule auto-moving ~25% each onto two untested numbers, one at 17.4% pickup, eating the
  2pp guardrail.) Call-time optimisation is cut (C4).
- **Guardrail KPI.** Promotion needs the guardrail non-inferiority pass. Decay monitoring rolls back a
  significant guardrail drop. KPI drift is alerted daily. Pickup and engagement are always computed from
  their own counters (`kpi.py`, `metrics.Counts.num_den`).

## 6. Governance
- **Lifecycle.** `DRAFT → SUBMITTING → PENDING → APPROVED → APPLYING → APPLIED`, plus `AUTO_APPLYING`. Terminal
  states: `REJECTED` (no resubmit of the same content), `EXPIRED` (owner redecides from fresh data), `LAPSED`,
  `STALE`, `NOT_PERMITTED` (403 → approval fallback + page) and `DROPPED` (re-check failed). A stale base is
  classified by the actor of the intervening versions. If a supervisor touched our dimension, their change
  stands and nothing is re-proposed. If it was our own change, the same patch is rebased automatically.
  Proposals are stored as **patches**, so a rebase is mechanical.
- **Batching and timing.** One routine request in flight per workflow, batching every dimension that changes
  together. Submission happens only in approver hours (Kestrel ≥ 11:00), and only when the p75 latency plus one
  tick fits before hours end. Routine requests expire at the end of that approver day, so stale evidence isn't
  approved tomorrow. A rolling 24h quota keeps one slot per workflow for rollback/incident (Kestrel capped at
  2/day by their own request). **One deliberate exception, stated to the client (§3, memo 04):** a validated
  fix for a live hallucination incident may use the policy's own limit of 4 when both of Kestrel's slots are
  spent. It never exceeds the policy, and every use raises a summary alert naming the request. Without it, a
  fix sat ready overnight on two reseeded worlds (MTTR up to 27h). Approved changes are applied on the next tick (60-minute step against a 2h apply window).
- **Auto-apply vs approval.** Auto-apply is used for caller-ID rotation and for harm-reducing moves *toward
  control* within `max_shift`. Approval is used everywhere a customer hears something new (start of
  exploration, advance, promotion, prompt), **even on Kestrel where policy would allow it**. Auto-applies are
  never chained to get past `max_shift`. Eligibility is checked locally first. A 403 is treated as a bug
  signal.
- **Honest proposal contents.** `diff` is old→new per cohort and dimension. `affected_leads` is open leads in
  running campaigns whose allocation changes (zero for agent dims on next-campaign workflows) plus the next
  batch × the changed share. `dry_run` gives per option a class (observed / estimated / unknown) with rates and
  CIs; unknown options get only an exposure bound, plus the test analysis. `impact_score`: promotion =
  clip(lift LCB/10pp) × share; exploration = 0.1 × challenger share; fix/rollback = clip(harm/10pp) × share.
  It's one function, unit-tested.
- **Supervisor edit mid-experiment.** It's recorded and alerted in the summary. Every experiment on the edited
  dimension ends as `INVALIDATED` (data stays keyed to old versions). Drafts touching that dimension are
  dropped. A prompt edit starts a 24h heightened hallucination watch. Edits are tracked by "last observed
  version", separately from what's stored, so an edit stored by a restart's sync still triggers all of this.
  In public_02's final run no test was live on renewal at the D5 15:00 edit (its exploration request had been
  declined). In a development run the same edit ended the voice test while the welcome test continued, and
  the governance tests cover the drop/stale paths.

## 7. Incidents
- **Detection.** A one-sided Poisson test on hallucination flags vs the prompt's history rate (or the
  workflow's), p < 0.001, ≥200 connected calls, on 2 consecutive hourly evaluations of a rolling 3h window
  (overlapping, so a debounce, as for caller ID). After a supervisor prompt edit
  ("heightened watch") it tests all calls on the new prompt since the edit, and one window suffices.
  Measured fire rate on held-out history: see `reports/detector_fp.md`. Caller-ID: 1 alarm / 24
  workflow-days on holdout A (0.042 per workflow-day). Hallucination: 0 / 24. Both are within the
  1-per-10-days bar, so holdout B was never touched. These are upper bounds: history may contain real events.
- **Picking a fix.** Candidates are validated one at a time in a pre-declared order: revert to the previous
  prompt, then the grounded catalogue prompt, then LLM suggestions (3 credits, fallback only). The first that
  passes `pass_rate − 1.64·SE ≥ 0.96` (and ≥ 0.97 raw) is proposed. We never validate several and pick the max.
  A validation run for the same workflow and prompt is reused, never paid for twice. "Strict/near-verbatim" is
  skipped (memo 04).
- **Credits.** Only the incident path spends credits, capped at 25 per incident. LLM suggestions are the
  optional part of that spend and only run while at least 60% of the starting credits would remain.
  Validating a known candidate (the revert, the grounded prompt) is essential spend and may use the reserve.
  Each credit call has an intent row first, is never retried, and counts as spent if its outcome is unknown.
  Re-asking for a validated fix after a non-decision (expired/lapsed) is capped at 2 asks per candidate. A
  drop because the fix is already live moves to verification, and a drop because the flagged prompt is gone
  closes the incident, so nothing re-proposes in a loop.
- **Verify after apply.** After ≥200 connected calls and ≥6h on the new prompt, the hallucination test must
  no longer fire. Engagement is compared with the pre-incident baseline. A drop is flagged for review, not
  silently kept.
- **public_02 timeline** (Linux, published seed, from `why`; time-to-fix was 330 minutes on all three Linux runs):

| sim time | event (from `incidents.timeline_json` / `decisions`) |
|---|---|
| D3 11:30 | supervisor edit v5 switches ks_cancel to prompt P2 (observed at the D3 12:00 tick, heightened watch starts) |
| D3 15:00 | watch test on every P2 call since the edit: 4.4% flagged vs 1.47% baseline over 316 calls (p=3.4e-4) → incident #1 |
| D3 15:00 | candidate 1 = revert to P1: validation val_00001 pass_rate 0.986 (lower bound 0.977 ≥ 0.96) → PASS, 5 credits |
| D3 15:00 | proposal `ks_cancel:63:1` (urgent, names the supervisor edit it reverses) submitted |
| D3 16:23 | approved (apr_00007); seen at the 17:00 tick (60-min step), applied as v7 |
| D3 23:00 | verified: P1 flag rate back within band, engagement not below baseline → RESOLVED |

Grader: `mttr_minutes: 330`, `fixed_by: controller_approved`, 1 validation run, 0 LLM calls. Hallucinated calls on
ks_cancel: 73 vs 310 in the no-op baseline.

## 8. Scale
Measured with `python scripts/load_test.py` ([reports/public_03_load.md](reports/public_03_load.md)) on Linux
(Ubuntu under WSL2, 8 logical CPUs, Python 3.10), with the simulator on the same machine and included in the
timings:

| metric | value |
|---|---|
| total wall time (bootstrap + 5 simulated days) | 276 s |
| history bootstrap (14 days, chunk 0) | 84.9 s |
| wall seconds per simulated day (advance + ingest + decide) | D0: 123.2, D1: 33.6, D2: 39.9, D3: 38.7, D4: 39.5 |
| mean wall per simulated day | 55.0 s (target < 600 s) |
| ingest throughput (all chunks, parse + commit) | 60,105 events/s over 9,737,078 events in 162 s |
| last decision pass | 277.2 ms (12 workflows) |
| peak RSS (controller) | 527.7 MB |
| store size at end | 581 MB (30.6 MB per simulated day incl. history) |
| calls dialled after D0 (aggregated) | 3,240,000 |
| rows | leads=2,304,000, agg=560,538, calls_log=3,240,000, decisions=390, proposals=39 |

- **Wall time per simulated day: 34-40 s for D1-D4, 123 s on D0, 55 s mean**, against a 600 s target: about 15x
  headroom in steady state. D0 carries the first decision passes for all 12 workflows right after an 85 s
  history bootstrap of about 5.7M events. (An earlier Windows run showed one 520 s day while the process was
  mostly waiting on disk; it did not reproduce on Linux.)
- **End-to-end decision lag:** a decision sees every event up to the current tick. The lag is one tick (60
  simulated minutes) plus about 0.3 s for the decision pass over 12 workflows.
- **Ingest** runs at about 60k events/s including `calls_log`, all in one thread. JSON parsing and SQLite
  inserts dominate.
- **Memory:** 528 MB peak RSS, mostly the per-campaign lead-feature cache (calls don't carry features). It is
  evicted after 6 days.
- The graders' box has 4 vCPU; the controller is single-threaded, so per-core speed matters more than cores.

**What breaks first at 10x (~8.5M events/day).** Single-threaded JSON parsing and SQLite's **single writer**.
Partitioning the compute alone doesn't fix the writer. In order:
1. **Now:** one process with one ingest/checkpoint owner and one writer. Decisions read after each commit.
2. **3-5x, still SQLite:** one fetcher owns the chunk cursor and fans call lines out by `workflow_id` hash to N
   parse/aggregate worker processes. Workers return small aggregate deltas. The single writer applies all
   deltas + `calls_log` + checkpoint in one transaction per chunk (the checkpoint stays atomic). Decision
   workers per workflow group read through WAL readers.
3. **10x+, production:** Postgres (SRE already runs it), with tables partitioned by `workflow_id` and one
   consumer per partition, each owning its own checkpoint row. Workflows are independent for governance,
   experiments and quotas, so no cross-partition coordination is needed. The fetcher that splits each global
   chunk is the only shared component and is stateless except for its cursor. `calls_log` moves to
   time-partitioned tables or object storage plus an index.
Tenants map onto partitions. A per-tenant credit/approval budget (C15) would sit in front of governance.

## 9. Reliability
- **Crash test** (`python scripts/crash_test.py`, log in `reports/crash_test.log`): one public_01 run, killed
  (1) right after a proposal is PENDING, (2) right after APPROVED is detected and before apply, (3) mid-chunk
  before commit, (4) by an external hard kill at an arbitrary time, then run to the end. It asserts no duplicate
  `proposal_id` in any `config/history`, every controller version present as APPLIED in our store, no submitted
  proposal stuck mid-flight, checkpoint = last chunk, and aggregated calls = calls in the stream. Result on the final code, on Linux: **PASS**: 4 kills (at D0 10:00, D0 13:00, D2 12:00 and an external kill at D3 09:00), 9 controller versions across 3 workflows, 0 duplicates, 0 stuck, checkpoint 105 = 105, 83,200 = 83,200 calls.
- **One error never ends the run.** Every decision step (config observer, detectors, incidents, experiments,
  governance) is isolated: an exception rolls back that step, pages with its name, and the loop carries on. If
  the process itself dies (e.g. the simulator unreachable past the GET retries), `run.sh` restarts it up to 5
  times; crash recovery makes a restart a resume. The controller exits 0 only when the scenario has finished.
  A SIGTERM/SIGINT to `run.sh` (e.g. a grader's timeout) is forwarded to the controller and never restarts it.
- **Interrupted downloads:** a chunk stream that drops mid-way is never resumed. The partial parse is
  discarded and the whole chunk is re-read (up to 3 attempts), so no event is counted twice. A call for a lead
  we never saw is skipped and paged, rather than blocking ingest forever.
- **What's lost:** nothing durable. An in-memory lead cache is rebuilt per campaign on demand. A credit call
  whose response was lost is counted as spent (deliberately), and its candidate is skipped.
- **Idempotency keys.** Approval: `proposal_id = wf:decision_id:attempt` (deterministic); reconciled via
  `GET /approvals?workflow_id`. Apply: `approval_id`; reconciled via `config/history`. Auto-apply:
  `proposal_id`; reconciled via `config/history`. Ingest: the chunk number (checkpoint in the same
  transaction). Credit calls have none, so they are never retried.
- **4xx/5xx.** GETs retry with backoff on 5xx/connection errors only. A mutation that times out or returns 5xx
  is an *unknown outcome*: the intent row stays, and the next tick reconciles before retrying (the same path as
  a restart). 409 duplicate → reconcile. 409 stale → actor-classified rebase. 410 → LAPSED. 403 → approval
  fallback + page. 402 → page, the incident stops spending. Repeated 5xx (>5) pages.

## 10. Audit & observability
```
$ python -m controller.why ks_cancel --at "D3 18:00" --db state/public_02_incidents.db   # (output trimmed: config, diff, dry run)
workflow: ks_cancel
at: D3 18:00
version: 7
actor: controller_approved
applied_at: D3 17:00
proposal:
  proposal_id: ks_cancel:63:1
  kind: incident_fix
  path: approval
  summary: Switch prompt P2 -> P1 to stop a hallucination spike
  rationale: P2 is flagging 0.0443 of connected calls vs a 0.0147 baseline (Poisson p=0.000342, 316 calls, held for consecutive windows). P1 passed va
  diff: …
  affected_leads: 5174
  impact_score: 0.296
  evidence:
    validation_run_id: val_00001
  dry_run: …
  submitted_at: D3 15:00
approval:
  approval_id: apr_00007
  decided_at: D3 16:23
  approver: kestrel_finance approver (simulated)
triggered_by:
  - id=63; minute=D3 15:00; kind=incident; rule=first candidate to pass validation; outcome=propose; inputs={'candidate': 'P1', 'validation': {'valida
lifecycle:
  - minute=D3 15:00; rule=submitting: urgent: within window and expected to be decided before expiry; outcome=SUBMITTING
  - minute=D3 15:00; rule=request accepted; outcome=PENDING
  - minute=D3 17:00; rule=approver approved; outcome=APPROVED
  - minute=D3 17:00; rule=applying approved change; outcome=APPLYING
  - minute=D3 17:00; rule=applied; outcome=APPLIED
what_happened_next:
  - minute=D3 23:00; kind=incident; rule=verified: hallucination rate back within band; outcome=RESOLVED
superseded_by: v8 (controller_approved) at D5 14:00
```
Per customer (IRDAI): `python -m controller.why --lead ks_cancel:l00022500` lists each attempt with time,
variant heard, config version, outcome, and "live because proposal X (summary); approved apr_N by the
kestrel_finance approver at D3 15:36" (or "business default", "supervisor edit", "auto-applied within
policy").

**Page:** ingest stalled > 2 ticks; > 5 consecutive 5xx; auto-apply 403 despite the local check; a
hallucination incident opened, with no validated fix or out of incident credits; credits below the reserve;
de-risk stalled 48h; no healthy caller ID left; engaged/disposition mismatch; a decision module raised (it is
isolated, the rest of the loop keeps running); calls for unknown leads skipped. **Don't page (summary):**
supervisor edits, caller-ID rotations that succeeded, rejections, inconclusive tests, KPI drift, "client kept
promotion despite decay". The full table with actions is in README §11.

## 11. Results
**Every number below was measured on Linux** (Ubuntu under WSL2, Python 3.10, numpy 2.2.6), the graders'
platform. The simulator is deterministic within a platform but not across platforms (an independent Linux
reproduction matched exactly, while the same code on Windows gave different worlds: e.g. 416 vs 406 hallucinated
calls in the public_02 baseline), so Windows numbers are not reported. "Three runs" means the published scenario
plus two reseeded worlds: same policies and hidden truth, different random draws (`scripts/multi_run.py`).

### public_01 (dev, no incidents): range over 3 runs
Run 1 is the published scenario; the others change only its random seed (same policies and hidden truth).
Each run has its own fresh no-op baseline; Δ = change vs that run's baseline.

| run | conclusion Δ (ALL) | ks_cancel primary Δ | nw_kyc primary Δ | nw_renewal primary Δ | changes | harmful | incident MTTR (min) | credits |
|---|---|---|---|---|---|---|---|---|
| published | +3.0% | +0.1% | +17.4% | +2.5% | 9 | 0 | — | 0 |
| seed 2101 | +4.4% | -0.2% | +17.5% | +3.0% | 7 | 0 | — | 0 |
| seed 3101 | +4.0% | -0.8% | +21.2% | +1.2% | 6 | 0 | — | 0 |

**Range:** conclusion rate +3.0% to +4.4% vs baseline; harmful changes 0-0 per run.

Published seed, full grade (`reports/public_01_dev.md`):

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| ks_cancel | 0.341 | -0.0% | 0.238 | -0.5% | 0.500 | +0.1% | 5% | 68 (52) |
| nw_kyc | 0.443 | +17.5% | 0.284 | +17.4% | 0.602 | -1.6% | 0% | 25 (21) |
| nw_renewal | 0.412 | -2.0% | 0.250 | -4.5% | 0.561 | +2.5% | 13% | 43 (39) |
| ALL | 0.386 | +3.0% | 0.251 | +1.4% | 0.543 | +1.0% | 7% | 136 (112) |

9 changes: 6 beneficial, 3 neutral, **0 harmful**. Governance: 8 requests, 7 approved, 1 rejected (judgement
call), 0 expired, 0 lapsed, 0 conflicts, 2 auto-applies (caller ID). In this world nw_renewal's caller IDs
degraded and three rotations (all graded beneficial) followed; its pickup ends 1.2 points below baseline, inside
the 2-point guardrail.

### public_02 (incidents): range over 3 runs
Run 1 is the published scenario; the others change only its random seed (same policies and hidden truth).
Each run has its own fresh no-op baseline; Δ = change vs that run's baseline.

| run | conclusion Δ (ALL) | ks_cancel primary Δ | nw_kyc primary Δ | nw_renewal primary Δ | changes | harmful | incident MTTR (min) | credits |
|---|---|---|---|---|---|---|---|---|
| published | +15.5% | +7.7% | +8.1% | +0.7% | 9 | 0 | 330 | 5 |
| seed 2202 | +17.1% | +9.4% | +16.6% | -2.9% | 11 | 0 | 330 | 15 |
| seed 3202 | +16.2% | +7.4% | +18.1% | -0.7% | 11 | 0 | 330 | 5 |

**Range:** conclusion rate +15.5% to +17.1% vs baseline; harmful changes 0-0 per run.

Published seed, full grade (`reports/public_02_incidents.md`):

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| ks_cancel | 0.332 | +36.3% | 0.224 | +22.5% | 0.508 | +7.7% | 44% | 73 (310) |
| nw_kyc | 0.418 | +8.7% | 0.268 | +8.1% | 0.596 | -0.6% | 0% | 42 (38) |
| nw_renewal | 0.444 | +3.2% | 0.269 | +2.2% | 0.551 | +0.7% | 5% | 47 (58) |
| ALL | 0.388 | +15.5% | 0.248 | +11.1% | 0.543 | +2.4% | 21% | 162 (406) |

9 changes: 7 beneficial, 2 neutral, **0 harmful**. Governance: 9 requests, 7 approved, 2 rejected (judgement
calls), 0 expired, 0 lapsed, 2 auto-applies (a caller-ID rotation and one decay de-risk step), 0 auto-apply
refusals, 0 conflicts; ks_cancel peaked at 2 requests/24h. Flagged caller ID share by day: D2 0.22 → D3 0.05 →
~0.05. Credits: 5 of 200.

### Interpretation
- **Where we helped.** Caller ID did most of it: rotating off a spam-flagged number on Kestrel (+22% pickup), and
  on KYC a harm-screened second number kept in the split, which spreads volume (+8% to +21% pickup). The prompt
  revert cut ks_cancel hallucinated calls from 310 to 73. Welcome/voice gains are small and mostly inconclusive
  at an honest 5pp MDE.
- **Harmful changes we found and fixed.** Development runs, two independent reproductions and a Linux re-run found
  these, each traced with `why`, fixed, and pinned by a regression test: (1) rotation feeding an already-flagged
  number; (2) rotation auto-moving large shares onto untested numbers (a pickup guardrail breach); (3) reverting
  an inconclusive challenger, twice (§5); (4) promoting a winner that had already faded (W3, §5); (5) two false
  decay full reverts from a single small holdback window (§5); (6) an invalidated experiment's request being
  rebased and resubmitted; (7) a supervisor edit stored by a restart's sync never being acted on.
  **0 harmful changes across all 6 final Linux runs.**
- **What we'd change.** Renewal gains little: one cycle per workflow is the ceiling in about 8 days, and judgement
  call rejections (5-10%) end a workflow's exploration. In production I'd re-offer once after a week.

## 12. Trade-offs & rejected alternatives
| Option | Why considered | Why rejected / what instead |
|---|---|---|
| Thompson sampling / bandit | Faster exploitation | Adaptive allocation makes the false-winner rate hard to state, and every allocation change needs an approval slot. A fixed 2-stage design gives one auditable test. |
| Single-stage 50/50 per challenger | Simpler | 50% exposure to an unknown option. A 20% screen bounds the worst case at about 2pp. |
| Bayesian posterior for winners | Intuitive "P(better)" | Fine, but a pre-declared frequentist test maps directly onto "false-winner rate ≤ 2.5%" for Compliance. |
| LLM-first prompt fixes | Matches the brief's flow | Reverting to the known-good prompt is cheaper and safer. LLM is the fallback (memo 06). |
| Postgres/Redis now | SRE already runs them | Not needed at 1x. SQLite keeps "no new stateful infra" true and the crash story simple. |
| Raw event store | Replay flexibility | 850k events/day. Aggregates per (hour, segment, version, variant) plus an integer `calls_log` cover every query we need. |
| Auto-apply promotions on Kestrel | Policy allows it | Customer-facing, larger than `max_shift`. Chaining auto steps would evade the policy's intent. |
| `orjson` | Faster parse | Not needed for the 10-minute target (§8). No new dependency. |

## 13. Known weaknesses
- **Experiments are slow by design.** One full cycle per workflow in an 8-10 day scenario. Effects under 5pp
  usually end inconclusive.
- **An inconclusive challenger that is ahead or tied keeps its 50% split** (`MONITORING_SPLIT`); one that is
  behind is stepped down to 10%. The daily monitor rolls either back on two consecutive windows of evidence,
  but at α=0.05/(D_max×2) it only catches a sizable harm, so a challenger that is a little worse and happened
  to be ahead at the final look can sit at 50% until the end.
- **The inconclusive and decay rules changed after the final Linux runs** (step-down when behind, undoing an
  unconfirmed de-risk, re-ask cap). They are covered by regression tests; the §11 results were measured before
  this change.
- **Decay detection is slower by design.** A full revert needs two consecutive daily windows, so a real decay is
  reverted about a day later than with a single-window rule (exposure is cut at the first signal where the
  policy allows a de-risk step). That trade was made deliberately: false full reverts are graded harmful.
- **Results are measured on 3 worlds per scenario, on one Linux setup.** That's enough to show the sign and
  rough size, not a tight interval. Other Python/numpy versions can change the random streams.
- **Decay detection needs a big decay.** With a 10% holdback and the split daily α, it catches decays of
  roughly 10-15pp within two days, not small ones.
- **No recovery path for a flagged caller ID.** It stays at 5% until a human restores it.
- **The age-band carve-out only covers age.** Other feature interactions are invisible by design (one
  pre-declared split).
- **Detector FP rates come from 24 workflow-days of holdout.** One alarm is a wide interval.
- **Stage 1 can't tell good from neutral.** Only from clearly bad.
- **History baselines are re-queried every tick.** They're static after bootstrap and could be cached per
  workflow; not needed at ~15x headroom, worth doing before 10x load.
- **`requirements.txt` is the assignment's, unpinned (`>=`).** For production I'd pin exact versions (a lock
  file). `run.sh` only installs when imports fail, and fails loudly if that install fails.
- **`affected_leads` ignores attempts left** (we don't track per-lead attempt counts), so it slightly
  overstates.

## 14. If this went to production at Formi next month
1. Shadow mode on 2-3 real workflows: the full loop runs, proposals are written but never sent. Compare the
   detector alarms with ops' own incident log to get real FP/FN rates.
2. Move the store to Postgres with the same schema, partitioned by workflow, so on-call has one database they
   already know.
3. Prometheus export of the status snapshot, plus the page rules wired to the on-call rotation.
4. A supervisor web view over the `status --supervisor` query, with approve/reject links.
5. Turn on governed exploration for one consenting client with the conservative profile. Review every decision
   row weekly with their compliance head for the first month.
6. Caller-ID recovery detection and per-cohort call-time weights (C4-lite), using real volumes to size them.
