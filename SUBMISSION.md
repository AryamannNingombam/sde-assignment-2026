# Outcome-First Agent Loop — Submission

**Name:** _fill in_ · **Date:** _fill in_ · **Hours actually spent (be honest):** _fill in_ · **Language / storage:** Python 3.11, SQLite (one file, WAL)

---

## 0. TL;DR

A single-process controller that detects drift, bad caller IDs and hallucination spikes, runs factorial experiments with sequential stopping, and sends batched proposals through governance. It keeps a holdout to catch decay and answers "why did this change" from its own store.
public_01: conclusion rate **+7.9%**, 1 harmful change of 16. public_02: **+12.7%**, 2 harmful of 17, hallucinated calls **197 vs 416**. public_03: **+18.0%**, 0 harmful of 46, slowest simulated day 172 s.
Survived 9 SIGKILLs with all integrity checks passing, 0 lapsed approvals.
Deliberately not built: call-time optimisation (C4) and cross-tenant fairness (C15).

## 1. Assumptions

1. Guardrails such as `pickup_rate_max_drop: 0.02` are absolute rate points, not relative. The docs don't say. Absolute is the only reading measurable at this traffic.
2. `approver_hours` are IST, matching the dialling window.
3. Approver latency may run past close of business, so routine requests are sent early enough for an average-latency decision the same day.
4. Welcome message and voice cannot change whether someone picks up, because they are heard after pickup. So pickup-primary workflows (KYC) only experiment on caller ID. The guardrail is still measured on every winner, so this assumption can't hide harm.
5. A "named human approval" (memo 02) is satisfied in the simulator by an approval id. The API exposes no name.
6. A controller-created cohort id starting `c_` is ours. Any other id was made by a supervisor and keeps precedence.
7. Memo 04's limits apply to Kestrel's cancellation line, which is the line its author runs, not all of Kestrel.
8. Credits are per-scenario, and only incidents should spend them.
9. A simulator restart is a new world: the old database is set aside and not resumed.

## 2. Scope decisions

| # | Capability | Status | Why | What it would take to finish |
|---|---|---|---|---|
| C1 | Event ingestion | Built | Everything is only as fresh as this | Partitioning at 10× (§8) |
| C2 | Shared cohort object | Built | Memo 05, and cheap if done first | — |
| C3 | Bootstrap from history | Built | Baselines for every detector come from it | Variant effects are not in history, so nothing more to extract |
| C4 | Call-time optimisation | **Cut** | Largest remaining lift, but a second learning system to defend | About 2 days: per-cohort hourly pickup model plus experiments on `hour_weights` |
| C5 | Caller-ID health | Built | Directly affects pickup and auto-apply is permitted | Recovery probing (§13) |
| C6 | Variant experiments | Built | Core of the loop | Follow-up rounds on cohorts |
| C7 | Promotion, decay, rollback | Built | "Back out when it stops working" | — |
| C8 | Hallucination response | Built | Regulated-client incident path | — |
| C9 | Governance client | Built | Absolute constraint | — |
| C10 | Impact, affected leads, dry run | Built | Memo 05: a product surface | Calibrating impact against realised outcomes |
| C11 | Supervisor view | Partial | CLI one-screen view per workflow, no UI | A web page over the same query, about half a day |
| C12 | Audit store | Built | Floor, and the live review | — |
| C13 | Crash recovery | Built | Non-negotiable | — |
| C14 | Loop observability | Partial | `health` CLI and alert table, no paging integration | Wire `alerts` to the pager |
| C15 | Fair allocation across tenants | **Cut** | Credits barely spent (5 of 200), so there was no contention to allocate | Per-tenant credit and approver budgets |

**Principle.** I built what is required for a change to be safe and explainable first, then what produces lift with the least new surface. A wrong, unexplainable change costs more in this market than a missed lift. C4 is the cut that costs the most outcome, and I would do it next.

## 3. Stakeholders

### 01 — Nikhil Rao, Sales
**Accepted:** a per-client lift number, reported separately for pickup and engagement. Batching, so supervisors get at most one or two requests a day (peak was 2 per 24h).
**Declined:** a blended score (constraint 3). "Live by evening" for a variant winning at lunch: at 300 dials/hour a lunchtime lead is mostly noise, and approvers can take up to 8 hours on KYC. Rolling out the Persuasive prompt: prompt changes need validation evidence, and another account's demo is not that.
**Wrong against policy:**
- "Kestrel has auto-apply for everything." `ks_cancel` allows schedule, caller ID, welcome and voice, capped at a 0.2 shift, and never prompts. On public_03, Kestrel's renewal allows only schedule and caller ID, and its KYC has auto-apply off.
- "Northwind is fine with auto-apply on KYC." `nw_kyc` has `auto_apply.enabled: false`, and Northwind's compliance head requires named human approval.
- P4 "wherever available" isn't everywhere: `nw_kyc` doesn't offer it.

> **Reply:** Nikhil, you'll have a per-client number for the summit: pickup and engagement shown separately, because our product definition doesn't allow blending them. "Improved itself overnight" isn't quite true. Northwind's KYC has auto-apply switched off, and Kestrel's excludes prompts and caps shifts, so winners go through their approvers. On the load scenario conclusion rate rose 18% with no harmful changes, and that's the claim I'd put on stage. I won't roll out Persuasive without validation evidence. Happy to review the slide.

### 02 — Meera Iyer, Compliance, Northwind
**Accepted:** every customer-facing change goes to a human, even where policy would allow auto-apply. Prompt changes carry a validation run id. `why-call` answers what a customer heard and why, down to variant and approval. Requests are only sent inside approver hours.
**Declined / gap:** the weekly summary isn't built, though the audit data for it exists. "Even briefly worse for a cohort" can't be guaranteed by any experiment, so instead exposure is capped: control keeps 50%, clearly worse arms stop early, and cohorts a winner would hurt stay on control.
**Wrong against policy:** the memo treats call timing and caller-ID latitude as covering both workflows. That's true for `nw_renewal`, but `nw_kyc` has auto-apply off, so even caller-ID changes there go to a human. Approver hours in the memo do match the policy.

> **Reply:** Meera, your conditions are built in. Nothing a customer hears changes without an approval, script changes carry validation evidence, and we can show what any customer heard on any day and why it was live, well inside 24 hours. Two honest limits. On KYC, your policy has automatic changes off entirely, so caller-ID moves come to your approvers too. And no experiment can promise zero downside, so we cap it: half of calls stay on your current setup and clearly worse options stop early. The weekly summary isn't built yet. It's next.

### 03 — Kabir Menon, Platform & SRE
**Accepted:** kill/restart test (9 SIGKILLs, §9). Idempotency on every write. Alerts carry the next action. `health` shows ingest, decisions and credit burn without logs. One simulated day on load took at most 172 s against a 600 s limit.
**Pushed back:** SQLite is a file, so no new service to operate, but production should move to the Postgres you already run, and the SQL is written to make that a port. The numbers came from a 12-core laptop, not 4 vCPU / 8 GB.
**Wrong:** nothing false in the memo.

> **Reply:** Kabir, kill test: 9 SIGKILLs during a full run, no double applies, no lost approvals, and every event counted exactly once against an independent recount. Slowest load day was 172 s against your 600 s. Caveat: that's a 12-core laptop with the simulator alongside, and I haven't run it on 4 vCPU yet. No new infrastructure: state is one SQLite file, and in production I'd port it to your Postgres. Pages name what to look at. First thing to break at 10× is the single decision process, and the fix is partitioning by tenant.

### 04 — Anita Desai, Operations, Kestrel
**Accepted:** two requests a day and nothing before 11:00, tighter than the policy's four. Her edits stand: a supervisor edit stops any experiment on that dimension and is never overwritten. One screen (`view`). Fixes are checked for engagement after applying, so a word-for-word script that nobody stays on fails verification.
**Pushed back:** an active hallucination incident may be sent before 11:00, still within the cap and still needing a human yes. "Tell me before anything changes": caller-ID moves auto-apply when a number goes bad, because waiting costs pickup, and they show in `view` afterwards.
**Wrong against policy:** nothing false. Her limits are simply narrower than what's signed.

> **Reply:** Anita, your changes stand, and if you edit something we're testing, we stop that test. You'll get at most two requests a day, none before 11:00, with everything batched. Two exceptions, so you can object. A live hallucination problem can reach you before 11:00, though it still needs your yes. And if a caller ID goes bad, we move calls off it straight away and show it on your screen after. After any script fix we check people still stay on the call, so the word-for-word problem gets caught. Your one screen is ready.

### 05 — Tara Kulkarni, Product
**Accepted:** separate KPIs. One cohort object and id. Every proposal has impact, diff, affected leads and dry run. Expired counts as rejected. Winners are per-workflow only. Unapproved arms record `never_ran`, and arms absent from a stratum contribute nothing.
**Answered your open question:** minimum 200 connected per arm for a cohort or a winner, and at least 5% of leads. Cost: on a 1,100-lead workflow, subgroup effects under roughly 20% stay invisible during the run. Lowering it would surface more cohorts and more false ones.
**Declined:** per-person call time, your headline P0. Three P0s plus the governance floor didn't fit. Caller-ID health and a thin consolidated view shipped.
**Wrong:** nothing false. Calling everything P0 is the trade-off the memo itself concedes.

> **Reply:** Tara, your definitions are held in code. Minimum cohort is 200 connected calls per arm and 5% of leads, evaluated daily, with about 2.4% false winners measured on A/A data. The cost is that smaller subgroup effects stay invisible. Your three P0s: caller-ID health shipped, the supervisor view shipped as a command-line screen, and per-person call time did not. It's a separate learning system, and I chose to make the governance path trustworthy first. It's what I'd build next, starting per cohort. So it won't be the summit headline.

### 06 — Aryamann, CTO
**Accepted:** explainable before impressive. Credits spent only where they change a decision: 5 credits on public_02, because the free known-good prompt was tried before any LLM call. Choosing, in §2. Runbook for whoever is paged. Honest limits in §13.
**Wrong:** nothing false, and your warning about the other memos was accurate.

> **Reply:** Aryamann, I built the loop end to end and cut call-time optimisation and cross-tenant fairness. Sales and Product will each have a reason to be unhappy, and I've drafted those replies. Honest position: 0 harmful of 46 on load, but 1 and 2 harmful on the two smaller scenarios, all from returning to the default when nothing proved better. What breaks first at scale is the single decision process. Not yet run on the 4 vCPU target. I'd trust it with a supervised pilot on one workflow, not hundreds, until impact scores are calibrated against reality.

## 4. Architecture

```
   simulator HTTP
        |  chunks (NDJSON, streamed)
        v
  +-----------+  one transaction per chunk   +----------------------------------+
  |  Ingestor | ---------------------------> |  SQLite: rollups, leads, cursor  |
  +-----------+                              |  experiments, promotions,        |
                                             |  incidents, intents, proposals,  |
  every 15 sim minutes, per workflow:        |  config_versions, decisions      |
  sync config -> poll proposals -> detect    +----------------------------------+
        -> daily review -> flush                   ^                    ^
        |                                          |                    |
        v                                    all decisions        read-only CLI:
  +-------------+  intents (data-only ops)         |            why, why-call, view, health
  | Governance  | ---------------------------------+
  +-------------+
        |  POST /approvals, POST /apply, PUT /config (caller ID only)
        v
   simulator HTTP
```

All state is in `state/controller.db`, plus gzipped raw events in `state/events/` for per-call audit. In memory there is only the lead-to-segment join for live campaigns and a few caches, all rebuilt from the database on start. On restart: ingest whatever isn't committed, then `poll` asks the simulator what happened to each open proposal.

## 5. The learning loop

**Cohorts.** One `Cohort` class, its id derived from its predicate. Experiments run on `default`, then one- and two-feature slices are scanned when an experiment ends. Three-way slices would fragment below minimum size. A slice needs 200 connected per arm and 5% of leads, at most 4 new cohorts per workflow.

**Experiment design.** Welcome and voice are sampled independently per call, so one allocation is a full factorial and both dimensions run at once at no sample cost. Control keeps 50%, the rest splits evenly. I gave up test power relative to a square-root-k allocation in order to limit exposure (memo 02). Interactions aren't tested directly: main effects are marginal over the other factor, which randomisation makes unbiased.

**Deciding a winner.** Arm versus control, risk difference stratified by (day, config version, prompt). One look per day, O'Brien-Fleming alpha spending, Holm across arms, family alpha 0.05. Information is the larger of sample fraction and calendar fraction, with experiments capped at min(5 days, half the horizon). A winner also needs 200 observations and a lift that didn't collapse inside the test.
**False-winner rate, measured:** 2.3–2.4% (±0.5%) on 3,000 A/A experiments per configuration (`reports/false_winner_rate.md`), which is the upper tail of a 5% two-sided budget. It uses the production functions. It doesn't model correlation between attempts on the same lead, so the true rate is somewhat higher.
Subgroups use Benjamini-Hochberg at q=0.05, an exploratory standard, and that rate isn't measured.

A conclusion that doesn't get applied (rejected, expired or stale) is re-tested on all the data before re-sending. This fixed a real bug where evidence from D4 promoted a decayed variant on D7.

**Decay and rollback.** After promotion, 15% stays on the old control. Each day: winner against control over 3 days. Rollback if credibly worse than control, or credibly below half the promotion lift and below a quarter of it in point estimate. A 15% holdout alone is underpowered, so control's 21-day pooled rate is used when the concurrent holdout agrees with it, and ignored when it doesn't. **Noticing is slow, about 3–4 days:** on public_01 W3 was promoted on D3, as its decay began, and rolled back on D7. On public_02 it left traffic on day 6 after the decay began. The daily look and the 3-day window set that speed. A shorter window would catch decay sooner and false-alarm more.

**Call time and caller ID.** Call time is cut (§2). Caller IDs: unused numbers get 5% each. Quarantine compares a number to concurrent peers over 6 hours (z≥4 and pickup ≤70% of peers), or to its own history at the same hours if it is the only number.

**Guardrail.** Every winner has the guardrail KPI tested: blocked if P(true drop exceeds limit) > 20%. When noise is wider than the limit that probability is high for any arm, so it judges on the point estimate instead. Slice winners are tested too, and a cohort that a global winner would hurt stays on control.

## 6. Governance

```
intent queued --flush--> drafted --POST--> pending --> approved --> applying --> applied
                            |                 |            |            |
                            v                 v            |            v
                       stale/invalid   rejected/expired    |       stale/lapsed
                            |                 |            |            |
                            +--------+--------+------------+------------+
                                     v
                 routine: requeued, rebuilt on the live config
                 promotions: re-tested on all data first
```

**Batching and timing.** One open routine request per workflow, everything queued goes in one request. Routine sends are limited to approver hours (and 11:00 for Kestrel cancellation), leaving time for an average-latency decision. One request in every 24h is reserved for incidents. Approved changes apply within the next tick, comfortably inside the 2-hour apply window. Across all three scenarios: 0 lapsed, 0 expired, 0 fatigue rejections. Stale proposals are expected after supervisor edits and were all re-proposed.

**Auto-apply.** Only caller ID, even where policy permits voice or welcome (memos 02 and 04). A move larger than `max_shift` takes one capped step, and the rest goes to a human: chaining steps would evade the limit. A write that could report any other dimension as changed is routed to a human.

**Impact, affected leads, dry run.** Impact = 1 − exp(−value ÷ 5% of daily connected) × confidence, where value is engaged calls gained per day. One scale across kinds, so the queue ranks sensibly. **The value inputs are estimates and impact isn't calibrated against realised outcomes.** Affected leads is the leads with attempts remaining, weighted by how much of their traffic changes. Dry run replays the last 7 days of real calls; arms never observed are listed and excluded.

**Supervisor edit mid-experiment.** The edit stands. An edit to a tested dimension or to cohorts ends that experiment and cancels its intents. Other edits leave it running, since strata isolate them. Pending proposals go stale at apply and are rebuilt on the supervisor's config.

## 7. Incidents

**Hallucination detection.** Rolling 3 hours for the live prompt, at least 100 QA calls, rate ≥2× baseline and ≥1 point above it, and exact binomial tail p < 1e-6. The first version used a normal approximation, and at about 4 expected flags that understates the tail by orders of magnitude: it opened a false incident on public_01. After the fix there were 0 incidents on public_01 and public_03. Per-look false-positive rate is below 1e-6, and looks overlap heavily, so I expect a few per year platform-wide.

**Picking a fix.** First a known-good prompt: at least 500 real calls here and a clean record, re-validated for 5 credits. Engagement on it has actually been observed. Only if none passes does the LLM nominate candidates, and validation decides among them. Spend is capped at 40 credits per incident.

**Verifying.** After 200 QA calls on the new prompt: flags back near baseline and engagement within 15% of pre-incident. Otherwise that prompt is marked failed and the incident goes back to selection.

**Timeline from public_02** (ks_cancel):

| Time | Event |
|---|---|
| D2 10:00 | Caller ID D2 degrades (simulator injects) |
| D2 11:15 | Detected, pickup 57% of normal. First capped step auto-applied (limit 0.2) |
| D3 11:00 | Remainder sent to approver |
| D3 11:45 | Supervisor ships P2 (v5). That proposal becomes stale at apply and is rebuilt |
| D3 16:15 | Incident: 6.2% flagged vs 1.4% baseline over 258 calls. P1 validated at 0.986 (5 credits). Sent with the caller-ID remainder in one request |
| D3 18:00 | Approved and applied |
| D3 21:00 | Verified: flags 1.0%, engagement 52.5%. Closed |

MTTR 390 minutes, and most of that was detection. The strict exact test waited for enough evidence, the direct cost of removing false alarms. Flagged-number share was 31% on D2, 21% on D3 and 0 from D4. Hallucinated calls on this workflow: 109 against 330 at baseline.

## 8. Scale

Measured on public_03_load, 12 workflows, full report in `reports/public_03_load.md`. **Machine: 12-logical-core, 15 GB Windows 11 laptop, simulator on the same machine, not the 4 vCPU / 8 GB Linux target.**

| Metric | Value |
|---|---|
| Ingest throughput | 33,255 events/s during arrival; 70,238 on bootstrap |
| Bootstrap | 5.54M events in 79 s |
| Decide per tick (12 workflows) | median 685 ms, p99 1,358 ms |
| Ingest per tick | median 294 ms, p99 3,312 ms |
| Decision lag | at most one 15-minute tick, plus a few seconds |
| Peak memory | 272 MB |
| Wall-clock per simulated day | 71–172 s, including the simulator (limit: 600 s) |
| Database at finish | 140 MB, plus 106 MB of gzipped events |

**At 10× (extrapolated, not measured).** Ingest stays within real time: about 8.4M events/day at ~33k/s is 4–5 minutes. Memory grows to about 2.7 GB, inside 8 GB. **What breaks first is the single decision process.** Decide took 29–101 s per simulated day, so roughly 5–17 minutes at 10×, over the 10-minute target. Decide time varied by day (D3 was about 3.5× D0) and I didn't profile why. Then SQLite's single writer.
**Partitioning:** all state is keyed by workflow and nothing is shared across tenants, so run N worker processes hash-partitioned by tenant, one database each, or Postgres with row-level ownership.

## 9. Reliability

**Crash test** (`scripts/crash_test.py`, output in `reports/crash_recovery.log`): full public_02 run, killed with SIGKILL/TerminateProcess at seeded random times, 9 kills, restarted each time. Checked against the simulator's API and an independent recount of the event stream:

```
[PASS] scenario ran to the end: minute 14400
[PASS] no proposal was applied twice: 17 applied, duplicates: []
[PASS] no approval was lost: 15 approvals, missing: []
[PASS] every applied change is recorded as applied in our store: 17
[PASS] nothing is recorded as applied that did not happen: 0
[PASS] no proposal is left half-done: 0
[PASS] every event ingested exactly once: stream 324338, store 324338
[PASS] rollups match an independent recount: dials 245032, connected 62237, engaged 33613
[PASS] our store knows the final config version of every workflow
[PASS] learning survived the restarts: {'concluded': 6, 'invalidated': 1}
```

Random kills rarely land between a write and its record, so those windows have deterministic tests in `tests/test_decisions.py` (crash after draft, after POST, after apply, during auto-apply).

**What is lost:** an LLM or validation call whose response didn't reach the database is paid for again, at most one call per crash. Nothing else.

**Idempotency.** `proposal_id` is derived from the content and attempt number. Each intent row commits before its HTTP call. `apply` returning "already applied" is treated as success, with the version read from config history. Chunks commit atomically with the cursor.

**Simulator errors.** 5xx and transport errors retry with backoff. `advance` has no idempotency key, so before retrying it checks where the simulator actually is. 409 stale: rebuild on the live config. 409 duplicate: adopt the existing approval. 410 or lapsed: rejection path. 403 or 422: audited as rejected or invalid, not retried unchanged. Repeated failure exits, and `run.sh` restarts it.

## 10. Audit & observability

`python -m controller why --workflow ks_cancel --at "D3 18:00"`, real output, trimmed:

```
# ks_cancel: config v6 at 2027-01-07T18:00:00+05:30
Changed by: controller_approved
Dimensions: caller_id, prompt_version

## Why
Move prompt from P2 to P1: hallucination flags at 6.2%, normal is 1.4%; finish moving traffic off a caller ID

Rationale: 258 recent calls flagged at 6.2% (exact binomial p=7.7e-07). P1 (known_good) passed validation at
0.986 on 500 conversations. Validation measures safety only, so engagement is verified live after applying.
Impact score: 0.8928  Affected leads: 4566

## Who approved it
Approval apr_00008, requested 2027-01-07T16:15:00+05:30, decided 2027-01-07T18:00:00+05:30.
The simulator's API does not expose the approver's name, so the approval id is the identifier we hold.
```

The command then prints the diff, the dry run, KPIs before and after, and the next 24 hours of decisions. `why-call --lead <id>` gives each call's variant and why it was live.

**Page on:** an incident with no applicable fix; credits too low to fix an incident. Also, once wired up: repeated restarts and ingest stalls.
**Don't page on:** KPI drift (often our own promotion), request budget exhausted, a single rejected proposal, one process restart. Those are tickets or nothing.

## 11. Results

**public_01** (`reports/public_01.md`)

| workflow | conclusion | Δ | pickup | Δ | engagement | Δ | gap captured |
|---|---|---|---|---|---|---|---|
| ks_cancel | 0.352 | +5.7% | 0.249 | +4.5% | 0.495 | +0.9% | 0% |
| nw_kyc | 0.430 | +18.3% | 0.280 | +15.8% | 0.597 | +1.1% | 0% |
| nw_renewal | 0.439 | +4.5% | 0.268 | +1.8% | 0.562 | +3.0% | 14% |
| ALL | 0.397 | +7.9% | 0.262 | +5.6% | 0.540 | +1.9% | 5% |

16 changes: 7 beneficial, 8 neutral, 1 harmful. 12 requests, all approved. No false incidents, 0 credits.

**public_02** (`reports/public_02.md`)

| workflow | conclusion | Δ | pickup | Δ | engagement | Δ | gap captured | hallucinated (base) |
|---|---|---|---|---|---|---|---|---|
| ks_cancel | 0.326 | +31.5% | 0.222 | +20.9% | 0.503 | +5.6% | 37% | 109 (330) |
| nw_kyc | 0.388 | +3.5% | 0.252 | +4.0% | 0.589 | −0.6% | 0% | 33 (31) |
| nw_renewal | 0.439 | +3.0% | 0.266 | +1.6% | 0.552 | +0.8% | 15% | 55 (55) |
| ALL | 0.377 | +12.7% | 0.243 | +9.5% | 0.539 | +1.7% | 25% | 197 (416) |

17 changes: 10 beneficial, 5 neutral, 2 harmful. 13 approved, 2 rejected, 2 stale re-proposals, 0 lapsed. 5 credits.

**public_03** (`reports/public_03_grade.md`): ALL conclusion +18.0%, pickup +9.9%, engagement +5.1%. 46 changes, 23 beneficial, 23 neutral, 0 harmful. 12 winners, 2 rollbacks, 0 lapsed.

**Interpretation.** Most lift comes from caller-ID work, and most of the engagement gap remains: 5–25% captured. Experiments take days, one round per dimension. Results vary between runs of the same scenario, because approver randomness depends on call order: ks_cancel on public_01 ranged from +5.7% to +12.1% across three runs while the code was changing.

**Where I was harmful.** All three harmful changes (public_01 ks_cancel voice, public_02 ks_cancel caller ID and nw_kyc caller ID) are the same decision: a trial ended with no proven winner, so traffic returned to the known default, and truth says the unproven mix was slightly better. I chose this. An unproven mix left running indefinitely can't be explained to a compliance head. The public_02 caller-ID cases also show a real weakness: see §13 on re-tests.

## 12. Trade-offs & rejected alternatives

| Option | Why considered | Why rejected / what instead |
|---|---|---|
| Thompson sampling | Less regret | Allocation changes need approvals, capped at 2–4 a day. An adaptive policy isn't deployable through governance, and is harder to explain |
| Bayesian decision rule | Simple to read | "Probability best" is less familiar to auditors. Sequential frequentist with a measured false-winner rate |
| Fixed-horizon test | Simplest | Can't stop early for clear winners or harm |
| Auto-apply for voice on Kestrel | Policy permits, and it's faster | Memos 02 and 04, and a 0.2 shift limit makes tests small anyway |
| Postgres or Redis now | Matches production | A dependency for the grading box. SQL ports directly |
| Holdout only for decay | Purely concurrent | Underpowered at 15%. Rejected after a real miss |
| Larger holdout | More power | Costs lift forever, so pooled control is used instead |
| Stepping past `max_shift` with chained auto-applies | Faster rotation | Evades the policy's intent |
| LLM ranks prompt fixes | Convenient | Constraint 4 |

## 13. Known weaknesses

1. Not run on 4 vCPU / 8 GB Linux. `run.sh` has only been exercised under Git Bash on Windows.
2. Impact scores are uncalibrated. They rank proposals consistently but aren't validated against outcomes.
3. A re-test reuses the alpha of the look that declared the winner. After an early stop that is very strict, so a genuinely good caller ID can be dropped (seen in public_02).
4. Standard errors treat calls as independent, but attempts on one lead are correlated. False-winner rates are somewhat understated.
5. One round per dimension. No re-experiment after rollback.
6. Quarantined caller IDs never come back.
7. Overlapping cohorts across dimensions follow first-match, so someone in two slices only gets the first slice's allocation.
8. Hallucination detection took about 4.75 hours on public_02 (edit at 11:30, incident at 16:15). The false-alarm fix bought precision with latency. Decay detection is also slow, at 3–4 days (§5).
9. No pause switch per workflow. The runbook describes a manual route.
10. Meera's weekly summary and pager integration aren't built.
11. An experiment that stalls after repeated rejection stays on its split allocation until a human acts, flagged only in the audit log.
12. No call-time optimisation, the biggest lift left on the table.

## 14. If this went to production at Formi next month

1. **Days 1–2:** run the kill test and load test on the real 4 vCPU box, profile decide time.
2. **Days 2–4:** move to the existing Postgres. Pager integration for the two page alerts.
3. **Days 3–5:** add a per-workflow pause, since the first thing on-call will want is an off switch.
4. **Week 1:** shadow mode on one client: proposals generated and reviewed, nothing sent.
5. **Week 2:** one workflow live with a human reading every proposal, comparing impact scores to realised lift.
6. **End of week 2:** fix the re-test alpha and add cluster-robust errors by lead, before trusting more workflows. Then start cohort-level call time.
