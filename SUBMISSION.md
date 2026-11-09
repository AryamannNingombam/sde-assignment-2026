# Outcome-First Agent Loop — Submission

**Name:** _[fill in]_ · **Date:** _[fill in]_ · **Hours actually spent (be honest):** _[fill in]_ · **Language / storage:** Python 3.11, SQLite (WAL) — no new infrastructure

---

## 0. TL;DR
- A single always-on controller: ingest call events → aggregate per workflow/hour → detect (hallucination spike, caller-ID degradation) and learn (Thompson sampling on voice × welcome per cohort) → propose/auto-apply through governance → audit everything.
- public_01: conclusion rate **+12.9 %** vs no-op (pickup +6.4 %, engagement +5.3 %). public_02: **+25.7 %**, supervisor's bad prompt fixed in **210 sim-min** (150–240 across runs, dominated by approver latency), hallucinated calls 431 → 183, 4 credits used. public_03: **+16.2 %**, ~25 s wall-clock per simulated day, 1.59 GB peak.
- Biggest lesson (§11): my first version made too many noisy changes (83–170 per run, up to 10 harmful). Adding an *evidence gate* (P(new > live) ≥ 0.85/0.90, exploration of never-seen options exempt) cut changes by ~40 % and harmful changes to 2–4 per run with the same lift. A later *guardrail monitor* (§5) costs ~2 points of lift and buys a smaller guardrail drop.
- Deliberately **not** built: per-person call time (C4), supervisor view (C11), cross-tenant credit fairness (C15), explicit winner rollback (C7, only implicit decay).

## 1. Assumptions
1. The `/workflows` governance block is the contract; memos are claims to check against it (CTO memo says the same).
2. "Customer-facing" = voice, welcome message, prompt. Caller ID and schedule are operational. I follow each workflow's `allowed_dims` literally, including `nort_cancel_2` (public_03) where voice/welcome are auto-apply-allowed even though the Northwind compliance memo only mentions renewal and KYC. **This is a risk I'd raise with Northwind before production.**
3. A simulated approver is a named human approver for the purposes of the compliance memo.
4. Hallucination baseline = the best prompt seen with ≥ 300 connected calls; the detector's own false-positive floor (~1.5 %) is part of that baseline.
5. Exploration cost is acceptable if bounded: ≤ `max_shift` per auto-apply step, ≥ 10 % exploration share, unseen caller IDs capped at 15 %.
6. Credits are cheap in the simulator, expensive in production (CTO memo): spend only on prompt incidents; cap per workflow with a token bucket.
7. One controller instance per store. Two instances on one SQLite file is out of scope (documented, not guarded).
8. Sim time drives all decisions (cooldowns, windows, TTLs); wall-clock is only used for ops (breakers, health, alerts).

## 2. Scope decisions
| # | Capability | Built / Partial / Cut | Why | What it would take to finish |
|---|---|---|---|---|
| C1 | Ingestion at load scale, idempotent, restartable | **Built** | Foundation; the CTO says scale is the real problem. 57 k events/s live, chunk + pointer committed in one transaction. | Memory diet for the lead table (§8). |
| C2 | Shared cohort object | **Partial** | Experiments + config use one cohort set (`make_groups`, ids `c_<age>_<lang>`). Hallucination and caller-ID detection are workflow-level, not cohort-level; no supervisor view consumes it. | Cohort registry table + use it in detection. ~1 day. |
| C3 | Bootstrap from history | **Built** | Pre-D0 chunks are ingested like live ones; first caller-ID/experiment decisions already have data at D0. | — |
| C4 | Call-time optimisation (per cohort/person) | **Cut** | Biggest opportunity I did not take; `schedule` is auto-apply-allowed for Northwind renewal, so it is *possible*. I preferred to do C5/C6/C8/C9 properly (README: "five done properly"). | Hour-of-day pickup aggregates per cohort + Thompson on `hour_weights`; per-person needs `lead_preferred_hour` estimation (≥ 3 attempts/person). 2–3 days. |
| C5 | Caller-ID health | **Built** | Pickup^4 allocation with shrinkage, 15 % cap on unseen IDs, urgent drain of a degraded ID, evidence gate for non-urgent moves. | Per-cohort caller-ID effects. |
| C6 | Voice/welcome experiments | **Built** | Thompson sampling per cohort × option, pooled prior (n=30), 10 % exploration, 96 h window / 24 h half-life; two dims sampled independently (interaction ignored — §13). | Interaction terms; sequential testing for false-winner control. |
| C7 | Winner promotion + decay + rollback | **Partial** | Decay is *implicit*: the 24 h half-life plus 10 % exploration let a decayed winner lose share. No explicit "rollback to previous config" action. I did not verify decay behaviour on the "Decaying variants" section of the grade. | Per-variant control chart vs its own post-promotion baseline, auto-propose rollback. |
| C8 | Hallucination incident response | **Built** | Detect (z-test vs best-prompt baseline) → known-good prompt or `suggest-fixes` → **quality check of the candidate (engagement, flow adherence)** → `validation/runs` → approval with evidence → post-apply verification of flag rate *and* quality. | Prompt-quality guardrail added (engagement + `flow_adherence`, §5/§7); thresholds are my guesses, not calibrated. |
| C9 | Governance client | **Built** | State machine in §6; stale/lapsed/expired re-plan; auto-apply only within `allowed_dims`/`max_shift`; batching of caller-ID + experiment into one request; reserve 1 request/24 h for incidents. | Per-supervisor soft limits (§3 memo 04). |
| C10 | Honest impact/affected/dry-run | **Partial** | Impact = relative expected-engagement lift from posterior means; dry run = posterior replay over the last 96 h; `affected_leads` = leads of the last 3 days. It is a model, not a real replay of historical calls. | Real counterfactual replay using logged variant × outcome. |
| C11 | Supervisor view | **Cut** | Product and the Kestrel supervisor both ask for it; I cut it because it is UI work on top of a store that already answers the questions (`why`, SQL). | A read-only page over `proposals` + `audit` + `agg`. ~1 day. |
| C12 | Queryable audit store | **Built** | `audit` table + `python -m controller why`; every row carries trace/span ids. | — |
| C13 | Crash recovery demonstrated | **Built** | `scripts/crash_test.sh` (§9). | Kill inside the "sending" window is covered by a unit test, not by chance in the script. |
| C14 | Loop observability | **Built** | `/metrics`, `/healthz`, `/readyz`, structured logs, spans, alerts on breaker-open / quarantine. | Dashboards. |
| C15 | Fair credits/approver attention across tenants | **Cut** (partial) | Per-workflow token bucket stops one workflow draining credits; no tenant-level fairness. | Per-tenant credit share + shard-level budget. |

**Principle:** pick what protects the client first (governance boundary, no double-apply, incident fix with evidence), then what moves the primary KPI measurably (caller-ID and voice/welcome), then what makes the loop operable (audit, recovery, metrics). What a client *sees* (supervisor UI) and the headline summit feature (per-person call time) lost to those.

## 3. Stakeholders

### 01 — Sales (Nikhil Rao)
- **Accepted:** speed matters. Caller-ID and cohort experiments auto-apply where policy allows (public_01: 53 changes in 8 days), stepped toward target so each step respects `max_shift`.
- **Pushed back / declined:** a single blended lift number (Product: pickup and engagement are never blended — I report them separately, per client); "push winners straight through" beyond policy; rolling the "persuasive" prompt out wherever it exists.
- **Wrong against the policies:** "Kestrel turned on auto-apply for everything" — `ks_cancel` allows only `schedule, caller_id, welcome_message, voice` with `max_shift` 0.2; **`prompt_version` and `cohorts` are not allowed** and need approval. "Northwind is fine with auto-apply on KYC" — `nw_kyc` has `auto_apply.enabled: false`; Northwind renewal allows only `schedule` and `caller_id`.
- **Reply:** "Nikhil — we can show a lift per client, with pickup and engagement side by side; a blended score would hide a client where one went down. Auto-apply is on only where the signed policy says so: Kestrel for voice, welcome message and caller ID (not prompts or cohorts), Northwind renewal for caller ID and timing, and Northwind KYC not at all. Anything else needs the client's approval, and prompts need validation evidence. We can be faster where it's allowed (those changes apply within the tick that detects them), but I won't promise 'live by evening' for approval-gated changes; approvers answer in 30 min–8 h within office hours. I can give you a per-client before/after for the summit from `reports/`."

### 02 — Client compliance (Meera Iyer, Northwind)
- **Accepted:** voice/welcome/prompt on Northwind renewal and KYC never auto-apply (policy: `allowed_dims` excludes them); prompt changes carry a `validation_run_id`; requests are timed inside approver hours (renewal 10–19, KYC 10–18); every call event records `config_version`, `cohort_id` and `variant`, so "why did this customer hear X on day D" is answerable from our store + the event log.
- **Declined / not done:** a weekly summary of operational changes is **not built** (data is in `audit`; a SQL view would do). "Slow and right": I do not slow down caller-ID/schedule changes the policy permits, but the evidence gate makes borderline moves wait.
- **Wrong / caveat:** Northwind's *cancel* workflow in public_03 (`nort_cancel_2`) allows voice/welcome auto-apply, which is broader than this memo's scope; the policy, not the memo, is the contract — flag to Northwind.
- **Reply:** "Meera — confirmed: on your renewal and KYC workflows nothing a customer hears changes without a named approval; only caller-ID rotation and call timing (renewal only) may change automatically, as per the signed policy. Prompt changes go with a validation run attached. Each change is logged with who proposed, who approved and the evidence, and every call records the variant it used, so we can answer an IRDAI query per customer per day. One thing to check on your side: your cancellation workflow's policy allows voice and welcome-message auto-apply — tell us if you want that switched off. A weekly change summary is next on our list."

### 03 — Platform / SRE (Kabir Menon)
- **Accepted:** kill-anywhere safety (`scripts/crash_test.sh`, atomic chunk+pointer commit, `reconcile()`), idempotency (deterministic `proposal_id`, 409-duplicate handled as "already landed"), actionable alerts, loop health without logs (`/metrics`, `/readyz`).
- **Pushed back:** none on principle. **No new stateful infra:** embedded SQLite file on the pod's volume (WAL). Who operates it at 2 a.m.: nobody — it is a file; the backup is a copy of the file. (`docker-compose.yml` with Valkey/sqlite-web in the repo is a dev convenience only; the controller does not use Valkey.)
- **Numbers:** one sim day of public_03 in **≈ 25 s** (budget 10 min), 1.59 GB peak, breaks first on memory at 10× (§8, `reports/public_03_load.md`). Measured on an M4 Pro, not 4 vCPU/8 GB.
- **Reply:** "Kabir — kill -9 at random points, restart, and the run completes with no double-applies: script and log are in `reports/`. Retries reuse the same proposal id and the simulator's duplicate error is treated as 'already landed'. State is one SQLite file (no Postgres/Redis added). Public_03 runs at ~25 s per simulated day, 1.6 GB RSS, on a laptop — not yet measured on your 4 vCPU box. At 10× memory breaks first (lead table); the plan is sharding by tenant. Health: `/readyz`, `/metrics`; I'd page on breaker-open, quarantined workflow and stale `/readyz`, nothing else."

### 04 — Client ops supervisor (Anita Desai, Kestrel)
- **Accepted:** never overwrite her edits — every plan starts from the *live* config, a supervisor edit makes our pending approval stale and we re-plan from it (`apply_failed … stale_base_version → re-plan`, public_02); one request containing everything (caller-ID + experiment are batched into one proposal).
- **Declined / partial:** "two requests a day, never before 11:00" is **stricter than the policy** (`max_requests_per_24h: 4`, approver hours 10–19) and I did **not** implement a per-supervisor soft limit (peak in public_02 was 1/24 h for `ks_cancel`, so it holds in practice, not by design). "Tell me before anything changes": impossible while `auto_apply` is on for her workflow — auto-applied changes are logged, not pre-announced.
- **Her prompt edits vs the hallucination fix:** if her edit causes a flag-rate spike, we do *not* silently revert — we propose the revert with validation evidence for approval (public_02: edit at D3 11:30 → detected 12:45 → approved → applied 14:00).
- **Her "word-for-word script" warning:** handled in two places (§5/§7): a candidate prompt with known history is rejected if its engagement is > 3 points below the best known prompt or its `flow_adherence` differs by > 0.05 from the known prompts — *before* credits are spent; after the fix, engagement and adherence on the new prompt are verified against the other prompts (`quality_ok` / `quality_regression` + alert). **Limits:** a brand-new prompt with no history can't be pre-checked (it's flagged `unverified` in the proposal and only caught afterwards), and the thresholds are guesses.
- **Reply:** "Anita — we won't overwrite your edits: if you change the config while we have something waiting, ours is dropped and re-planned from yours. Prompt reverts always come to you as a request with test evidence. Two things I can't promise yet: a hard cap of two requests/day before 11:00 (today we send at most one a day per workflow in practice, but it isn't enforced), and advance notice for changes your policy auto-applies — if you want that, ask Formi to turn auto-apply off for voice/welcome and everything will come to you as one request. A single-screen view of what's being tested/winning is not built yet."

### 05 — Product (Tara Kulkarni)
- **Accepted:** pickup and engagement never blended (separate columns everywhere, guardrail respected per workflow `objective`); every proposal has impact score, diff, affected leads, dry run; expiry is a rejection and we re-plan with fresh data under a **new** `proposal_id` (id contains config hash + version); evidence = actual calls only (aggregated from call events' recorded variant, so an arm that never ran contributes nothing); winners update only that workflow.
- **Pushed back / cut:** per-person call time (headline for the summit) — cut, §2 C4. Consolidated supervisor view — cut (C11). Caller-ID health — built.
- **Their open questions, answered:** *minimum cohort size* — no hard minimum; cells are age × language (≤ 20), thin cells borrow from the pooled option rate (prior n = 30) and a change must clear P(better than live) ≥ 0.85. *Evaluation window* — 96 h with 24 h half-life; cost: ~1 day to confirm a decayed winner, versus fewer false winners. *"Cohort is one shared object"* — only experiments + config share it (partial, C2).
- **Reply:** "Tara — held: pickup and engagement are separate everywhere, proposals carry impact/diff/affected/dry run, expired = rejected and re-planned fresh under a new id, and only calls that actually ran count as evidence. Not done: per-person call timing and the supervisor view — I chose to finish caller-ID health, experiments and incident handling properly first; the supervisor view is ~1 day on top of the store, call timing is 2–3. Cohorts: age×language (≤ 20), min evidence via a posterior gate rather than a fixed count — speed vs false winners is tuned by one number (0.85)."

### 06 — CTO (Aryamann)
- **Accepted:** explainability over raw lift (audit with rationale, evidence, trace id; `why` command); credits only where they change a decision (prompt incidents; public_02 used **4 of 200**); scale honesty (§8); choosing (§2); docs for whoever is paged.
- **Wrong in other memos:** see 01 (auto-apply claims), 04 (limits stricter than policy), 02 (cancel workflow scope).
- **Reply:** "Aryamann — no-says: per-person call timing, supervisor UI, per-tenant credit fairness; reasons in §2. Credit use: 4/200 in the incident scenario, 0 elsewhere. First thing to break at 10× is memory (lead table), not CPU; sharding by tenant fixes it. Biggest quality finding: unguarded learning produced up to 10 harmful changes per run; the evidence gate brought it to 2–4 with the same lift."

## 4. Architecture
Code layout (`controller/`): `api/` (HTTP client, retries, circuit breakers) · `core/` (`engine` control loop, `policy` pure decision maths, `ingest`, `limits`, `timeutil`) · `storage/` (SQLite `Store`) · `observability/` (`trace`, `logs`, `metrics` + health endpoints, `alerts`; never imports `core/`) · `__main__.py` (CLI: run / `why`).

```
 simulator (HTTP) ──GET /events/chunks──▶ Ingestor ──▶ SQLite ◀── Controller.decide(wf)
                                         (per chunk, one txn: agg + leads + pointer)   │
 /sim/state, /workflows, /config ───────────────────────────────────────────────────────┤
                                                                                         ▼
   core/policy.py (pure): did_target · did_improve_prob · engage_targets · exp_improve_prob · prompt_incident
                                                                                         ▼
   submit(): put_proposal(status=sending) ─▶ auto-apply PUT /config   or   POST /approvals ─▶ poll() ─▶ POST /apply
                                                                                         ▼
                           audit · proposals · spans · metrics tables  +  /metrics /healthz /readyz  +  JSON logs
```
- **State (SQLite, WAL, one file):** `kv` (pointers, cooldowns, `now_min`), `agg` (per wf × hour × key counters), `leads`, `proposals`, `audit`, `spans`, `metrics`.
- **Tick loop:** reconcile any `sending` → `/sim/state` → ingest → poll approvals → decide per workflow (bulkhead) → metrics → `/sim/advance`.
- **Restart:** `startup()` detects a *new world* (scenario changed, or chunks/time went backwards vs live markers) and resets; otherwise it resumes from `last_events`/`last_history`, then `reconcile()`.
- **Resilience:** separate read/write circuit breakers (5 consecutive failures, 30 s cooldown; 4xx never trips), jittered retries, per-workflow crash counter with 60-sim-min quarantine, SIGTERM = finish the tick then exit.

## 5. The learning loop
- **Cohorts:** one per (age_band × lang) present in the last 96 h if ≤ 20, else per age band. They are only created when every existing cohort id starts with `c_` — **a supervisor-defined cohort set is never touched**. Fragmentation is controlled by pooling: thin cells use the workflow-wide option rate as prior (n = 30).
- **Experiment design:** per cohort × dim ∈ {voice, welcome_message}: Beta posteriors on engaged/connected under the *current prompt only*; allocation = 0.9 · P(best) (3000 Thompson draws, seeded by sim-minute → deterministic) + 0.1/n exploration. Options with < 30 connected calls start at the mean of observed options. voice and welcome are sampled independently; interaction is ignored.
- **Deciding a winner:** posterior probability, not a p-value. A re-allocation must satisfy **P(volume-weighted expected engagement under proposal > live) ≥ 0.85** (`exp_improve_prob`, summed over both dims) or be *exploration of an option never observed* (≥ 30 connected calls = observed); suppressed proposals are written to `audit` as `suppressed` with the probability. I did **not** measure a false-winner rate.
- **Decay and rollback:** implicit — 24 h half-life, 10 % floor. No explicit rollback (C7 partial).
- **Call time and caller ID:** call time cut. Caller ID: weights ∝ (shrunk pickup)^4 from a 12 h window with 6 h half-life; unseen IDs (all-time < 100 dials) capped at 15 %; floor 3 %. Non-urgent shifts need TV ≥ 0.15 **and P(better than live) ≥ 0.90**; *urgent* (an ID with ≥ 10 % traffic whose shrunk pickup < 75 % of the best) needs TV ≥ 0.08 and skips the gate. Cooldown 60 min (urgent) / 240 min.
- **Guardrail KPI (explicit, every tick, every workflow):** the guardrail from `objective` (e.g. `engagement_rate_max_drop: 0.02`) is measured over the last 48 h and compared with the pre-D0 history. A drop only counts if statistically real (lower confidence bound > 0). Point estimate > 50 % of the limit → **hold**: on the dims that move that KPI (caller ID for pickup; voice/welcome for engagement) the evidence bar rises to P ≥ 0.95 and exploration of unseen options stops; > 100 % of the limit → **breach**: those dims are frozen (urgent caller-ID drains still allowed), an alert fires, and everything is in `audit` (`guardrail_hold/breach/ok`, hysteresis: release below 25 % of the limit). Each tick's state is also a metric (`guardrail_drop`).
- **Prompt quality guardrail:** `flow_adherence` and engagement per prompt are aggregated (`fla|<prompt>`, `eng|…|<prompt>`); see §7.

## 6. Governance
- **State machine (`proposals.status`):** `sending` → (`applied_auto` | `pending_approval` | `failed` on 4xx | `abandoned` after a crash if it never reached the simulator). `pending_approval` → `applied` | `rejected` | `expired` | `lapsed` (approved but not applied in time) | `stale` (409 on apply: config moved — supervisor edit or our own earlier change). `rejected/expired/lapsed/stale` → re-plan from the live config after 360 min / immediately, always with a new `proposal_id`.
- **Batching/timing:** caller-ID + experiment ride in one `batch` proposal; at most one change per workflow per tick; no new approval while one is pending; one request/24 h kept in reserve for incidents; non-auto experiments only inside approver hours; deferral is audited with the retry time.
- **Auto-apply vs not:** auto-apply only if enabled, every changed dim ∈ `allowed_dims`, and shift ≤ `max_shift` (otherwise `step_toward` moves partway). Prompt and cohort changes are in no workflow's `allowed_dims`, so they always take the approval route.
- **Impact / affected / dry run:** see C10 — a posterior-replay model, honest in what it is called but not a counterfactual replay.
- **Supervisor edit mid-experiment:** pending approval goes stale; plans restart from the live config; our cohorts are only rewritten if all existing cohort ids are ours.

## 7. Incidents
- **Detection (hallucination):** flag rate over the last 4 h on the *current* prompt (≥ 120 connected calls) vs the best prompt's all-time rate (floor 0.4 %): z-test; thresholds depend on whether the prompt changed in the last 8 h (z ≥ 3.5, ≥ 2.5× baseline, ≥ 2 %) or not (z ≥ 5.5, ≥ 3.5×, ≥ 3 %). Checked every 15 sim-min, hence the strict "no recent change" threshold. Expected false-positive rate was **not** measured; in public_01/03 (no incidents) it raised none.
- **Fix selection:** known-good prompts first (free), else `suggest-fixes` (3 credits); each candidate validated (n = 400, 4 credits); proposal only if `pass_rate ≥ min_validation_pass_rate + 0.005`. Credits are token-bucketed per workflow (6 calls, refill 1/30 sim-min) and an 8-credit reserve is kept.
- **Fix quality (new):** before spending credits on a candidate with ≥ 300 historical connected calls: reject (`candidate_rejected`) if engagement < best other prompt − 0.03 or mean `flow_adherence` differs from the other prompts by > 0.05 (catches "nobody hallucinated and nobody stayed" and also a too-scripted bot). A candidate with no history is allowed but marked `unverified` in the proposal.
- **Verification:** 3 h after apply, flag rate on the new prompt over ≥ 80 calls (`verified` audit row; "resolved" if < 2 %), plus `quality_ok` / `quality_regression` (engagement vs the other prompts; adherence shift > 0.05) with an alert on regression. There is no automatic revert.
- **Race fixed while testing:** a pending prompt-fix approval used to be invalidated by our own caller-ID auto-apply (version bump → `stale_base_version` → re-proposal, MTTR 150 → 240 min in one run). While a prompt fix is pending/sending, no other change is submitted for that workflow.
- **Timeline, public_02 `ks_cancel`:** D3 11:30 supervisor edit → P2 (config v21) · 12:45 incident detected (flag 5.7 % vs 1.5 %, z = 3.8) · 12:45 validation P1 passes (0.985 ≥ 0.97), proposal `apr_00009` with evidence · 13:40 approved · 14:00 applied (v22) · 17:00 verification: P1 at 3.2 % over 155 calls, logged as `STILL HIGH` (3.2 % vs my fixed 2 % bar; baseline detector noise is ~1.5 %, so I would not page on that — threshold should be relative to baseline). Grade: MTTR **150 min** in the run shown; across later runs of the same code 210–240 min (approver latency is random, 20–120 min for Kestrel). Credits **4**.
- **Caller-ID incident (flagged ID from D2 10:00):** the flagged number's share of traffic was **11.4 %** on D2 and ≤ 6 % on later days (an earlier version of the loop, before the evidence gate, left it at ~50 % on D2; I did not re-investigate why).

## 8. Scale
> Measured on the host (before the scripts moved into Docker). `scripts/eval.sh` now runs in Docker (Linux VM, native arm64) and reports peak RSS in KB; a re-run of public_01 there took 16 s vs 39 s on the host, so the figures below are conservative for a Linux container but were not re-measured for public_03.

See `reports/public_03_load.md` for the full table. Short form: **202 s wall-clock for 5 sim days + 7 days of history; ~25 s per live sim day; ingest ~54 k events/s live (211 k/s bootstrap); decide p95 265 ms for 12 workflows; peak RSS 1.59 GB.** At 10× memory breaks first (lead table ≈ 12–15 GB), then bootstrap latency (~4 min); CPU does not. Partition by tenant → one controller + one SQLite file per shard.

## 9. Reliability
- **Crash-recovery test:** `scripts/crash_test.sh` (runs entirely in Docker on a throwaway state volume; log: `reports/crash_recovery_public_02.log`): public_02, `docker kill` (SIGKILL) of the controller container at 6 s and at 10 s, restart, restart again to completion; then, **from the simulator's side**, check no `proposal_id` appears twice in any workflow's config history (58 controller-originated versions, 0 duplicates; re-run on the final code), nothing is left in `sending`, run finished. Result: **PASS** (re-run after the guardrail changes).
- **Honest limit of that test:** neither kill landed inside the narrow `sending` window (`recovered` audit rows = 0), so the *recovery branch* is proven by `tests/test_recovery.py` (all three outcomes of `reconcile()` + the duplicate-409 path), not by the kill script.
- **What state is lost:** none by design — chunk aggregates and the `last_events` pointer are one transaction; proposals are written *before* the API call.
- **Idempotency keys:** `proposal_id = ctl-<wf>-v<version>-<kind>-<sha1(config)[:10]>` is deterministic, so a retry of the same decision reuses it; `duplicate_proposal_id` (409) is resolved by looking the id up in config history / approvals.
- **4xx/5xx/transport:** transport errors → 6 jittered retries → `ConnectionError` → tick skipped without advancing sim time; 5xx and exhausted retries trip the breaker (fail-fast, 30 s); 4xx are business answers (stale/duplicate/402) and never trip it.
- **Known bug found and fixed while preparing this submission:** the "new simulator world" check compared against a stale startup signature, so re-using a controller store against a restarted simulator silently ingested nothing (my first public_02 re-run showed 5 changes and 0 credits). Now compares live progress markers (`seen_chunks`, `now_min`); covered by a test.

## 10. Audit & observability
```
$ docker compose run --rm --no-deps controller python -m controller why --state-dir /state --wf ks_cancel --at "D3 13:00" --window 90
[D3 11:30] config_changed     v21 by supervisor changed ['prompt_version']
[D3 12:45] incident           hallucination spike on P2: flag rate 5.7% vs baseline 1.5% (7/124 connected calls, z=3.8)
[D3 12:45] validation         P1: pass_rate 0.985 (need >= 0.97) run val_00001
[D3 12:45] proposed           apr_00009 (prompt_fix): Revert prompt P2 -> P1 (hallucination spike)
      rationale: "Hallucination flag rate on P2 is 5.7% vs 1.5% on P1 (z=3.8, n=124). P1 passed validation val_00001 with pass_rate 0.985."
      evidence: {"validation_run_id": "val_00001"}
      proposal_id: "ctl-ks_cancel-v21-prompt_fix-7cdec67b5e"
[D3 13:40] approval_decided   apr_00009 approved
[D3 14:00] applied            apr_00009 applied as v22 (prompt_fix)
[D3 14:00] config_changed     v22 by controller_approved changed ['prompt_version']
[D3 14:15] suppressed         experiment not proposed: P(better than live) = 0.62 < 0.85 (expected lift +0.37%, max cohort shift 0.39)
```
Every audit row also carries `trace_id`/`span_id` linking to the `spans` table (`SELECT name, dur_ms, status FROM spans WHERE trace_id = ?`), and every log line is JSON with the same ids.
- **Page on:** circuit breaker open (the simulator/API is failing), a workflow quarantined after 3 crashes, `/readyz` failing > 2 min. Each alert text says which breaker/workflow.
- **Do not page on:** `suppressed`, `deferred`, `apply_failed(stale)` (normal governance traffic), `rate_limited`, a single 4xx.

## 11. Results
Final code, clean store per run (`scripts/eval.sh`). Conclusion = leads concluded ÷ leads uploaded, vs a no-op controller.

| Scenario | Conclusion Δ | Pickup Δ | Engagement Δ | Changes (ben / neutral / harmful) | Notes |
|---|---|---|---|---|---|
| public_01 | **+12.9 %** | +6.4 % | +5.3 % | 52 (13 / 36 / 3) | gap captured 24 % |
| public_02 | **+25.7 %** | +21.2 % | +2.1 % | 65 (16 / 48 / 1) | MTTR 210 min; hallucinated calls 183 vs 431; credits 4 |
| public_03 | **+16.2 %** | +8.3 % | +5.6 % | 103 (46 / 53 / 4) | 12 workflows |

**Three stages of the same loop** (single runs; two clean runs of identical code differed by ≤ 0.2 points, so the gaps below are larger than run-to-run noise on public_01):

| Scenario | v1: no gates | + evidence gate | + guardrail monitor & pending-fix rule (final) |
|---|---|---|---|
| public_01 | 83–93 applied, 4–9 harmful, +14.6 % | 54, 4, +14.7 % | 52, 3, **+12.9 %** |
| public_02 | 114, 7, +26.3 % | 68, 2, +28.3 % | 65, 1, **+25.7 %** |
| public_03 | 170, 10, +16.2 % | 98, 4, +16.3 % | 103, 4, **+16.2 %** |

The guardrail layer cost ~2 points of conclusion lift on public_01/02 (none on public_03). What it bought: `nw_kyc` engagement (the guardrail KPI of a pickup-primary workflow) was −2.3 % in public_02 versus −2.9 % before and never crossed its limit, `nw_kyc` is +3.0 % in public_01; breach/hold transitions are visible in `audit`. I did **not** test whether a looser hold threshold (e.g. 75 % of the limit) keeps more lift at the same safety.

**Where I was harmful and why.** (1) *Caller-ID churn:* `nw_renewal` got 25+ rebalances in 8 days chasing differences of ~0.01 between IDs; `(pickup)^4` turned noise into ≥ 15 % shifts, and decayed windows made a known-bad ID look "unexplored" again every few hours. Fix: all-time exploration status + P(better) ≥ 0.90 gate (the gate often reads 0.04–0.4, i.e. the planned move was *worse* than live). (2) *Fresh Thompson draws:* every cycle re-sampled allocations and applied noise-level moves. Fix: P(better) ≥ 0.85, with exploration of never-observed options exempt — **my first version of the gate also blocked exploration and learning dropped to ~0 % gap captured; the history only contains V1/W1, so unseen options can't show evidence.** Remaining harmful changes are mostly the price of exploring a genuinely bad caller ID (`D4`) and a few voice/welcome moves; one urgent caller-ID drain (−0.049) in public_01. `arav_kyc_1`/`tide_kyc_1` gained nothing (auto-apply off, max 2 requests/day, `next_campaign_only`) — I'd look there first.

Full tables: `reports/public_01.md`, `reports/public_02.md`, `reports/public_03.md`; wall-clock/RSS: `reports/walltime.txt`. (`*_try1/try2.md` are earlier attempts, kept for the history.)

## 12. Trade-offs & rejected alternatives
| Option | Why considered | Why rejected / what instead |
|---|---|---|
| Postgres/Redis/Valkey for state | SRE already runs them; shared state for HA | SRE memo: no new stateful infra; single writer per shard is enough; SQLite WAL + atomic chunk commits give crash safety. A Valkey container exists in `docker-compose.yml` for experiments; unused by the controller. |
| LLM decides winners | Fast to build | Constraint 4: statistics decide; the LLM only proposes prompt candidates. |
| Fixed minimum sample per cohort | Easy to explain | Fragments traffic; pooled prior + posterior gate adapts to cohort size. |
| Gate *all* changes on P(better) | Fewest harmful changes | Killed learning (no evidence for unseen options). Gate exploitation only. |
| Disable auto-apply to be "safe" | Compliance comfort | Policy permits it; harm came from noise, not from auto-apply. |
| Thread pool per workflow (true bulkhead) | Isolation of slow workflows | SQLite connection + ordering issues; per-workflow try/except + breaker + quarantine was enough at 12 workflows. |
| OpenTelemetry SDK | Standard | New dependencies to defend; hand-rolled W3C `traceparent` + spans table was ~60 lines. |

## 13. Known weaknesses
- **`flow_adherence` guardrail is a heuristic.** Thresholds (engagement −0.03, adherence ±0.05) are guesses from one data look (mean ≈ 0.93, range 0.66–1.0) and were never exercised by an actual bad-fix scenario in the public data (every `quality_ok` in my runs). A prompt with no history can't be pre-checked and an adherence regression only alerts, it does not auto-revert.
- **Guardrail monitor limits:** reference = pre-D0 history (no seasonality or drift model); a persistent *legitimate* shift would hold the workflow; hold/breach are tuned on three scenarios; it costs ~2 points of lift (§11) and I did not tune that trade-off.
- **No false-winner / false-positive rates measured**; one seed per scenario; gates (0.85/0.90) are tuned on the three public scenarios, so hidden ones may behave differently.
- **Post-fix verification threshold is absolute (2 %)**, not relative to baseline: logs `STILL HIGH` at 3.2 % although it's near the detector noise floor.
- **Voice × welcome interaction** ignored; independent sampling.
- **Exploration still costs:** unseen caller IDs get up to 15 %; one run showed −0.026 pickup for the first exploration of a bad ID.
- **Hallucinated calls are not lower than baseline** in public_01 (153 vs 132) and public_03 (5162 vs 4667): I did not investigate whether voice/welcome changes influence the detector.
- **Per-supervisor limits** (2/day, not before 11:00) and a weekly summary for Northwind are not implemented.
- **Logs:** `warning`/`error` records go to **stderr** and the rest to stdout — redirect both (I lost sight of crash records once because only stdout was captured). **Memory** scales with leads (§8). **Single instance** per store; no leader election.
- **Impact/dry-run** are model-based, not a counterfactual replay.
- Timings are from a laptop, not 4 vCPU/8 GB.

## 14. If this went to production at Formi next month
1. (Day 1–2) Run on a 4 vCPU/8 GB box against public_03; add RSS/latency alerts.
2. (Day 2–4) Calibrate the quality guardrail on real data (adherence/engagement thresholds, seasonality-aware reference for the guardrail monitor), add auto-revert on `quality_regression`, and make the post-fix flag-rate check relative to baseline.
3. (Week 1) Shadow mode: run the loop proposing-only on real workflows for a week, compare against what supervisors changed by hand.
4. (Week 1) Supervisor/ops view over `proposals` + `audit` (read-only page), the Northwind weekly summary, and per-workflow soft limits (requests/day, earliest hour).
5. (Week 2) Per-tenant credit shares + tenant sharding (one process/SQLite per shard); lead-table memory diet.
6. (Week 2) Explicit winner decay/rollback; measure false-winner and false-incident rates on replayed history; revisit the 0.85/0.90 thresholds with that data.
7. (Week 2) Runbook for the person paged: breaker open → check simulator/API health; quarantine → `why` + `spans` for the failing trace id; stuck `sending` → restart (reconcile resolves it).
