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
| `DID_PASS_Z` | 1.645 | A probed DID passes when it is NOT significantly (one-sided p<0.05) below the (1-margin) line. A point-estimate rule (formerly `DID_PASS_RATIO` 0.8) fails ~1 in 6 healthy DIDs at the minimum n=100 (se_rel 15%), stranding them as "suspect". | 1.28 passes more, 2.33 fewer. |
| `DID_PASS_MIN_DIALS` | 100 | se_rel(100) = 15%: below this the pass test cannot see even a 25% shortfall. | Doubling n shrinks the standard error by sqrt(2). |
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
| `HALLUC_VALIDATION_N_STEPS` | 300,200,100,50 | Day-0 validation uses the incident credit rule and scales down only when credits cannot cover 300; 50 (1 credit) is the floor. | - |
| `HALLUC_RECHECK_FAILS` | 4 ticks | A production-triggered incident whose spike no longer holds on 4 consecutive evaluations (1 h) closes as a false alarm and the blacklist is lifted. | - |
| `HALLUC_BAD_EXPIRY_MINUTES` | 2 days | A blacklisted prompt is reconsidered after 2 days (evidence ages, supervisors fix prompts). | - |
| `INCIDENT_CREDIT_DAILY_CAP` | 30 per workflow per day | One incident may spend 25; the daily cap stops repeated false incidents draining credits. | - |
