# Thresholds: derivation and sensitivity

Every tunable in `controller/settings.py` that gates a detector or an allocation, with the reasoning that fixes
its value. The rule: a threshold is derived from (a) the guardrail magnitude the brief gives (a 2% drop on the
guarded KPI is "harmful"), (b) effect-size / power arithmetic, or (c) the workflow's own policy values read over
HTTP (`min_validation_pass_rate`, `objective.guardrail`, `max_shift`). None is fitted to a public scenario's
hidden truth. Where a value is a prior, it says so. `docs/CONTEXT.md` is left unchanged.

Notation: p0 = a typical pickup rate (~0.3); se_rel(n) = sqrt((1-p0)/(n p0)) is the relative standard error of a
pickup rate: n=100 -> 15%, n=150 -> 12%, n=1000 -> 4.7%.

## Caller-ID health (C5)

| Name | Value | Derivation | Sensitivity |
|---|---|---|---|
| `DID_H_FLOOR` | 0.25 | Prior for the worst plausible relative health of an untested number. Carrier spam labelling is commonly reported to cut answer rates by about 75%, so a labelled number answers ~1/4 as often. Previously 0.35. Lower = more conservative probe cap. | Probe cap at h_bar=0.9: floor 0.35 -> 2.5%, 0.25 -> 2.1%, 0.0 -> 1.5%. |
| `DID_PROBE_BASE_STEP` | 0.015 | Harmful line is -2% on the guarded KPI; 0.5pp reserved for measurement noise. The cap `s <= 0.015 h/(h-h_floor)` keeps the worst-case DID-health step below 1.5%. | Linear: 0.01 -> cap 1.4%; 0.02 -> 2.8% (touches the line). |
| `DID_PROBE_MAX_SHARE` | 0.25 | Clamp used when h_bar <= h_floor, where the formula diverges (fleet already as bad as the worst case, a probe cannot hurt), and a global bound on any probe. | Only active when the whole fleet is unhealthy. |
| `DID_REPROBE_HARM_BUDGET` | 0.005 | A re-probe of a number whose flag expired is a second look at a known-bad candidate: it may cost at most a quarter of the 2% line. Gives share = 0.5% x h/(h-floor), about 0.7%. | Budget 0.01 -> ~1.4%: faster verdict, but residual traffic on a once-flagged number is more likely to be read as harm. |
| `DID_FLAG_MIN_DROP` | 0.12 | Effect-size gate. A number holding share s whose pickup falls by d costs the workflow s*d. At the smallest useful split (2 DIDs, s=0.5) a 12% step costs 6% = 3x the 2% guardrail; smaller steps are not worth an incident. Previously 0.30, which hid a 15-20% step. | The p gate is the real limit; at 0.08 a mild fatigue wobble starts to qualify. |
| `DID_FLAG_P` | 1e-5 | CONTEXT C5 asks p<0.001 per test; the test is repeated every tick on 4 windows (~130 looks per DID-day), so Bonferroni-style 0.001/100. | Detecting a 15% step needs ~3300 dials per side at 1e-5 (z=4.26), ~2700 at 1e-4. At 1e-3 false flags appear every few days. |
| `DID_FLAG_P_UNFITTED` | 1e-7 | While the fatigue curve is flat/cold, load effects cannot be adjusted away, so a drop may be fatigue. Two orders stricter. | Cold-start workflows flag only on large clear steps. |
| `DID_FLAG_WINDOWS_HOURS` | 1,2,3,6 | CONTEXT uses 3 h; a 6 h window adds power for 15-20% steps while diluting a step by at most the pre-step hours. | Longer windows add power and dilute the estimated drop. |
| `DID_FLAG_PERSIST_EVALS` | 2 | The condition must hold on 2 consecutive evaluations: screens one-tick outliers. | 1 reverts to the old behaviour; 3 costs another 15-60 min of detection time. |
| `DID_FLAG_COOLDOWN_MINUTES` | 2 days | A flag is not permanent: labels decay. After 2 days and complete evacuation the number is re-probed at the re-probe cap. Order of the fatigue time constant (days). | Longer = fewer re-probes; production would use about a week. |
| `DID_SHARE_WINDOW_HOURS`, `DID_SHARE_MIN_DIALS` | 12 h, 50 | Observed share needs enough dials: 50 dials give a share standard error of at most 7pp. Widens to 24 h if short. | Larger window = slower to notice an evacuation completing. |
| `DID_EVAC_CLOSE_SHARE` | 0.005 | An evacuation closes when the flagged number's observed trailing share is below 0.5% (the re-probe harm budget). | Higher closes earlier but hides residual traffic. |
| `DID_WEAK_MARGIN` | 0.15 | Materiality: a DID whose pickup at comparable load is >=15% below peers costs, at a 3-way split, 5% = 2.5x the guardrail, so removing it is worth an approval slot. Previously 0.20. | At n=150 (se_rel 12%) a weak base is confirmed only when ~50% below; with the 48 h window (n~1000) ~30% below. |
| `DID_PASS_RATIO`, `DID_PASS_Z` | 0.775, 1.645 | A probed DID passes when its load-adjusted pickup ratio is >= 1 - 1.5 x margin (halfway between healthy and the materiality line, widened by the ~15% standard error at n=100) and it is not significantly (p<0.05) below the materiality line. A looser z-only rule let a 0.55-health number pass ~1 time in 6 at the minimum n; a point rule at the 0.85 line failed ~1 in 6 healthy ones. A DID that misses the bar stays 'suspect' (probe cap at most) and is re-judged each tick, so a healthy one is delayed, not stranded. | 0.85 fails more healthy DIDs at n=100; 0.7 admits ~9% of 0.55-health DIDs. |
| `DID_PASS_MIN_DIALS` | 150 | se_rel(150) = 12%. With the 0.775 bar a 0.62-relative-health number (a 0.55-health DID next to loaded peers) passes about 2% of the time, against 16% at n=100 (one false pass was graded harmful on public_01). Probing a 2% share takes ~2 days instead of ~1.4. | Doubling n shrinks the standard error by sqrt(2). |
| `DID_PASS_MIN_AGE_HOURS` | 24 | CONTEXT: "after >= 1 day passing". | - |
| `DID_FLAG_MIN_DIALS` | 150 | Each side of the step test (CONTEXT C5). | - |

## Hallucination (C8)

| Name | Value | Derivation | Sensitivity |
|---|---|---|---|
| ceiling `1 - min_validation_pass_rate` | policy | A fix needs validation pass >= `min_validation_pass_rate`, so a flag rate above `1 - pass` is, by the workflow's own governance, worse than anything approvable. Baseline-free test: Wilson lower bound (z=3.09) of the live prompt's rolling-day flag rate above it. | A prompt whose true rate sits under the ceiling (2.5% under a 3% ceiling) is not caught by this test; it needs a baseline or the Day-0 validation. |
| impact divisor | `1 - min_pass` | Impact override = flag-rate excess / the workflow's own tolerance (was a fixed 1%). | Strict policies (0.99) saturate impact sooner. |
| `HALLUC_P`, `HALLUC_P_DRIFT` | 1e-4, 1e-5 | CONTEXT p<0.001, tightened for repeated looks. Exact Fisher is used when either count < 20 or the baseline n < 1000 (z approximation unreliable). The old 10x-alpha adherence branch is removed. | - |
| `HALLUC_MIN_CONNECTS` | 200 | At a 1.5% baseline, 200 connects hold ~3 flags: the smallest sample where an exact test can reach 1e-4 against a 5% rate. | - |
| `HALLUC_FLAG_MARGIN_FRACTION` | 1/3 | Non-inferiority margin of the verify step = a third of the workflow's tolerance (1 - min_pass) = 1pp at 0.97. | Smaller = stricter verification and more n needed. |
| `HALLUC_VERIFY_MIN_CONNECTS` | 400 | At a 0.6% flag rate, n=400 gives se 0.4pp so the upper bound of the difference (1.645 se) is ~0.7pp, inside the 1pp margin. | n=200 cannot pass a true-equal prompt at a 1pp margin. |
| `HALLUC_VERIFY_MAX_CONNECTS` | 1500 | Between 400 and 1500 connects an unresolved non-inferiority check means wait, not fail (a clean prompt with a 1.7% observed rate cannot be shown within 1pp at n=413: upper bound 1.4pp; it can at ~1000). A fix is failed at once if significantly worse than baseline (p<0.01) or fails the engagement guardrail, and after 1500 connects if still not non-inferior. | Lower = quicker failing of ambiguous fixes. |
| `HALLUC_VALIDATION_N_STEPS` | 300,200,100,50 | Day-0 validation uses the incident credit rule and scales down only when credits cannot cover 300; 50 (1 credit) is the floor. | - |
| `HALLUC_RECHECK_FAILS` | 4 ticks | A production-triggered incident whose spike no longer holds on 4 consecutive evaluations (1 h) closes as a false alarm and the blacklist is lifted. | - |
| `HALLUC_BAD_EXPIRY_MINUTES` | 2 days | A blacklisted prompt is reconsidered after 2 days (evidence ages, supervisors fix prompts). | - |
| `INCIDENT_CREDIT_DAILY_CAP` | 30 per workflow per day | One incident may spend 25; the daily cap stops repeated false incidents draining credits. | - |

## Solo-DID own-history test (A1)

Used when a caller ID has no usable peer step test (a single active DID, or probes too thin to give peers 150
dials per window). The recent window is compared with the DID's own preceding 48 h at the (hour-of-day, cell)
level, times the change the fatigue curve predicts from its own load trajectory.

| Name | Value | Derivation | Sensitivity |
|---|---|---|---|
| `DID_SOLO_REF_HOURS` | 48 | The reference must contain every hour-of-day of the window, so it spans two days; a longer reference averages over fatigue drift. At 2,000 dials/day it holds ~4,000 dials (se_rel 3%). | 24 h can lack the window's hours of day; 96 h dilutes a slow decline. |
| `DID_SOLO_SHRINK_N` | 30 | An (hour, cell) rate from a few dials is shrunk toward the hour's pooled rate with 30 pseudo-dials: it removes lead-mix change without letting a sparse cell dominate. | 0 = noisy cell rates; 100 = hour-only adjustment. |
| `DID_SOLO_P_FACTOR` | 0.1 | Level = `DID_FLAG_P` x 0.1 (1e-6; 1e-8 while the curve is unfitted). No peer absorbs a common shock, so the bar is stricter; with the 12% effect-size gate and 2-eval persistence a 6 h window needs a ~25% drop at 1,200 dials. | 1.0 flags 12-25% steps but would flag on lead-mix drift. |
| `DID_SOLO_DAYS_BACK` | 4 | Cube days loaded: window + reference. | - |

## Sibling prompt safety check (A2)

| Name | Value | Derivation | Sensitivity |
|---|---|---|---|
| `SIBLING_MAX` | 3 | At most 3 other catalogue prompts per workflow, in catalogue order (summaries are never read: R5). | More siblings spend more of the 200 credits for the same single decision. |
| `SIBLING_N` | 200 | 2 credits per sibling. | At n=200 a 0.9% failure rate cannot be separated from a 2.7% one without a top-up (below). |
| `SIBLING_TOPUP_N` | 300 | One 3-credit top-up when the sibling's observed rate is below the live prompt's lower bound but its upper bound still overlaps. | Pooled n=500 lets the bounds separate a ~1 pp gap only about half the time. |
| `SIBLING_BOUND_Z` | 1.645 | One-sided 95% Wilson bounds on each side: sibling upper bound < live lower bound ("clearly safer"). | 1.96 needs roughly 40% more n. |
| `SIBLING_MIN_LIVE_FRACTION` | 0.5 | Materiality: the live prompt's failure lower bound must be at least half the workflow's tolerance (1 - min pass = 3%, so 1.5%). A first run switched a healthy prompt (true failure ~1%, 7/300 observed) to the strict-script prompt on bounds that merely separated: -14% engagement, graded harmful. With the gate a bound-separated but immaterial gap gets one 3-credit second look at the live prompt, then no switch. Note a switch away from a permissive prompt (e.g. 2.7% failure) still costs engagement by construction: it is a safety-vs-engagement trade the approver signs off. | 0.33 (the 1 pp non-inferiority margin) admits the false switch above. |
| credits | - | Routine spend rule: after every run the balance must still hold `CREDIT_RESERVE_PER_WORKFLOW` x workflows. | - |

Verification after apply reuses the C8 constants (`HALLUC_VERIFY_*`, flag margin = a third of the workflow's
tolerance, engagement guardrail). Engagement is not checked before apply (a catalogue prompt has no engagement
history): a switch can cost engagement relative to a permissive prompt, which is why a failed verification rolls back.

## Shared cohorts (C2)

| Name | Value | Derivation | Sensitivity |
|---|---|---|---|
| `COHORT_MIN_DIALS_PER_HOUR` | 100 | n_min = 100 x in-window hours (1,000 dials for a 10 h window). A cohort-hour pickup rate from 100 dials has se_rel 15% (see notation), the smallest at which the shrinkage estimate is not mostly prior. Groups below n_min fall into `default`. | 200: fewer, larger cohorts; 50: se_rel 21%, cohorts mostly shrunk to pooled. |
| `COHORT_MAX` | 20 | The sim's limit; the largest groups are kept. | - |
| `COHORT_MIN_Z` | 3.72 | The group x hour likelihood-ratio statistic is converted to a df-comparable z (Wilson-Hilferty) and must beat one-sided p<1e-4 = 1e-3 / 10 candidate partitions (4 features + 6 pairs). A BIC penalty was tried and rejected: it discards a real age effect (LR 114, df 27) on 27k dials. | 3.09 (p=1e-3) adds a false partition about 1 time in 100 null workflows. |
| `COHORT_PAIR_MARGIN_Z` | 2.0 | A feature pair must beat the best single feature by 2 z (parsimony: pairs add df and fragment volume). | - |

The score uses a separable (group + hour) multiplicative model as the null, so pickup LEVEL differences between
groups score zero: only differing hour PROFILES, which per-cohort tables can exploit, count. Cohorts are the groups of
one feature (or pair), so they are disjoint and first-match order cannot matter (`is_partition` checks it).

## Per-cohort call time (C4a)

| Name | Value | Derivation | Sensitivity |
|---|---|---|---|
| shrinkage | empirical Bayes | B = tau^2 / (tau^2 + v), v = m/E the sampling variance of an O/E multiplier, tau^2 the between-cohort variance estimated from the same data (0 when cohorts do not differ: tables collapse to the pooled profile). No tunable. | - |
| `SCHEDULE_WEIGHT_CLIP` | 0.3-3.0 | CONTEXT C4a. Weights are mean-1 over the window and clipped; every in-window hour is present. | - |
| `SCHEDULE_HISTORY_DAYS` | 14 | Days of calls for the multipliers. | Longer: more data, slower to see a drift. |
| `SCHEDULE_BUNDLE_MIN_LIFT` | 0.05% | The Day-0 bundle's value is the significant partition (the shared cohort object); the tables only have to be an estimated non-loss. | - |
| `SCHEDULE_MIN_LIFT` | 0.5% | A refresh needs an estimated relative pickup gain of at least a quarter of the 2% guardrail, else it is churn. | 0.1%: daily refreshes chasing noise. |
| guardrail | `engagement_rate_max_drop` | The dry run re-weights recent dials (capacity per hour fixed, cohort share proportional to volume x weight) and re-composes engagement of connected leads; the change is blocked if the estimated absolute drop exceeds the workflow's guardrail (A3). | - |
| `SCHEDULE_VERIFY_MIN_DIALS` / `_DONE_DIALS` | 1,500 / 4,000 | Post-apply dials needed to evaluate / finalise the before-after check. se of a standardised pickup difference at 1,500 dials per side is ~1.6 pp (0.28 base). | - |
| `SCHEDULE_VERIFY_P` | 0.05 | Roll back only if the hour-mix-adjusted pickup (or engagement) fell by at least the guardrail AND one-sided p<0.05. There is no concurrent control, so the check is confounded (lead mix, DID changes) and conservative. | - |
