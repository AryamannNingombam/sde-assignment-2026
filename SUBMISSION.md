# Outcome-First Agent Loop — Submission

**Name:** Sahil Verma · **Date:** 2026-11-09 · **Hours actually spent:** approximately 6 · **Language / storage:** Python, JSON state

## 0. TL;DR

The controller consumes simulator chunks, keeps restartable statistics, proposes cautious voice changes, and records approval state locally. The latest public runs captured positive engagement lift without harmful applied changes. Prompt changes are only proposed after a population-level hallucination test and validation evidence, then still pass through approval.

## 1. Assumptions

1. Event chunks are immutable and event IDs are monotonic.
2. A controller restart must preserve its last processed chunk and pending approval IDs.
3. A variant needs at least 200 dials before it is compared.
4. A change must show at least a 1 percentage-point observed lift before proposal; initial exploration is capped at 10% outside the incumbent.

## 2. Scope decisions

| # | Capability | Built / Partial / Cut | Why | What it would take to finish |
|---|---|---|---|---|
| C1 | Event ingestion | Built | Chunk cursor and atomic JSON state | Partitioned store at load scale |
| C2 | Cohorts | Partial | Simulator cohorts are preserved in events | Shared cohort feature store |
| C3 | History bootstrap | Built | History chunks are consumed before live events | More compact aggregation |
| C5 | Caller-ID health | Partial | Rotates toward a clearly healthier ID | Formal sequential test |
| C6 | Experiments | Partial | Minimum sample and exploration guard | Cohort-level factorial design |
| C8 | Incident response | Partial | Conservative safety gate and caller-ID rotation | Full incident state machine |
| C9 | Governance | Built | Approval polling and idempotent proposal IDs | Batching across tenants |
| C12 | Audit store | Partial | Local JSON state and simulator approvals | Queryable SQLite/event store |
| C13 | Crash recovery | Partial | Atomic state replacement and resumable cursor | Automated kill test |

## 3. Stakeholders

### Sales

Accepted the need for measurable lift and low proposal volume. Pushed back on blended KPIs, instant rollout, and bypassing approvals: pickup and engagement are separate, and the simulator contract makes governance mandatory. Reply: “We will show separate KPI movement and only promote changes with population evidence and the required approval. That is slower than a demo shortcut, but it gives the client a result we can explain.”

### Client Compliance

Accepted named approval for customer-facing changes, validation evidence for scripts, and variant-level auditability. Pushed back only on treating operational latitude as invisible; all changes are recorded. Reply: “Every customer-facing change carries its evidence and approval ID, and the event record identifies the exact variant. We will include operational changes in the weekly summary.”

### Platform & SRE

Accepted idempotency, restartability, bounded memory, and actionable audit records. Chose JSON state for the assignment to avoid new infrastructure; production would use the existing database. Reply: “The controller checkpoints its chunk cursor and pending approvals atomically. The load run exposed an unbounded incident buffer, which is now a bounded rolling window.”

### Client Operations Supervisor

Accepted supervisor edits as authoritative and limited proposal volume. Pushed back on silently undoing edits; the controller audits supervisor changes and does not overwrite them outside governance. Reply: “Your edits remain authoritative. We record them, reconcile pending proposals against the new version, and batch future requests rather than flooding your queue.”

### Product

Accepted separate KPI definitions, one workflow-local config, evidence-bearing proposals, and fresh-data re-proposal after expiry. Cut the full consolidated UI and per-person optimizer to keep the experiment and governance loop correct. Reply: “The current iteration prioritizes a reliable decision loop and audit trail. A supervisor view and per-person timing are explicit next steps, not implied capabilities.”

### CTO

Accepted explainability, bounded credit use, scale measurement, and explicit cuts. Pushed back on treating every wishlist item as P0. Reply: “I prioritized ingestion, governance, safe experimentation, auditability, and recovery. I cut the UI and full per-person optimizer, and documented the production work needed to add them.”

## 4. Architecture

```text
simulator events -> chunk reader -> local statistics/state -> guarded policy
                                      |                  |
                                      +-> audit JSON      +-> approval API
                                                         +-> applied config
```

## 5. Reliability

State is written through a temporary file followed by replacement. The chunk cursor is advanced only after a chunk is read successfully. Approval IDs are persisted before the next loop, so restart reconciliation can poll and apply an approved request once.

## 6. Public results

| Scenario | Conclusion-rate delta | Engagement delta | Harmful changes | Applied changes |
|---|---:|---:|---:|---:|
| public_01_dev | +5.1% | +0.4% | 0 | 3 |
| public_02_incidents | +2.1% | +0.3% | 0 | 3 |
| public_03_load | +0.4% | +0.3% | 0 | 12 |

The final public_02 run used 90% incumbent voice traffic and 10% exploration. Its overall pickup rate was -1.1% versus baseline, so the result is a modest engagement improvement with a guardrail trade-off that should be monitored before production rollout.

## 7. Scale

The public_03 baseline generated 9,737,439 events in 329.3 seconds and wrote 4.45 GB of output. The full controller run completed without a memory failure; its aggregate result was +0.4% conclusion rate, +0.1% pickup, and +0.3% engagement versus baseline. It applied 12 neutral voice changes, with no harmful changes. The first limit is event-file I/O, not controller policy evaluation. At 10x scale I would partition ingestion by tenant and workflow, use compressed segments, and keep only aggregate statistics in memory.

## 8. Known weaknesses

The current controller is intentionally conservative after public_02 revealed harmful prompt and voice cascades. It still needs a proper post-apply rollback monitor, a durable queryable audit database, and a complete supervisor-edit state machine before production use.

## 9. Crash-recovery evidence

Run the controller, stop it with `Ctrl+C`, then run [scripts/crash_recovery.ps1](scripts/crash_recovery.ps1) again with the same state path. The persisted chunk cursor and approval IDs are the recovery evidence; the controller does not reprocess completed chunks or lose pending approvals.

## 10. If this went to production at Formi next month

First, i would add SQLite audit queries and crash tests. Next, sequential guardrail tests and automatic rollback. Then enable cohort-level experiments behind a feature flag, run shadow mode, and only after two weeks of clean guardrail data enable auto-apply for caller-ID rotation.
