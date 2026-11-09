# Outcome-First Agent Loop: Submission

**Name:** Vikas · **Date:** 2026-11-09 · **Hours actually spent (be honest):** about 3, AI-assisted · **Language / storage:** Python 3.10+, SQLite (WAL), `httpx` + `numpy` only

Runbook for the on-call engineer: [docs/CONTROLLER.md](docs/CONTROLLER.md). Reports: [reports/](reports/).

---

## 0. TL;DR

* A single-process controller ticks every 15 simulated minutes: ingest events into shared per-slice aggregates, detect, experiment, propose through governance, apply, verify, and record why in an append-only decision log.
* Levers: caller-ID rotation and per-person call hour (auto-applied where the policy allows), welcome/voice experiments with per-slice tests and FDR control, winner holdouts with decay rollback, and hallucination incident response.
* Results against the no-op baseline, conclusion rate (leads concluded ÷ uploaded): **public_01 +15.7%, public_02 +32.6%**, public_03 **+21.8%** (12 workflows). The naive example gets +1.2% on public_01. No change was graded harmful on any public scenario. The hallucination incident was fixed in 210 minutes for 3 credits. A modified scenario with different truth and policy (`scenarios/robust_check.yaml`) also ran clean: +33.2%.
* Crash test: 7 kills (3 deterministic points inside the dangerous windows, 3 mid-loop exits, 1 SIGKILL), run finishes, every invariant holds.
* Cut: per-person call time learned from a person's own history, per-tenant credit/attention fairness, a real UI, Postgres. Section 2 says why.

## 1. Assumptions

1. Guardrail drops (`pickup_rate_max_drop: 0.02`) are **absolute** points. I report relative numbers too; one run showed nw_kyc engagement −2.3% relative, which is about 0.014 absolute.
2. Pickup and engagement are never blended. The one headline number I give Sales is leads concluded ÷ leads uploaded, which the README defines as the business outcome.
3. Voice/welcome do not move pickup; caller ID and call time do not move engagement. I inferred this from the contract wording, and use it to route levers to the right KPI (nw_kyc is pickup-primary, so its levers are caller ID and call hour).
4. Person features are stable across campaigns, so person → feature cell can be cached.
5. A person has one preferred hour (contract), so I assign the hour of their first attempt each day; later attempts fall back to the 0.25 weight.
6. Customer-facing = welcome message, voice, prompt (Compliance memo). I send those through human approval even where the policy would let me auto-apply (Kestrel).
7. The hallucination detector's reported recall/FP rates (about 80% / 1%) are as stated in the contract; I take the baseline flag rate from history.
8. One routine proposal per workflow per day is enough; the policy cap minus one slot is reserved for incidents.
9. Scenario horizons are 8–10 days, so I accept that only effects of roughly ≥10% on a reasonably large slice are detectable in time.

## 2. Scope decisions

| # | Capability | Built / Partial / Cut | Why | What it would take to finish |
|---|---|---|---|---|
| C1 | Event ingestion at scale | **Built** | Foundation. Chunk + cursor commit atomically; aggregates only, no raw rows. | Sharded workers + Postgres for 10× (section 8). |
| C2 | Joins + one shared cohort object | **Built** | Cohort = `feature=level` (or `a=x&b=y`), same ID in tests, config, audit and view. | Cohort registry shared across workflows of one tenant. |
| C3 | History bootstrap | **Partial** | History used for hour-of-day pickup profiles, baseline flag rate and KPI baselines. History has only the default variant, so it cannot say which voice is better; that is learned live. | A cross-workflow prior for variants (Product says promotion across clients is later). |
| C4 | Call-time optimisation | **Partial** | Per-person `lead_preferred_hour`, assigned from an (age × tier) profile with a capacity-aware auction. Not learned from the person's own calls. | Per-person posterior from own attempts; measure realised vs predicted gain. |
| C5 | Caller-ID health | **Built** | Multiplicative weights on pickup + even spread (health falls with own load) + fast flag detection + memory so a flagged ID stays down until a probe recovers. | Explore recovery more cleverly. |
| C6 | Welcome × voice experiments | **Built** | Randomised exploration, per-slice tests, BH FDR, per-slice pruning. Interactions between the two dims not modelled (see section 5). | Interaction terms / a logistic model with shrinkage. |
| C7 | Promotion, decay, rollback | **Built** | Winner + control holdout; two decay signals. | Hourly-resolution variant stats for faster decay detection. |
| C8 | Hallucination response | **Built** | Detect → last-known-good (no LLM) → validate → propose with evidence → verify. | Prompt A/B is impossible (one prompt per workflow), so no prompt "improvement" path. |
| C9 | Governance client | **Built** | State machine, batching, approver hours, TTL, stale handling, intent-first idempotency, auto-apply routing. | Per-approver fatigue model. |
| C10 | Honest impact / dry run | **Built** | Numbers from logged aggregates, CI shown; schedule gain is a model estimate and flagged as such. | Calibrate predicted vs realised schedule gain. |
| C11 | Supervisor view | **Partial** | JSON/HTML on :8800 and `reports/supervisor_view.json`. | Real UI. |
| C12 | Audit store | **Built** | `decision` + `proposal` + `cfgchg`; `python -m controller why`. | Per-call retention (see Known weaknesses). |
| C13 | Crash recovery demo | **Built** | `scripts/crash_test.py`. | Run it in CI. |
| C14 | Loop observability | **Partial** | `metric` table, `/health` on the view server, alert table with page/warn/info. | Prometheus export. |
| C15 | Fairness across tenants | **Cut** | Credits are barely used (3 of 200) and approver attention is per workflow; no contention to arbitrate. | A global scheduler once credits or approver time are shared. |

**Principle:** fund the levers whose effect is largest and cheapest to measure first (call time, caller ID: they move pickup for every workflow), keep customer-facing changes slow and evidenced, and spend effort on the things that can hurt a client (governance, incidents, crash safety) before the things that only add lift.

## 3. Stakeholders

### 01 Sales (Nikhil Rao)
* **Accepted:** one headline number per client (concluded ÷ uploaded); speed where the policy allows it: caller-ID and call-hour changes apply the same day without a human.
* **Pushed back:** a single blended score (Product constraint: pickup and engagement stay separate); "winner live for everyone by evening" (voice/welcome need a named approval and a statistical bar); the persuasive prompt (P4 hallucinates at 2.5% vs 0.6%; a workflow has exactly one prompt so it cannot even be A/B tested; validation measures safety only).
* **Wrong claims:** Kestrel's auto-apply is *not* "everything": `ks_cancel` allows schedule, caller_id, welcome_message and voice only, with `max_shift` 0.2, and not prompts or cohorts. Northwind KYC auto-apply is **disabled** in policy (`nw_kyc.auto_apply.enabled=false`); renewal allows only schedule and caller_id.
* **Reply:** "Nikhil: for the summit I can show one number per client: leads concluded ÷ leads uploaded (+16% and +33% on our two test worlds, +22% at load), with pickup and engagement beside it, not blended. Caller-ID and call-time fixes go live the same day. Voice, welcome and script changes need the client's approval, and Northwind KYC has auto-apply switched off in the signed policy. So 'winner by lunch, live by evening' will read as 'winner proven in days, approved in hours'. I won't ship the persuasive prompt: it hallucinates four times as often as today's."

### 02 Compliance (Meera Iyer, Northwind)
* **Accepted:** voice/welcome/script changes only with a named human approval (even where auto-apply would be permitted); script changes carry a validation run id; requests sent only inside approver hours (renewal 10–19, KYC 10–18), never at night; larger control share on Northwind (≥65%) while experimenting.
* **Pushed back:** "no worse for any cohort, even briefly" cannot be promised for any experiment. Every request states the exact exploration share, it is capped, and arms that trail are pruned automatically.
* **Wrong/imprecise:** timing and caller ID are "covered" for renewal only. For `nw_kyc` auto-apply is off, so I also route those through approval.
* **Audit answer within 24h:** `python -m controller why` gives config version, proposal, approver, evidence and rationale for any workflow and time. The per-call variant is in the simulator's event stream (`variant`, `config_version`); we keep decisions and aggregates, not raw calls (Known weaknesses).
* **Reply:** "Meera: customer-facing changes will only go live after a named approval from your team, with validation evidence on any script change, and requests only arrive inside your approver hours. I can't promise that no cohort is ever worse off, even briefly, because testing a different voice means some customers hear it. What I can promise is a cap on that share (at least 65% stays on today's setup for Northwind), automatic withdrawal of an arm that trails, and an answer to 'why did this customer hear that' from our decision log. Note that KYC call-timing changes also go through approval, because auto-apply is off for it."

### 03 Platform/SRE (Kabir Menon)
* **Accepted:** kill/restart test (shown); idempotency everywhere; actionable alerts only; loop health without logs; a load figure.
* **Pushed back:** none on the non-negotiables. On "no new stateful infra": SQLite is a file, not a service, but a recycled node loses it unless it lives on a persistent volume. The store SQL is portable to Postgres, which he already runs; that is the production answer.
* **Reply:** "Kabir: I killed the controller 7 times in one run (3 at the exact points between 'sent' and 'recorded', 3 mid-loop, 1 SIGKILL); it finished with no double apply and no lost approval (reports/crash_recovery.log). One public_03 simulated day ingests in about 5 seconds on this laptop (173k events/s); the per-tick decision time is p50 0.03 s, p99 0.73 s. State is one SQLite file: put it on a persistent volume or tell me and I'll point the same schema at your Postgres. Pages: hallucination spike, no validated fix, failed fix, low credits. Everything else is a ticket."

### 04 Client ops supervisor (Anita Desai, Kestrel)
* **Accepted:** at most 2 requests/day (I send one routine request and keep a slot for incidents), never before 11:00, one request per day carrying every change; her edits are never reverted silently: the controller adopts them as the new baseline and holds those dimensions for 2 days; compliance-script-style prompts (P5) are ranked last when picking a fix; a one-screen view.
* **Pushed back:** "tell me before anything changes on a running campaign". Customer-facing changes do go through her approval. Caller-ID rotation and the daily call-hour assignment cannot wait for a human (a flagged caller ID costs pickup every hour; new leads arrive daily), so they auto-apply under the policy and appear in her view as "changed today".
* **Reply:** "Anita: you'll get at most one request a day, never before 11:00, with everything in it, and a spare slot is kept for a safety fix. Anything the customer hears (opening line, voice, script) waits for your yes. I will never undo your edits quietly. If your prompt starts hallucinating, I'll send you a revert with the evidence and you decide. Two things I do not ask first: which phone number we dial from and which hour we ring a lead, because they can't wait a day. You'll see those under 'changed today'."

### 05 Product (Tara Kulkarni)
* **Accepted:** all definitions: separate KPIs; one cohort object; minimum cohort size and window picked with reasoning (section 5); every proposal carries impact score, diff, affected leads and dry run; an expired or rejected proposal is re-planned from fresh data under a new id; only calls from arms that actually ran count (stats are keyed on each call's recorded variant and start at the apply time); a winner changes only its own workflow.
* **Pushed back:** all three P0s at once. Per-person call time is delivered at cohort-profile quality, not learned per person.
* **Impact score meaning:** expected relative gain on the workflow's primary KPI ÷ 5%, clipped to [0.03, 1]. An experiment start scores 0.03 on purpose (no gain claimed).
* **Reply:** "Tara: pickup and engagement stay separate everywhere; a cohort is one object (`age_band=60+`, same id in tests, config and the view); a proposal's impact score is expected primary-KPI gain over 5%, so a pure exploration request honestly scores near zero. Minimum evidence is 80 effective connected calls per arm per slice, 10% false-discovery rate, 6-day half-life: faster wins, more false winners (section 5). Of your three P0s, caller-ID health and the supervisor view are in; per-person call time is in at cohort-profile quality, not yet learned from each person's own calls."

### 06 CTO (Aryamann)
* **Accepted:** explainability over lift (no change without a recorded reason); no compute without a decision to change (3 of 200 credits used; no LLM call needed because the last-known-good prompt was available); the scale envelope with honest breakpoints (section 8); choosing (section 2); runbook.
* **Wrong claim to check:** none found; his instruction to trust the system's contract is why I read policies from `GET /workflows` rather than from memos.
* **Reply:** "Aryamann: I chose pickup levers first (they help every workflow and are cheap to measure), kept customer-facing changes behind approvals, and cut fairness across tenants and per-person call time. Every change has a decision record with its inputs; credits used: 3 of 200 on public_02, 0 on public_01. First thing to break at 10× is the single-process ingest and the 5 MB preference-map writes, in that order (section 8)."

## 4. Architecture

```
 sim HTTP ──events──▶ Ingestor ──(1 txn per chunk: aggregates + person/cell tables + cursor)──▶ SQLite
    ▲                                                                                              │
    │ apply / PUT / POST approvals / validation                       read-side queries (Learn)    ▼
    │                                                              ┌────────────────────────── Planner ──────────────┐
 Governance (Gov) ◀── proposals ◀── Controller loop (15 min tick) ─┤ caller-ID · call hour · variants/cohorts       │
   state machine, intent-first                                      │ decay · guardrail · impact/dry-run            │
   reconcile on every tick                                          └────────────────────────────────────────────────┘
                                          Incidents (hallucination state machine) ── Audit (decision/proposal/cfgchg) ── View
```

State (all in `controller.db`): `agg_*` sufficient statistics (per day × feature cell × option; hourly for caller ID and prompt flags), `person` (cell, last enrolment day, last conclusion day), `proposal` (request, approver outcome, patch to apply), `decision` (audit), `incident`, `wfstate` (learning state per workflow), `plan_log` (once-per-day idempotency), `alert`, `credit_log`, `metric`.

**Restart:** re-read chunks after the cursor; every proposal not in a terminal state is reconciled against `GET /approvals` / config history; learning state is read from `wfstate`. Nothing waits in memory.

## 5. The learning loop

* **Cohorts.** Cell = (lang, tier, age, value). Tests run on single-feature slices and "all"; cohorts written to config are conjunctions of at most two chosen features, capped at 20 (weakest levels dropped), composites ordered before singles because the first match wins. Traffic is not fragmented: slices are only created for winners or clearly harmful arms.
* **Minimum size and window.** 80 effective connected calls per arm per slice (decay-weighted), half-life 6 days. Cost: a modest 8% lift needs about 3k calls per arm, which is more than a single day of a small workflow; so in an 8-day world only effects ≥10–15% on a large slice are caught. A shorter window reacts faster to decay but halves the effective n.
* **Design.** Welcome and voice are randomised independently per dial, so marginal comparisons per dimension are unbiased. Control share while exploring: 50% (engagement-primary), 85% (pickup-primary: engagement is only a guardrail there), ≥65% on Northwind. Concurrent control only: data starts at the apply time of the experiment (`epoch`).
* **Winner.** One-sided two-proportion test with a 1.15 variance inflation (repeat attempts), Benjamini–Hochberg at q=0.10 over all slice × option tests of a dimension, **and** p≤0.015 on its own (overlapping slices inflate BH ranks), **and** relative lift ≥3%. Deterministic: no randomness, no LLM. Expected false-winner rate ≤10% of promotions; the holdout and decay checks bound the cost of the ones that slip through.
* **Exploitation.** Winner 67%, control holdout 25%, other arms 8%. The holdout makes decay measurable and costs about a quarter of the winner's gain.
* **Pruning.** Arm withdrawn from the whole workflow at z≤−1.65 (n≥100) or from a slice at z≤−2.7.
* **Decay and rollback.** Checked hourly after promotion: (A) winner significantly worse than its holdout in the last 2 days (z≤−1.28); (B) the winner's own rate fell vs its first 2 days (z≤−1.8) and it no longer clearly beats the holdout. I removed an earlier rule ("lift fell well below the promotion estimate") because winner's-curse inflates that estimate and it rolled back a true winner in testing. Typical detection: 1–2 days after decay starts.
* **Two dimensions.** Independent randomisation means each dimension's marginal is unbiased; interaction between a welcome and a voice is not modelled (cut).
* **Call time and caller ID.** Hour profiles come from history, shrunk age×tier → age → global; persons are assigned an hour by an auction that respects hourly capacity. Caller ID: multiplicative weights toward equal pickup, half blended with an even spread over healthy IDs, a raw 3-hour fast view for sudden flags, per-ID memory until a post-flag probe recovers.
* **Guardrail.** Daily check of the guardrail KPI over the last 2 days vs the 7 history days; on a significant breach exploration freezes and a warn alert fires.

## 6. Governance

* **State machine:** `intent → pending → approved → applied`, with `rejected`, `expired`, `lapsed`, `stale`, `void`, `failed`. Terminal proposals are never re-sent: the next plan, from fresh data, creates a new id (`wf.v<base>.<cfg-hash>.a<attempt>`).
* **Batching/timing.** One routine request per workflow per day, in the first tick inside approver hours (not before 11:00 for Kestrel), carrying all changes. Policy cap and client cap (Kestrel 2/day) are honoured; one slot is reserved for incidents. Polling every 15 simulated minutes keeps decisions inside the 2-hour apply window (0 lapses across public runs).
* **Auto-apply** only for dimensions the policy lists (caller_id, schedule), stepped to respect `max_shift`. I voluntarily do not auto-apply welcome/voice/prompt/cohorts even on Kestrel, where the policy would allow welcome/voice.
* **Impact, affected leads, dry run.** Affected leads = active (enrolled within the cadence window, not concluded) persons in the affected slices. Dry run = the logged per-slice rates, CI and traffic share behind each promotion. Schedule gain is a model estimate (profile-based) and is labelled so; measured gain was about half of it on public_01.
* **Supervisor edits.** Recorded as a decision, never reverted, dims put on hold for 2 days, the edited default becomes the new control (prunes learned about clearly bad arms are kept, exploration restarts gently at ≥70% control). An approval made stale by an edit is detected at apply time (409) and re-planned.

## 7. Incidents

* **Detection:** ≥120 connected calls on the current prompt, one-sided binomial z≥3.6 against the history flag rate, rate ≥ max(2×baseline, baseline+1pt), confirmed twice ≥30 min apart. Expected false positives ≈0.1–0.3% per workflow-day; a false alarm costs 3 credits and one reversible, validated proposal.
* **Fix:** the last prompt that ran cleanly in our data (no LLM); validated with n=300 (3 credits) against the policy threshold; LLM suggestions only if there is no such prompt, then validate each; "verbatim/strict" candidates ranked last.
* **Verify:** ≥120 connected calls after apply; flag rate back inside the normal range (z<2.5) or the incident fails and pages.
* **public_02 timeline (ks_cancel, D3):** 11:30 supervisor ships P2 (flag rate about 5%); 13:15 detected (n=208, z=5.0); 13:15 P1 validated at 0.987 and proposed; 14:30 applied after approval; 16:30 verified (1.6%, n=126). **Time to fix about 3.5 h (210 min), 3 credits;** most of it is the approver's latency. The caller-ID flag (D2 10:00): the flagged ID's share went 17% on that day to 2% from the next day on.

## 8. Scale

Measured on public_03 (12 workflows, about 650k dials/day, 4-vCPU-class laptop, simulator running on the same machine): 

| metric | value |
|---|---|
| events ingested (7 history days + 5 days) | 9.74M in 56.3 s = **173k events/s** (fetch + parse + aggregate + SQLite commit) |
| one simulated day (about 850k events) | about 5 s to ingest |
| decision time per 15-min tick, all 12 workflows | p50 0.03 s, p99 0.73 s, max 1.6 s (the 08:15 call-hour assignment) |
| peak RSS | 995 MB |
| wall-clock, 5 simulated days incl. the simulator | about 6 min, far under the 10 min/day target |
| outcome | conclusion +21.8%, pickup +13.7%, engagement +4.9%; 114 changes, 0 harmful |

Ingest rate swung between 15k and 185k events/s across runs depending on what else was using the machine, so treat it as "tens to a couple of hundred thousand per second", and quote the high end only on an idle box. One workflow (`nort_kyc_1`) gained only +1.0% because three consecutive random "judgement call" rejections (15% each) delayed its first change to day 3; the controller re-planned each time and never resent a rejected request.


Breaks first at 10×: (1) single-process ingest (JSON parse + SQLite upserts are CPU-bound on one core): shard by workflow hash across processes; (2) the per-person preference map is up to 200k entries per workflow, re-PUT daily (5 MB bodies × hundreds of workflows) and re-read by the simulator on every version; send deltas or cap to the highest-value persons; (3) SQLite single writer: move to Postgres per shard; (4) person arrays in RAM (about 2 bytes×3 per person) are fine until hundreds of millions of persons. Partition by tenant then workflow; approvals are per workflow so nothing is shared.

## 9. Reliability

* **Method:** `scripts/crash_test.py`: 3 deterministic crashes in the windows after an approval POST, after an apply, and after an auto-apply PUT (before they are recorded), 3 hard exits mid-loop, SIGKILLs at random times; restart each time; then check against the simulator: finished; every simulator approval has exactly one proposal row; no approval or auto-proposal applied twice; our "applied" equals the simulator's; nothing stuck in a non-terminal state that the simulator has closed. Output: `reports/crash_recovery.log`.
* **What is lost:** at most one validation run (3 credits) if killed between the POST and the bookkeeping.
* **Idempotency keys:** proposal id from (workflow, base version, config hash, attempt); chunk cursor in the same transaction as its aggregates; `plan_log (workflow, day, slot)`.
* **Bugs this found:** `_recover_intent` was missing (crash loop); a failed ingest transaction retried in-process would lose newly created cells (unit test). Both fixed.
* **API errors:** transport errors and 5xx retry with backoff; 409 stale → mark stale, re-plan; 410 lapsed → alert; 403 on auto-apply → logged, alert; 402 never reached (credits are checked first).

## 10. Audit & observability

```
$ python -m controller why --db runs/controller.db --wf ks_cancel --at "D3 19:00"
ks_cancel config v16 was in force at D3 19:00; it was set at D3 14:30 by actor 'controller_approved', changing ['prompt_version'].
  PROPOSAL ks_cancel.v15.…: "Safety fix: switch prompt P2 -> P1 (hallucination flags 5.8% vs 1.5% normal)"
  RATIONALE: 12 of 208 connected calls on P2 were flagged … P1 passed a validation run at 0.9867 (needs >= 0.97) …
  GOVERNANCE: requested D3 13:15, approver decision D3 14:19 (approval apr_000xx), applied D3 14:30; impact_score=0.9 …
  DECISION RECORD #… [incident_proposal] … inputs: {…}
  WHAT HAPPENED NEXT: D3 16:30 [incident_verified] flag rate after fix 1.6% (n=126) …
  KPIs 2 days before / after …
```
(The exact output is reproducible from `runs/ctl_public_02_incidents.db`.) **Page on:** hallucination spike, no validated fix, failed fix, credits low during an incident. **Ticket, not page:** guardrail breach, lapsed approval, supervisor edits, degraded caller ID.

## 11. Results

Paste of `reports/public_01_dev.md` and `reports/public_02_incidents.md` summary tables.

**public_01_dev** (39 changes: 29 neutral, 10 beneficial, 0 harmful)

| workflow | conclusion | Δ | pickup Δ | engagement Δ | gap captured |
|---|---|---|---|---|---|
| ks_cancel | 0.391 | +14.5% | +12.7% | +1.1% | 10% |
| nw_kyc | 0.450 | +22.8% | +20.2% | −0.1% | 13% |
| nw_renewal | 0.471 | +13.1% | +8.9% | +2.1% | 13% |
| **ALL** | 0.430 | **+15.7%** | +12.7% | +1.4% | 12% |

**public_02_incidents** (55 changes: 38 neutral, 17 beneficial, 0 harmful; MTTR 210 min; 3 credits)

| workflow | conclusion | Δ | pickup Δ | engagement Δ | gap captured |
|---|---|---|---|---|---|
| ks_cancel | 0.387 | +64.4% | +43.8% | +8.8% | 49% |
| nw_kyc | 0.447 | +19.5% | +22.2% | −3.0% | 0% |
| nw_renewal | 0.503 | +16.2% | +14.9% | +0.3% | 16% |
| **ALL** | 0.438 | **+32.6%** | +27.4% | +1.9% | 33% |

**Robustness check** (`scenarios/robust_check.yaml`, written by me, not graded; different seed, 6 languages, a primary-KPI flip on Kestrel, different approver hours, auto-apply of prompts enabled on KYC, a different flagged ID and decaying variant, a persuasive-prompt edit): ran with no errors, +33.2% conclusion, 54 changes, 1 graded harmful. That one is the intended safety revert of the supervisor's persuasive prompt P4: P4 is more engaging but hallucinates, so fixing it costs about 4.7% expected engagement. It is a deliberate trade-off, not a bug. Its MTTR of 1425 min is dominated by approver hours (the fix was proposed within 5 h of the edit, after hours the decision waited for 10:00).

**Interpretation.** Most of the lift is pickup (call hour and caller ID), which is detectable fast; engagement lift is small because 8–10 days limit how much a per-slice test can find. Hallucinated calls on ks_cancel fell from 348 (baseline) to about 110. Where I lost ground: nw_kyc engagement (−3.0% relative) is mostly sampling noise (expected engagement from the configs was within about 1% of baseline; about 450–680 connected calls a day gives ±2% daily standard error); the real cost is the 15% W2 exploration. nw_renewal public_02 gave back engagement during the first days of exploration (W3 decays, V4 hurts) before pruning. Earlier iterations had harmful changes (a caller-ID blend that re-explored a spam-flagged ID; a decay rule that rolled back a true winner); both were fixed, and the final runs have none. Results vary run to run because the simulator's RNG stream depends on when configs change: treat ±3 points as noise.

## 12. Trade-offs & rejected alternatives

| Option | Why considered | Why rejected / what instead |
|---|---|---|
| Bandit (Thompson) for variants | Efficient exploration | Needs randomness in the decision; the brief wants a deterministic, auditable winner. Fixed shares + tests instead. |
| Hierarchical model across slices | More power for small slices | Time; the per-slice test with FDR is explainable to a compliance head. |
| Cohort hour tables | Natural schedule lever | Needs the `cohorts` dim, which no auto-apply policy allows; and a table shared by all leads has no effect. Per-person preferred hour is allowed under `schedule`. |
| LLM to pick the incident fix | Spend credits | Last-known-good is free and has observed engagement. |
| Re-sending an expired proposal | Simple | Product: expired = rejection, re-plan on fresh data. |
| Postgres/Redis | SRE already runs them | More to set up for a take-home; SQL kept portable. |

## 13. Known weaknesses

* Power: slice-level effects below about 15% are mostly not found in 8 days; the engagement lift is modest.
* Predicted schedule gain is roughly 2× the realised gain (only the first attempt of the day lands on the preferred hour).
* No per-call retention in our store; a per-customer audit needs the event archive joined with our `config_version` decisions.
* Exploration costs engagement early on (nw_renewal public_02); the Northwind cap (≥65% control) trades speed for caution.
* SQLite on one node; single-process loop.
* Fixing an unsafe prompt that was also more engaging costs engagement (graded harmful in `robust_check`): the controller prefers safety, and picks the last observed-clean prompt, not an unseen one that might engage better.
* Promotion needs a stability check on the last ~36 h, which is skipped when recent data is too thin; on pickup-primary workflows I demand p≤0.004 instead of 0.015 for that reason.
* Decay detection works at day resolution for slice variants, so a slice winner can overstay by about a day.
* Cohort design handles two features per cohort scheme; a hidden world with effects depending on three features at once is not captured.
* A second supervisor edit during a hold restarts the hold; no cap on how long a dimension can be held.

## 14. If this went to production at Formi next month

1. Week 1: move the store to your Postgres, run the loop in shadow mode (propose, do not apply) on 2–3 workflows, and compare predicted vs realised gains.
2. Calibrate the schedule gain estimate; add per-person posterior hours for returning leads.
3. Retain call-level (lead, ts, config_version, variant) in compressed partitions for the 24h audit SLA.
4. Prometheus metrics + alert routing for the page/warn table; test the crash script in CI.
5. Shard workers by workflow; load-test at 10× with the preference-map deltas.
6. Per-tenant knobs (exploration cap, quiet hours) in config instead of code; weekly summary email from the decision log for Northwind.
7. Only then widen to auto-promote across workflows of one tenant.
