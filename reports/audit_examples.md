# Audit examples (C12): `controller why` on the final graded runs

Runs: runs/final_mine01 + state/final1\public_01_dev-b730e0b5.db; runs/final_mine02 + state/final2\public_02_incidents-afcb9425.db. `--at` Day numbers are 0-based, as the grader prints them. Code commit c556fce. (STATE_DIR was state/final1 and state/final2.)

## public_01 - approved change: ks_cancel v3 (experiment entry, apr_00003)

```
$ python -m controller why --db <db> --workflow ks_cancel --at 'Day 0 12:30'
why ks_cancel at Day 0 12:30
  active version v3 by controller_approved (observed Day 0 12:15, dims ["cohorts", "welcome_message", "voice", "schedule"])
    prompt P1, cohorts 4, allocations {"default": {"caller_id": {"D1": 0.48929382311941066, "D2": 0.48929382311941066, "D3": 0.02141235376117863}, "voice": {"V1": 0.775, "V2": 0.075, "V3": 0.075, "V4": 0.075}, "welcome_message": {"W1": 0.85, "W2": 0.075, "W3": 0.075}}}
  proposal ks_cancel:2:experiment_entry [approval] state=CLOSED base=v2 applied=v3 at Day 0 12:15
    summary: Start voice experiment: control V1 keeps 77.5%, challengers V2 7.5%, V3 7.5%, V4 7.5% (total 22.5%); Start welcome_message experiment: control W1 keeps 85.0%, challengers W2 7.5%, W3 7.5% (total 15.0%); Define 4 cohorts and per-cohort call-time tables: est. pickup 0.248 -> 0.250 (+0.5%), est. engage
    rationale: Controlled exploration of voice: every challenger enters at 7.5% (total <= 22.5%), so even a challenger that is 10% worse costs under 2.2% of expected engagement; harm-stop every 4 h at z <= -3.0. | Controlled exploration of welcome_message: every challenger enters at 7.5% (total <= 22.5%), so even a challenger that is 10% worse costs under 1.5% of expected engagement; harm-stop every 4 h at z <= -3.0. | Define 4 cohorts and per-cohort call-time tables: est. pickup 0.248 -> 0.250 (+0.5%), est. engagement shift -0.000 (guardrail 0.02); weights only re-rank leads within an hour
    impact=0.225 affected_leads=4662 tv={'age_band=18-30/voice': 0.225, 'age_band=18-30/welcome_message': 0.15, 'age_band=31-45/voice': 0.225, 'age_band=31-45/welcome_message': 0.15, 'age_band=46-60/voice': 0.225, 'age_band=46-60/welcome_message': 0.15, 'age_band=60+/voice': 0.225, 'age_band=60+/welcome_message': 0.15, 'default/voice': 0.225, 'default/welcome_message': 0.15}
    dry_run: {"allocations": [{"arms": {"W1": {"n": 632, "rate": 0.4164, "status": "observed"}, "W2": {"status": "no_evidence"}, "W3": {"status": "no_evidence"}}, "ci95_new": [0.378, 0.4548], "cohort": "age_band=18-30", "dim": "welcome_message", "evidence": "partial", "exp...(truncated; see --json)
    approval apr_00003: APPROVED (decided_at Day 0 11:59, observed_at Day 0 12:15) by policy approver of ks_cancel; the sim exposes no approver names
    policy: approver hours [10, 19], latency [20, 120] min, ttl 12 h, max 4 requests/24h; objective {'guardrail': {'pickup_rate_max_drop': 0.02}, 'primary': 'engagement_rate'}
  proposal lifecycle:
    Day 0 11:00 DRAFT
    Day 0 11:00 INTENT
    Day 0 11:00 PENDING approval created
    Day 0 11:59 APPROVED decided_at Day 0 11:59, observed_at Day 0 12:15 approved
    Day 0 12:15 apply_intent
    Day 0 12:15 APPLIED applied
    Day 0 12:30 MONITORING monitoring after apply
    Day 1 12:15 CLOSED monitoring window over
  our decisions for this change:
    Day 0 11:00 proposal_pending: ks_cancel:2:experiment_entry: PENDING
      inputs: {"approval_id": "apr_00003", "expires_minute": 1380, "filed_minute": 660, "from": "INTENT", "note": "approval created", "proposal_id": "ks_cancel:2:experiment_entry"}
    Day 0 12:15 proposal_approved: ks_cancel:2:experiment_entry: APPROVED
      inputs: {"apply_by_minute": 839, "approval_id": "apr_00003", "decided_at": "2027-01-04T11:59:00+05:30", "from": "PENDING", "note": "approved", "proposal_id": "ks_cancel:2:experiment_entry"}
    Day 0 12:15 proposal_apply_intent: ks_cancel:2:experiment_entry: apply_intent
      inputs: {"approval_id": "apr_00003", "proposal_id": "ks_cancel:2:experiment_entry"}
    Day 0 12:15 proposal_applied: ks_cancel:2:experiment_entry: APPLIED
      inputs: {"applied_minute": 735, "applied_version": 3, "approval_id": "apr_00003", "changed_dims": ["cohorts", "welcome_message", "voice", "schedule"], "from": "APPROVED", "note": "applied", "proposal_id": "ks_cancel:2:experiment_entry"}
    Day 0 12:15 config_observed: v3 by controller_approved changed ['cohorts', 'welcome_message', 'voice', 'schedule']
      inputs: {"approval_id": "apr_00003", "event_id": 193432, "proposal_id": "ks_cancel:2:experiment_entry"}
  evidence (newest detector/test rows in the 24h before the proposal):
    Day 0 00:00 validation_run: ks_cancel P4: pass_rate 0.955 (n=200, val_00006)
      inputs: {"failures": 9, "n": 200, "pass_rate": 0.955, "prompt_version": "P4", "validation_run_id": "val_00006"}
    Day 0 00:00 did_curve_fit: fatigue curve refit: tau=120h fitted=True points=28
      inputs: {"fitted": true, "hs": [1.0, 0.9683, 0.9316, 0.9104, 0.8912, 0.876, 0.8448, 0.8428, 0.8348], "n_obs": 28, "tau_hours": 120.0, "xs": [589.4, 2743.3, 4916.1, 6542.2, 6571.0, 7527.6, 8646.9, 9495.1, 10445.6]}
    Day 0 00:00 did_tested: D2 passes: not worse than peers at its load
      inputs: {"dials": 32620, "did": "D2", "peer": {"connects": 1162, "did": "D2", "expected": 1150.26, "load": 10913.2, "n": 4836, "peer_load": 10940.8, "q": 1.0102, "z_weak": 6.613}}
    Day 0 11:00 halluc_eval: P1: flags 2.04% vs 1.37% (n=1077, p=3.62e-02, ceiling 3.0%)
      inputs: {"adherence_drop": -0.0014, "base_n": 16222, "base_rate": 0.013746763654296635, "baseline_source": "history", "ceiling": 0.030000000000000027, "flags": 22, "n": 1077, "p": 0.036192305613994835, "prompt": "P1", "rate": 0.02042711234911792, "rate_lb": 0.01073, "...(truncated; see --json)
    Day 0 11:00 did_eval: caller-ID evaluation: D1=tested, D2=tested, D3=untested
      inputs: {"best_step": {"did": "D2", "drop": 0.0873, "n": 200, "n_peers": 200, "n_ref": 2408, "p": 0.29784514953705493, "q_ref": 1.0602, "q_window": 0.9636, "share_ref": 0.5017, "share_window": 0.5, "solo": false, "window_h": 2, "z": -0.531}, "curve": {"fitted": true, ...(truncated; see --json)
  post-apply monitoring:
    Day 0 12:15 config_observed: v3 by controller_approved changed ['cohorts', 'welcome_message', 'voice', 'schedule']
      inputs: {"approval_id": "apr_00003", "event_id": 193432, "proposal_id": "ks_cancel:2:experiment_entry"}
    Day 0 12:30 schedule_applied: per-cohort call times live since Day 0 12:15 (config v3); verifying hour-mix-adjusted pickup
      inputs: {"estimate": {"engagement_drop": 0.00034, "engagement_new": 0.50074, "engagement_old": 0.50109, "pickup_new": 0.24965, "pickup_old": 0.24829, "rel_lift": 0.00547}, "version": 3}
    Day 0 12:30 experiment_applied: experiment_entry for welcome_message is live (Day 0 12:15): W1 85.0%, W2 7.5%, W3 7.5%
      inputs: {"kind": "experiment_entry", "phase": "running"}
    Day 0 12:30 experiment_applied: experiment_entry for voice is live (Day 0 12:15): V1 77.5%, V2 7.5%, V3 7.5%, V4 7.5%
      inputs: {"kind": "experiment_entry", "phase": "running"}
    Day 0 16:00 halluc_eval: P1: flags 1.81% vs 1.37% (n=1050, p=1.52e-01, ceiling 3.0%)
      inputs: {"adherence_drop": -0.0016, "base_n": 16222, "base_rate": 0.013746763654296635, "baseline_source": "history", "ceiling": 0.030000000000000027, "flags": 19, "n": 1050, "p": 0.15228217058603524, "prompt": "P1", "rate": 0.018095238095238095, "rate_lb": 0.00906, "...(truncated; see --json)
    Day 0 16:45 did_eval: caller-ID evaluation: D1=tested, D2=tested, D3=untested
      inputs: {"best_step": {"did": "D2", "drop": 0.1014, "n": 541, "n_peers": 559, "n_ref": 2424, "p": 0.19789227770704745, "q_ref": 1.0305, "q_window": 0.9185, "share_ref": 0.505, "share_window": 0.4918, "solo": false, "window_h": 3, "z": -0.849}, "curve": {"fitted": true...(truncated; see --json)
    Day 0 16:45 schedule_rollback: hour-mix-adjusted engagement fell beyond the guardrail after the call-time change: rolling back (confounded before/after check)
      inputs: {"cells": 16, "engagement": {"after_std": 0.46764, "before": 0.53279, "drop": 0.06515, "p_drop": 0.016653968094442292, "se": 0.03061, "z": 2.128}, "n_after": 1500, "pickup": {"after_std": 0.23288, "before": 0.22875, "drop": -0.00413, "p_drop": 0.62897995960303...(truncated; see --json)
    Day 0 16:45 config_observed: v4 by controller_auto changed ['schedule']
      inputs: {"approval_id": null, "event_id": 197487, "proposal_id": "ks_cancel:3:schedule_rollback"}
  superseded by v4 (controller_auto) at Day 0 16:45, dims ["schedule"], proposal ks_cancel:3:schedule_rollback: Roll back per-cohort call times: hour-mix-adjusted pickup/engagement fell beyond the guardrail
```

## public_01 - auto-applied change: ks_cancel v5 (did_spread, within policy, no approval)

```
$ python -m controller why --db <db> --workflow ks_cancel --at 'Day 1 13:30'
why ks_cancel at Day 1 13:30
  active version v5 by controller_auto (observed Day 1 13:15, dims ["caller_id"])
    prompt P1, cohorts 4, allocations {"default": {"caller_id": {"D1": 0.3333333333333333, "D2": 0.455254312905488, "D3": 0.21141235376117862}, "voice": {"V1": 0.775, "V2": 0.075, "V3": 0.075, "V4": 0.075}, "welcome_message": {"W1": 0.85, "W2": 0.075, "W3": 0.075}}}
  proposal ks_cancel:4:did_spread [auto] state=CLOSED base=v4 applied=v5 at Day 1 13:15
    summary: Spread calls evenly over healthy caller IDs (h-bar 0.79): default: D1 48.9%->33.3%, D2 48.9%->45.5%, D3 2.1%->21.1%
    rationale: caller-ID load spreading; statuses: D1=tested, D2=tested, D3=tested; default: D1 48.9%->33.3%, D2 48.9%->45.5%, D3 2.1%->21.1%
    impact=0.0 affected_leads=4539 tv={'age_band=18-30/caller_id': 0.19, 'age_band=31-45/caller_id': 0.19, 'age_band=46-60/caller_id': 0.19, 'age_band=60+/caller_id': 0.19, 'default/caller_id': 0.19}
    auto-applied under the workflow's auto_apply policy (no approval)
  proposal lifecycle:
    Day 1 13:15 DRAFT
    Day 1 13:15 INTENT
    Day 1 13:15 AUTO_APPLIED auto-applied
    Day 1 13:30 MONITORING monitoring after apply
    Day 2 13:15 CLOSED monitoring window over
  our decisions for this change:
    Day 1 13:15 proposal_auto_applied: ks_cancel:4:did_spread: AUTO_APPLIED
      inputs: {"applied_minute": 2235, "applied_version": 5, "approval_id": null, "changed_dims": ["caller_id"], "from": "INTENT", "note": "auto-applied", "proposal_id": "ks_cancel:4:did_spread"}
    Day 1 13:15 config_observed: v5 by controller_auto changed ['caller_id']
      inputs: {"approval_id": null, "event_id": 208041, "proposal_id": "ks_cancel:4:did_spread"}
  evidence (newest detector/test rows in the 24h before the proposal):
    Day 1 00:00 did_curve_fit: fatigue curve refit: tau=72h fitted=True points=31
      inputs: {"fitted": true, "hs": [1.0, 0.938, 0.9082, 0.8738, 0.8539, 0.8359, 0.8216, 0.7924, 0.7831], "n_obs": 31, "tau_hours": 72.0, "xs": [46.7, 580.6, 2465.0, 4152.4, 5225.0, 5227.4, 5762.5, 6283.8, 6886.3]}
    Day 1 13:00 halluc_eval: P1: flags 1.49% vs 1.37% (n=1074, p=4.15e-01, ceiling 3.0%)
      inputs: {"adherence_drop": 0.0011, "base_n": 16222, "base_rate": 0.013746763654296635, "baseline_source": "history", "ceiling": 0.030000000000000027, "flags": 16, "n": 1074, "p": 0.41487340882351187, "prompt": "P1", "rate": 0.0148975791433892, "rate_lb": 0.00702, "tri...(truncated; see --json)
    Day 1 13:15 did_tested: D3 passes: not worse than peers at its load
      inputs: {"dials": 150, "did": "D3", "peer": {"connects": 44, "did": "D3", "expected": 47.05, "load": 60.7, "n": 150, "peer_load": 7031.2, "q": 0.9352, "z_weak": 0.742}}
    Day 1 13:15 did_eval: caller-ID evaluation: D1=tested, D2=tested, D3=tested
      inputs: {"best_step": {"did": "D1", "drop": 0.2098, "n": 807, "n_peers": 893, "n_ref": 2285, "p": 0.0071914854210200834, "q_ref": 0.9733, "q_window": 0.7701, "share_ref": 0.476, "share_window": 0.4747, "solo": false, "window_h": 6, "z": -2.448}, "curve": {"fitted": tr...(truncated; see --json)
  post-apply monitoring:
    Day 1 13:15 did_tested: D3 passes: not worse than peers at its load
      inputs: {"dials": 150, "did": "D3", "peer": {"connects": 44, "did": "D3", "expected": 47.05, "load": 60.7, "n": 150, "peer_load": 7031.2, "q": 0.9352, "z_weak": 0.742}}
    Day 1 13:15 config_observed: v5 by controller_auto changed ['caller_id']
      inputs: {"approval_id": null, "event_id": 208041, "proposal_id": "ks_cancel:4:did_spread"}
    Day 1 14:00 halluc_eval: P1: flags 1.65% vs 1.37% (n=1093, p=2.63e-01, ceiling 3.0%)
      inputs: {"adherence_drop": 0.0009, "base_n": 16222, "base_rate": 0.013746763654296635, "baseline_source": "history", "ceiling": 0.030000000000000027, "flags": 18, "n": 1093, "p": 0.26310655778602643, "prompt": "P1", "rate": 0.01646843549862763, "rate_lb": 0.00809, "tr...(truncated; see --json)
    Day 1 14:15 did_eval: caller-ID evaluation: D1=tested, D2=tested, D3=tested
      inputs: {"best_step": {"did": "D2", "drop": 0.1989, "n": 215, "n_peers": 285, "n_ref": 2391, "p": 0.09207369752013761, "q_ref": 1.0815, "q_window": 0.8054, "share_ref": 0.4981, "share_window": 0.43, "solo": false, "window_h": 2, "z": -1.328}, "curve": {"fitted": true,...(truncated; see --json)
    Day 1 14:15 config_observed: v6 by controller_auto changed ['caller_id']
      inputs: {"approval_id": null, "event_id": 208942, "proposal_id": "ks_cancel:5:did_spread"}
  superseded by v6 (controller_auto) at Day 1 14:15, dims ["caller_id"], proposal ks_cancel:5:did_spread: Spread calls evenly over healthy caller IDs (h-bar 0.80): default: D1 33.3%->33.3%, D2 45.5%->33.3%, D3 21.1%->33.3%
```

## public_02 - approved change: ks_cancel v9 (halluc_fix reverting the supervisor's bad prompt, apr_00008)

```
$ python -m controller why --db <db> --workflow ks_cancel --at 'Day 3 14:00'
why ks_cancel at Day 3 14:00
  active version v9 by controller_approved (observed Day 3 13:45, dims ["welcome_message", "voice", "prompt_version"])
    prompt P1, cohorts 4, allocations {"default": {"caller_id": {"D1": 0.5, "D3": 0.5}, "voice": {"V1": 0.925, "V2": 0.075}, "welcome_message": {"W1": 0.725, "W2": 0.2, "W3": 0.075}}}
  proposal ks_cancel:9:halluc_fix [approval] state=CLOSED base=v8 applied=v9 at Day 3 13:45
    summary: Revert P2 (set by supervisor Day 3 11:30) to P1: flags 5.5% vs failed Day-0 validation (n=200, p=0.0e+00); validation val_00001 pass 0.987; voice experiment: drop V3 (lift -11.3%, z -1.70, recent z -1.20); new split V1 92.5%, V2 7.5%; welcome_message experiment: ramp W2 (lift +26.5%, z 3.41, n 150);
    rationale: Revert P2 (set by supervisor Day 3 11:30) to P1: flags 5.5% vs failed Day-0 validation (n=200, p=0.0e+00); validation val_00001 pass 0.987. Fix source: known_good; engagement is verified after apply. | voice experiment: drop V3 (lift -11.3%, z -1.70, recent z -1.20); new split V1 92.5%, V2 7.5%. Ramp: after >= 1 day and >= 100 connects, point estimate >= control; drop at z <= -1. | welcome_message experiment: ramp W2 (lift +26.5%, z 3.41, n 150); new split W1 72.5%, W2 20.0%, W3 7.5%. Ramp: after >= 1 day and >= 100 connects, point estimate >= control; drop at z <= -1.
    impact=1.0 affected_leads=3671 tv={'age_band=18-30/voice': 0.15, 'age_band=18-30/welcome_message': 0.125, 'age_band=31-45/voice': 0.15, 'age_band=31-45/welcome_message': 0.125, 'age_band=46-60/voice': 0.15, 'age_band=46-60/welcome_message': 0.125, 'age_band=60+/voice': 0.15, 'age_band=60+/welcome_message': 0.125, 'default/voice': 0.15, 'default/welcome_message': 0.125}
    dry_run: {"allocations": [{"arms": {"W1": {"n": 640, "rate": 0.4112, "status": "observed"}, "W2": {"n": 60, "rate": 0.4194, "status": "observed"}, "W3": {"n": 48, "rate": 0.48, "status": "observed"}}, "ci95_new": [0.3796, 0.4564], "cohort": "age_band=18-30", "dim": "we...(truncated; see --json)
    approval apr_00008: APPROVED (decided_at Day 3 13:26, observed_at Day 3 13:45) by policy approver of ks_cancel; the sim exposes no approver names
    policy: approver hours [10, 19], latency [20, 120] min, ttl 12 h, max 4 requests/24h; objective {'guardrail': {'pickup_rate_max_drop': 0.02}, 'primary': 'engagement_rate'}
  proposal lifecycle:
    Day 3 11:45 DRAFT
    Day 3 11:45 INTENT
    Day 3 11:45 PENDING approval created
    Day 3 13:26 APPROVED decided_at Day 3 13:26, observed_at Day 3 13:45 approved
    Day 3 13:45 apply_intent
    Day 3 13:45 APPLIED applied
    Day 3 14:00 MONITORING monitoring after apply
    Day 4 13:45 CLOSED monitoring window over
  our decisions for this change:
    Day 3 11:45 proposal_pending: ks_cancel:9:halluc_fix: PENDING
      inputs: {"approval_id": "apr_00008", "expires_minute": 5745, "filed_minute": 5025, "from": "INTENT", "note": "approval created", "proposal_id": "ks_cancel:9:halluc_fix"}
    Day 3 13:45 proposal_approved: ks_cancel:9:halluc_fix: APPROVED
      inputs: {"apply_by_minute": 5246, "approval_id": "apr_00008", "decided_at": "2027-01-07T13:26:00+05:30", "from": "PENDING", "note": "approved", "proposal_id": "ks_cancel:9:halluc_fix"}
    Day 3 13:45 proposal_apply_intent: ks_cancel:9:halluc_fix: apply_intent
      inputs: {"approval_id": "apr_00008", "proposal_id": "ks_cancel:9:halluc_fix"}
    Day 3 13:45 proposal_applied: ks_cancel:9:halluc_fix: APPLIED
      inputs: {"applied_minute": 5145, "applied_version": 9, "approval_id": "apr_00008", "changed_dims": ["welcome_message", "voice", "prompt_version"], "from": "APPROVED", "note": "applied", "proposal_id": "ks_cancel:9:halluc_fix"}
    Day 3 13:45 config_observed: v9 by controller_approved changed ['welcome_message', 'voice', 'prompt_version']
      inputs: {"approval_id": "apr_00008", "event_id": 235784, "proposal_id": "ks_cancel:9:halluc_fix"}
  evidence (newest detector/test rows in the 24h before the proposal):
    Day 3 00:00 did_curve_fit: fatigue curve refit: tau=192h fitted=True points=37
      inputs: {"fitted": true, "hs": [1.0, 0.9635, 0.9096, 0.8942, 0.8729, 0.8293, 0.8222, 0.8173, 0.7777, 0.7754, 0.7667], "n_obs": 37, "tau_hours": 192.0, "xs": [47.6, 481.6, 584.3, 2125.6, 4154.7, 4228.2, 5944.0, 7450.6, 7530.5, 10012.8, 14397.2]}
    Day 3 11:00 halluc_eval: P1: flags 1.46% vs 1.37% (n=1163, p=4.33e-01, ceiling 3.0%)
      inputs: {"adherence_drop": 0.0008, "base_n": 16439, "base_rate": 0.013686963927246183, "baseline_source": "history", "ceiling": 0.030000000000000027, "flags": 17, "n": 1163, "p": 0.4328579599203641, "prompt": "P1", "rate": 0.014617368873602751, "rate_lb": 0.00704, "tr...(truncated; see --json)
    Day 3 11:45 incident_opened: halluc incident opened
      inputs: {"bad_prompt": "P2", "baseline_prompt": null, "candidates": [], "credits_spent": 0.0, "edit": {"actor": "supervisor", "minute": 5010, "version": 8}, "holds": true, "incident_id": 2, "kind": "bad_prompt_day0", "recheck_fail": 0, "reverts_checked": false, "stats...(truncated; see --json)
    Day 3 11:45 did_eval: caller-ID evaluation: D1=tested, D2=flagged, D3=tested
      inputs: {"best_step": {"did": "D3", "drop": 0.1223, "n": 369, "n_peers": 331, "n_ref": 2223, "p": 0.16203669144918703, "q_ref": 1.1357, "q_window": 0.9848, "share_ref": 0.49, "share_window": 0.5271, "solo": false, "window_h": 2, "z": -0.986}, "curve": {"fitted": true,...(truncated; see --json)
  post-apply monitoring:
    Day 3 13:45 config_observed: v9 by controller_approved changed ['welcome_message', 'voice', 'prompt_version']
      inputs: {"approval_id": "apr_00008", "event_id": 235784, "proposal_id": "ks_cancel:9:halluc_fix"}
    Day 3 14:00 experiment_applied: experiment_update for welcome_message is live (Day 3 13:45): W1 72.5%, W2 20.0%, W3 7.5%
      inputs: {"kind": "experiment_update", "phase": "running"}
    Day 3 14:00 experiment_applied: experiment_update for voice is live (Day 3 13:45): V1 92.5%, V2 7.5%
      inputs: {"kind": "experiment_update", "phase": "running"}
    Day 3 17:30 incident_verified: P1: flags 1.23%, engagement ok
      inputs: {"engagement_ok": true, "flag_rate": 0.01229, "flags_ok": true, "margin": 0.01, "n": 407, "p": 0.0, "prompt": "P1"}
    Day 3 17:30 incident_closed: halluc incident closed: fixed by P1; flag rate non-inferior to baseline, engagement inside guardrail
      inputs: {"incident_id": 2}
    Day 3 21:00 experiment_look: welcome_message all: W2 lift +9.2% z 1.87 bound 2.96; W3 lift -3.6% z -0.62 bound 3.45 [look 2]
      inputs: {"alpha": 0.020000000000000004, "control": "W1", "dim": "welcome_message", "drop": [], "exposure_days": 3.38, "family": ["W2", "W3"], "look_index": 2, "ramp": [], "records": {"W2": {"alpha_adj": 0.01, "boundary": 2.9637024887120944, "clusters": 3729, "info": 4...(truncated; see --json)
    Day 3 21:00 experiment_look: welcome_message g0: W2 lift +8.3% z 1.26 bound 5.18; W3 lift +9.4% z 1.21 bound 5.70 [look 1]
      inputs: {"alpha": 0.0025000000000000005, "control": "W1", "dim": "welcome_message", "drop": [], "exposure_days": 3.38, "family": ["W2", "W3"], "look_index": 1, "ramp": ["W3"], "records": {"W2": {"alpha_adj": 0.00125, "boundary": 5.177639107690242, "clusters": 2327, "i...(truncated; see --json)
    Day 3 21:00 experiment_look: welcome_message g1: W2 lift +11.4% z 1.61 bound 5.59; W3 lift -21.1% z -2.42 [look 1]
      inputs: {"alpha": 0.0025000000000000005, "control": "W1", "dim": "welcome_message", "drop": ["W3"], "exposure_days": 3.38, "family": ["W2", "W3"], "look_index": 1, "ramp": [], "records": {"W2": {"alpha_adj": 0.00125, "boundary": 5.585725157559861, "clusters": 1402, "i...(truncated; see --json)
    Day 3 21:00 experiment_look: voice all: V2 lift -3.7% z -0.67
      inputs: {"alpha": 0.020000000000000004, "control": "V1", "dim": "voice", "drop": [], "exposure_days": 3.38, "family": ["V2", "V3", "V4"], "look_index": 0, "ramp": [], "records": {"V2": {"clusters": 3526, "info": 306.66596996779754, "lift": -0.037262495843943144, "n_ar...(truncated; see --json)
    Day 3 21:00 experiment_look: voice g0: V2 lift -7.7% z -1.05
      inputs: {"alpha": 0.0025000000000000005, "control": "V1", "dim": "voice", "drop": [], "exposure_days": 3.38, "family": ["V2", "V3", "V4"], "look_index": 0, "ramp": [], "records": {"V2": {"clusters": 2201, "info": 168.6177699414488, "lift": -0.07737204586915714, "n_arm...(truncated; see --json)
    Day 3 21:00 experiment_look: voice g1: V2 lift +4.6% z 0.57
      inputs: {"alpha": 0.0025000000000000005, "control": "V1", "dim": "voice", "drop": [], "exposure_days": 3.38, "family": ["V2", "V3", "V4"], "look_index": 0, "ramp": ["V2"], "records": {"V2": {"clusters": 1325, "info": 157.79274036334337, "lift": 0.04609682034023632, "n...(truncated; see --json)
    Day 4 00:00 schedule_plan: per-cohort call times: est. pickup 0.249 -> 0.249 (-0.0%), est. engagement shift +0.0001 (max drop 0.02): not material
      inputs: {"cohorts": ["age_band=31-45", "age_band=18-30", "age_band=46-60", "age_band=60+"], "current_tables": {"age_band=18-30": {"10": 0.9328, "11": 0.8937, "12": 1.1064, "13": 1.0658, "14": 0.892, "15": 0.8627, "16": 0.9671, "17": 1.1273, "18": 1.1701, "19": 1.099, ...(truncated; see --json)
    Day 4 11:00 halluc_eval: P1: flags 1.46% vs 1.37% (n=957, p=4.44e-01, ceiling 3.0%)
      inputs: {"adherence_drop": -0.0008, "base_n": 16439, "base_rate": 0.013686963927246183, "baseline_source": "history", "ceiling": 0.030000000000000027, "flags": 14, "n": 957, "p": 0.44373343261889253, "prompt": "P1", "rate": 0.014629049111807733, "rate_lb": 0.00656, "t...(truncated; see --json)
    Day 4 11:45 did_flag_expired: flag on D2 expired after the cooldown; re-probing it at the re-probe cap
      inputs: {"did": "D2", "flagged": {"drop": 0.6932, "minute": 3585, "n": 244, "p": 3.599720543147013e-07, "q_est": 0.3068}}
    Day 4 11:45 did_eval: caller-ID evaluation: D1=tested, D2=reprobe, D3=tested
      inputs: {"best_step": {"did": "D1", "drop": 0.0312, "n": 527, "n_peers": 573, "n_ref": 2388, "p": 0.3845970764266019, "q_ref": 0.9045, "q_window": 0.9136, "share_ref": 0.4975, "share_window": 0.4791, "solo": false, "window_h": 3, "z": -0.293}, "curve": {"fitted": true...(truncated; see --json)
    Day 4 11:45 config_observed: v10 by controller_auto changed ['caller_id']
      inputs: {"approval_id": null, "event_id": 247691, "proposal_id": "ks_cancel:10:did_probe"}
  superseded by v10 (controller_auto) at Day 4 11:45, dims ["caller_id"], proposal ks_cancel:10:did_probe: Probe/spread caller IDs within the safe probe cap (h-bar 0.80): default: D1 50.0%->49.6%, D2 0.0%->0.7%, D3 50.0%->49.6%
```

## public_02 - auto-applied change: ks_cancel v6 (did_evacuation of the flagged caller ID)

```
$ python -m controller why --db <db> --workflow ks_cancel --at 'Day 2 12:00'
why ks_cancel at Day 2 12:00
  active version v7 by controller_auto (observed Day 2 12:00, dims ["caller_id"])
    prompt P1, cohorts 4, allocations {"default": {"caller_id": {"D1": 0.5, "D3": 0.5}, "voice": {"V1": 0.775, "V2": 0.075, "V3": 0.075, "V4": 0.075}, "welcome_message": {"W1": 0.85, "W2": 0.075, "W3": 0.075}}}
  proposal ks_cancel:7:did_evacuation [auto] state=CLOSED base=v6 applied=v7 at Day 2 12:00
    summary: Evacuate flagged caller ID D2 (pickup ratio vs peers x0.31): default: D1 50.0%->50.0%, D2 14.3%->0.0%, D3 35.7%->50.0%
    rationale: caller-ID load spreading; statuses: D1=tested, D2=flagged, D3=tested; default: D1 50.0%->50.0%, D2 14.3%->0.0%, D3 35.7%->50.0%
    impact=0.0 affected_leads=4578 tv={'age_band=18-30/caller_id': 0.143333, 'age_band=31-45/caller_id': 0.143333, 'age_band=46-60/caller_id': 0.143333, 'age_band=60+/caller_id': 0.143333, 'default/caller_id': 0.143333}
    auto-applied under the workflow's auto_apply policy (no approval)
  proposal lifecycle:
    Day 2 12:00 DRAFT
    Day 2 12:00 INTENT
    Day 2 12:00 AUTO_APPLIED auto-applied
    Day 2 12:15 MONITORING monitoring after apply
    Day 3 12:00 CLOSED monitoring window over
  our decisions for this change:
    Day 2 12:00 proposal_auto_applied: ks_cancel:7:did_evacuation: AUTO_APPLIED
      inputs: {"applied_minute": 3600, "applied_version": 7, "approval_id": null, "changed_dims": ["caller_id"], "from": "INTENT", "note": "auto-applied", "proposal_id": "ks_cancel:7:did_evacuation"}
    Day 2 12:00 config_observed: v7 by controller_auto changed ['caller_id']
      inputs: {"approval_id": null, "event_id": 220497, "proposal_id": "ks_cancel:7:did_evacuation"}
  evidence (newest detector/test rows in the 24h before the proposal):
    Day 1 14:00 did_tested: D3 passes: not worse than peers at its load
      inputs: {"dials": 151, "did": "D3", "peer": {"connects": 50, "did": "D3", "expected": 48.73, "load": 64.6, "n": 151, "peer_load": 11148.6, "q": 1.026, "z_weak": 1.569}}
    Day 2 00:00 did_curve_fit: fatigue curve refit: tau=192h fitted=True points=34
      inputs: {"fitted": true, "hs": [1.0, 0.9635, 0.9096, 0.8961, 0.8729, 0.8293, 0.8222, 0.8173, 0.7777, 0.7754, 0.7698], "n_obs": 34, "tau_hours": 192.0, "xs": [47.6, 481.6, 584.3, 2243.8, 4154.7, 4228.2, 5944.0, 7450.6, 7530.5, 10012.8, 14295.9]}
    Day 2 11:45 incident_opened: did_flagged incident opened
      inputs: {"did": "D2", "incident_id": 1, "q_est": 0.3057, "step": {"did": "D2", "drop": 0.6932, "n": 244, "n_peers": 456, "n_ref": 1916, "p": 3.599720543147013e-07, "q_ref": 0.9367, "q_window": 0.2864, "share_ref": 0.3992, "share_window": 0.3486, "solo": false, "window...(truncated; see --json)
    Day 2 11:45 did_flagged: FLAGGED D2: pickup ratio vs peers fell 69% (p=3.6e-07, 244 dials in 2h vs 1916 in the reference); incident mode
      inputs: {"curve": {"fitted": true, "hs": [1.0, 0.9635, 0.9096, 0.8961, 0.8729, 0.8293, 0.8222, 0.8173, 0.7777, 0.7754, 0.7698], "n_obs": 34, "tau_hours": 192.0, "xs": [47.6, 481.6, 584.3, 2243.8, 4154.7, 4228.2, 5944.0, 7450.6, 7530.5, 10012.8, 14295.9]}, "step": {"di...(truncated; see --json)
    Day 2 12:00 halluc_eval: P1: flags 1.34% vs 1.37% (n=1123, p=5.75e-01, ceiling 3.0%)
      inputs: {"adherence_drop": 0.0022, "base_n": 16439, "base_rate": 0.013686963927246183, "baseline_source": "history", "ceiling": 0.030000000000000027, "flags": 15, "n": 1123, "p": 0.574795412790434, "prompt": "P1", "rate": 0.013357079252003561, "rate_lb": 0.00615, "tri...(truncated; see --json)
    Day 2 12:00 did_eval: caller-ID evaluation: D1=tested, D2=flagged, D3=tested
      inputs: {"best_step": {"did": "D3", "drop": 0.1065, "n": 261, "n_peers": 276, "n_ref": 1047, "p": 0.22968553494191812, "q_ref": 1.1846, "q_window": 1.0157, "share_ref": 0.363, "share_window": 0.486, "solo": false, "window_h": 3, "z": -0.74}, "curve": {"fitted": true, ...(truncated; see --json)
  post-apply monitoring:
    Day 2 12:00 config_observed: v7 by controller_auto changed ['caller_id']
      inputs: {"approval_id": null, "event_id": 220497, "proposal_id": "ks_cancel:7:did_evacuation"}
    Day 2 21:00 experiment_look: welcome_message all: W2 lift +12.7% z 2.03; W3 lift -3.1% z -0.45
      inputs: {"alpha": 0.020000000000000004, "control": "W1", "dim": "welcome_message", "drop": [], "exposure_days": 2.38, "family": ["W2", "W3"], "look_index": 0, "ramp": [], "records": {"W2": {"clusters": 2780, "info": 288.7535072634359, "lift": 0.12700369616892337, "n_a...(truncated; see --json)
    Day 2 21:00 experiment_look: welcome_message g0: W2 lift +10.0% z 1.14; W3 lift +14.2% z 1.58
      inputs: {"alpha": 0.0025000000000000005, "control": "W1", "dim": "welcome_message", "drop": [], "exposure_days": 2.38, "family": ["W2", "W3"], "look_index": 0, "ramp": ["W3"], "records": {"W2": {"clusters": 1739, "info": 144.9053779615245, "lift": 0.0997161590861888, ...(truncated; see --json)
    Day 2 21:00 experiment_look: welcome_message g1: W2 lift +16.7% z 2.02; W3 lift -26.1% z -2.50
      inputs: {"alpha": 0.0025000000000000005, "control": "W1", "dim": "welcome_message", "drop": [], "exposure_days": 2.38, "family": ["W2", "W3"], "look_index": 0, "ramp": [], "records": {"W2": {"clusters": 1041, "info": 171.50239108304947, "lift": 0.16659241332927066, "n...(truncated; see --json)
    Day 2 21:00 experiment_look: voice all: V2 lift -6.5% z -0.96 bound 4.82; V3 lift -11.3% z -1.70 [look 1]
      inputs: {"alpha": 0.020000000000000004, "control": "V1", "dim": "voice", "drop": ["V3"], "exposure_days": 2.38, "family": ["V2", "V3", "V4"], "look_index": 1, "ramp": [], "records": {"V2": {"alpha_adj": 0.006667, "boundary": 4.816761897283543, "clusters": 2572, "info"...(truncated; see --json)
    Day 2 21:00 experiment_look: voice g0: V2 lift -8.5% z -0.98; V3 lift -10.5% z -1.18
      inputs: {"alpha": 0.0025000000000000005, "control": "V1", "dim": "voice", "drop": [], "exposure_days": 2.38, "family": ["V2", "V3", "V4"], "look_index": 0, "ramp": [], "records": {"V2": {"clusters": 1607, "info": 120.59196243020288, "lift": -0.08499922416838201, "n_ar...(truncated; see --json)
    Day 2 21:00 experiment_look: voice g1: V2 lift +1.3% z 0.13; V3 lift -11.4% z -1.16
      inputs: {"alpha": 0.0025000000000000005, "control": "V1", "dim": "voice", "drop": [], "exposure_days": 2.38, "family": ["V2", "V3", "V4"], "look_index": 0, "ramp": [], "records": {"V2": {"clusters": 965, "info": 103.81713417336368, "lift": 0.012560621753235468, "n_arm...(truncated; see --json)
    Day 2 23:00 incident_closed: did_flagged incident closed: D2 evacuated: observed share 0.00% over the trailing window, config v7 share 0 in every key
      inputs: {"incident_id": 1}
    Day 3 00:00 schedule_plan: per-cohort call times: est. pickup 0.249 -> 0.249 (-0.0%), est. engagement shift +0.0001 (max drop 0.02): not material
      inputs: {"cohorts": ["age_band=31-45", "age_band=18-30", "age_band=46-60", "age_band=60+"], "current_tables": {"age_band=18-30": {"10": 0.9328, "11": 0.8937, "12": 1.1064, "13": 1.0658, "14": 0.892, "15": 0.8627, "16": 0.9671, "17": 1.1273, "18": 1.1701, "19": 1.099, ...(truncated; see --json)
    Day 3 11:00 halluc_eval: P1: flags 1.46% vs 1.37% (n=1163, p=4.33e-01, ceiling 3.0%)
      inputs: {"adherence_drop": 0.0008, "base_n": 16439, "base_rate": 0.013686963927246183, "baseline_source": "history", "ceiling": 0.030000000000000027, "flags": 17, "n": 1163, "p": 0.4328579599203641, "prompt": "P1", "rate": 0.014617368873602751, "rate_lb": 0.00704, "tr...(truncated; see --json)
    Day 3 11:30 did_eval: caller-ID evaluation: D1=tested, D2=flagged, D3=tested
      inputs: {"best_step": {"did": "D3", "drop": 0.0871, "n": 322, "n_peers": 278, "n_ref": 2223, "p": 0.2613889872832573, "q_ref": 1.1357, "q_window": 1.0245, "share_ref": 0.49, "share_window": 0.5367, "solo": false, "window_h": 2, "z": -0.639}, "curve": {"fitted": true, ...(truncated; see --json)
    Day 3 11:30 config_observed: v8 by supervisor changed ['prompt_version']
      inputs: {"approval_id": null, "event_id": 233756, "proposal_id": null}
  superseded by v8 (supervisor) at Day 3 11:30, dims ["prompt_version"], proposal None: None
```

## public_02 - per-lead: ks_cancel:l00024079 (calls on Day 3, the decisions behind them)

```
$ python -m controller why --db <db> --lead ks_cancel:l00024079 --day 3
lead ks_cancel:l00024079 person ks_cancel:p0009326 workflow ks_cancel campaign ks_cancel:c0017 (created Day 2 08:00, cell 131330), day 3
  Day 3 13:56 attempt 1 welcome W1 voice V1 DID D1 prompt P1 cohort age_band=18-30 connected=False engaged=False
    allocation from config v9; prompt from config v9 active at the call time
  Day 3 19:50 attempt 2 welcome W1 voice V1 DID D3 prompt P1 cohort age_band=18-30 connected=False engaged=False
    allocation from config v9; prompt from config v9 active at the call time
  decisions behind config v9:
    by controller_approved at Day 3 13:45 dims ["welcome_message", "voice", "prompt_version"]
    proposal ks_cancel:9:halluc_fix: Revert P2 (set by supervisor Day 3 11:30) to P1: flags 5.5% vs failed Day-0 validation (n=200, p=0.0e+00); validation val_00001 pass 0.987; voice experiment: drop V3 (lift -11.3%, z -1.70, recent z -1.20); new split V1 92.5%, V2 7.5%; welcome_message experiment: ramp W2 (lift +26.5%, z 3.41, n 150);
    rationale: Revert P2 (set by supervisor Day 3 11:30) to P1: flags 5.5% vs failed Day-0 validation (n=200, p=0.0e+00); validation val_00001 pass 0.987. Fix source: known_good; engagement is verified after apply. | voice experiment: drop V3 (lift -11.3%, z -1.70, recent z -1.20); new split V1 92.5%, V2 7.5%. Ramp: after >= 1 day and >= 100 connects, point estimate >= control; drop at z <= -1. | welcome_message experiment: ramp W2 (lift +26.5%, z 3.41, n 150); new split W1 72.5%, W2 20.0%, W3 7.5%. Ramp: after >= 1 day and >= 100 connects, point estimate >= control; drop at z <= -1.
    approval apr_00008 APPROVED decided_at Day 3 13:26 observed_at Day 3 13:45 by policy approver of ks_cancel
    Day 3 11:45 proposal_pending: ks_cancel:9:halluc_fix: PENDING
      inputs: {"approval_id": "apr_00008", "expires_minute": 5745, "filed_minute": 5025, "from": "INTENT", "note": "approval created", "proposal_id": "ks_cancel:9:halluc_fix"}
    Day 3 13:45 proposal_approved: ks_cancel:9:halluc_fix: APPROVED
      inputs: {"apply_by_minute": 5246, "approval_id": "apr_00008", "decided_at": "2027-01-07T13:26:00+05:30", "from": "PENDING", "note": "approved", "proposal_id": "ks_cancel:9:halluc_fix"}
    Day 3 13:45 proposal_apply_intent: ks_cancel:9:halluc_fix: apply_intent
      inputs: {"approval_id": "apr_00008", "proposal_id": "ks_cancel:9:halluc_fix"}
    Day 3 13:45 proposal_applied: ks_cancel:9:halluc_fix: APPLIED
      inputs: {"applied_minute": 5145, "applied_version": 9, "approval_id": "apr_00008", "changed_dims": ["welcome_message", "voice", "prompt_version"], "from": "APPROVED", "note": "applied", "proposal_id": "ks_cancel:9:halluc_fix"}
    Day 3 13:45 config_observed: v9 by controller_approved changed ['welcome_message', 'voice', 'prompt_version']
      inputs: {"approval_id": "apr_00008", "event_id": 235784, "proposal_id": "ks_cancel:9:halluc_fix"}
```

## public_02 - supervisor edit respected: nw_renewal v11 (Day 5 15:00, voice) and the next controller change

```
$ python -m controller why --db <db> --workflow nw_renewal --at 'Day 6 12:00'
why nw_renewal at Day 6 12:00
  active version v12 by controller_approved (observed Day 6 11:00, dims ["welcome_message"])
    prompt P1, cohorts 4, allocations {"default": {"caller_id": {"D1": 0.25, "D2": 0.25, "D3": 0.25, "D4": 0.25}, "voice": {"V2": 1.0}, "welcome_message": {"W1": 0.8, "W2": 0.2}}}
  proposal nw_renewal:10:experiment_update [approval] state=CLOSED base=v11 applied=v12 at Day 6 11:00
    summary: welcome_message experiment: drop W3 (lift +0.2%, z 0.05, recent z -1.52); new split W1 80.0%, W2 20.0%
    rationale: welcome_message experiment: drop W3 (lift +0.2%, z 0.05, recent z -1.52); new split W1 80.0%, W2 20.0%. Ramp: after >= 1 day and >= 100 connects, point estimate >= control; drop at z <= -1.
    impact=0.0 affected_leads=2583 tv={'age_band=18-30/welcome_message': 0.2, 'age_band=31-45/welcome_message': 0.2, 'age_band=46-60/welcome_message': 0.2, 'age_band=60+/welcome_message': 0.2, 'default/welcome_message': 0.2}
    dry_run: {"allocations": [{"arms": {"W1": {"n": 318, "rate": 0.4781, "status": "observed"}, "W2": {"n": 112, "rate": 0.5, "status": "observed"}, "W3": {"n": 114, "rate": 0.4224, "status": "observed"}}, "ci95_new": [0.435, 0.53], "cohort": "age_band=18-30", "dim": "welc...(truncated; see --json)
    approval apr_00012: APPROVED (decided_at Day 6 10:34, observed_at Day 6 11:00) by policy approver of nw_renewal; the sim exposes no approver names
    policy: approver hours [10, 19], latency [30, 240] min, ttl 24 h, max 3 requests/24h; objective {'guardrail': {'pickup_rate_max_drop': 0.02}, 'primary': 'engagement_rate'}
  proposal lifecycle:
    Day 6 10:00 DRAFT
    Day 6 10:00 INTENT
    Day 6 10:00 PENDING approval created
    Day 6 10:34 APPROVED decided_at Day 6 10:34, observed_at Day 6 11:00 approved
    Day 6 11:00 apply_intent
    Day 6 11:00 APPLIED applied
    Day 6 11:15 MONITORING monitoring after apply
    Day 7 11:00 CLOSED monitoring window over
  our decisions for this change:
    Day 6 10:00 proposal_pending: nw_renewal:10:experiment_update: PENDING
      inputs: {"approval_id": "apr_00012", "expires_minute": 10680, "filed_minute": 9240, "from": "INTENT", "note": "approval created", "proposal_id": "nw_renewal:10:experiment_update"}
    Day 6 11:00 proposal_approved: nw_renewal:10:experiment_update: APPROVED
      inputs: {"apply_by_minute": 9394, "approval_id": "apr_00012", "decided_at": "2027-01-10T10:34:00+05:30", "from": "PENDING", "note": "approved", "proposal_id": "nw_renewal:10:experiment_update"}
    Day 6 11:00 proposal_apply_intent: nw_renewal:10:experiment_update: apply_intent
      inputs: {"approval_id": "apr_00012", "proposal_id": "nw_renewal:10:experiment_update"}
    Day 6 11:00 proposal_applied: nw_renewal:10:experiment_update: APPLIED
      inputs: {"applied_minute": 9300, "applied_version": 12, "approval_id": "apr_00012", "changed_dims": ["welcome_message"], "from": "APPROVED", "note": "applied", "proposal_id": "nw_renewal:10:experiment_update"}
    Day 6 11:00 config_observed: v12 by controller_approved changed ['welcome_message']
      inputs: {"approval_id": "apr_00012", "event_id": 274429, "proposal_id": "nw_renewal:10:experiment_update"}
  evidence (newest detector/test rows in the 24h before the proposal):
    Day 6 00:00 did_curve_fit: fatigue curve refit: tau=48h fitted=True points=50
      inputs: {"fitted": true, "hs": [1.0, 0.9706, 0.9612, 0.9114, 0.8955, 0.8939, 0.881, 0.8601, 0.8435, 0.8282, 0.8214, 0.8115], "n_obs": 50, "tau_hours": 48.0, "xs": [489.9, 1262.0, 1327.1, 1773.7, 2268.8, 2823.0, 3102.3, 3402.6, 3504.4, 3525.8, 3545.3, 3586.9]}
    Day 6 10:00 halluc_eval: P1: flags 0.86% vs 1.30% (n=926, p=9.09e-01, ceiling 3.0%)
      inputs: {"adherence_drop": -0.002, "base_n": 13382, "base_rate": 0.013002540726348827, "baseline_source": "history", "ceiling": 0.030000000000000027, "flags": 8, "n": 926, "p": 0.9092899054485717, "prompt": "P1", "rate": 0.008639308855291577, "rate_lb": 0.00304, "trig...(truncated; see --json)
    Day 6 10:00 did_eval: caller-ID evaluation: D1=tested, D2=tested, D3=tested, D4=tested
      inputs: {"best_step": null, "curve": {"fitted": true, "hs": [1.0, 0.9706, 0.9612, 0.9114, 0.8955, 0.8939, 0.881, 0.8601, 0.8435, 0.8282, 0.8214, 0.8115], "n_obs": 50, "tau_hours": 48.0, "xs": [489.9, 1262.0, 1327.1, 1773.7, 2268.8, 2823.0, 3102.3, 3402.6, 3504.4, 3525...(truncated; see --json)
  post-apply monitoring:
    Day 6 11:00 config_observed: v12 by controller_approved changed ['welcome_message']
      inputs: {"approval_id": "apr_00012", "event_id": 274429, "proposal_id": "nw_renewal:10:experiment_update"}
    Day 6 11:15 experiment_applied: experiment_update for welcome_message is live (Day 6 11:00): W1 80.0%, W2 20.0%
      inputs: {"kind": "experiment_update", "phase": "running"}
    Day 6 21:00 experiment_look: welcome_message all: W2 lift +1.8% z 0.60
      inputs: {"alpha": 0.020000000000000004, "control": "W1", "dim": "welcome_message", "drop": ["W2"], "exposure_days": 6.33, "family": ["W2", "W3"], "look_index": 0, "ramp": [], "records": {"W2": {"clusters": 4980, "info": 1100.1630167456813, "lift": 0.018135734334226106...(truncated; see --json)
    Day 6 21:00 experiment_look: welcome_message g0: W2 lift -0.0% z -0.01 bound 3.31 [look 3]
      inputs: {"alpha": 0.0025000000000000005, "control": "W1", "dim": "welcome_message", "drop": [], "exposure_days": 6.33, "family": ["W2", "W3"], "look_index": 3, "ramp": [], "records": {"W2": {"alpha_adj": 0.00125, "boundary": 3.313451337891358, "clusters": 3029, "info"...(truncated; see --json)
    Day 6 21:00 experiment_look: welcome_message g1: W2 lift +3.2% z 0.75 bound 3.36 [look 3]
      inputs: {"alpha": 0.0025000000000000005, "control": "W1", "dim": "welcome_message", "drop": [], "exposure_days": 6.33, "family": ["W2", "W3"], "look_index": 3, "ramp": [], "records": {"W2": {"alpha_adj": 0.00125, "boundary": 3.3572462095092916, "clusters": 1951, "info...(truncated; see --json)
    Day 6 21:00 experiment_conclude: End welcome_message experiment: no challenger left; all traffic back to control W1
      inputs: {"control": "W1", "dim": "welcome_message"}
    Day 7 00:00 schedule_plan: per-cohort call times: est. pickup 0.275 -> 0.276 (+0.3%), est. engagement shift -0.0003 (max drop 0.02): not material
      inputs: {"cohorts": ["age_band=31-45", "age_band=18-30", "age_band=46-60", "age_band=60+"], "current_tables": {}, "estimate": {"engagement_drop": 0.00031, "engagement_new": 0.54957, "engagement_old": 0.54987, "pickup_new": 0.2761, "pickup_old": 0.27517, "rel_lift": 0....(truncated; see --json)
    Day 7 11:00 halluc_eval: P1: flags 1.04% vs 1.30% (n=963, p=7.98e-01, ceiling 3.0%)
      inputs: {"adherence_drop": -0.0021, "base_n": 13382, "base_rate": 0.013002540726348827, "baseline_source": "history", "ceiling": 0.030000000000000027, "flags": 10, "n": 963, "p": 0.7979895555946195, "prompt": "P1", "rate": 0.010384215991692628, "rate_lb": 0.00406, "tr...(truncated; see --json)
    Day 7 11:00 did_eval: caller-ID evaluation: D1=tested, D2=tested, D3=tested, D4=tested
      inputs: {"best_step": {"did": "D1", "drop": 0.4081, "n": 163, "n_peers": 437, "n_ref": 866, "p": 0.0013344419038445595, "q_ref": 1.0753, "q_window": 0.6383, "share_ref": 0.2406, "share_window": 0.2717, "solo": false, "window_h": 3, "z": -3.004}, "curve": {"fitted": tr...(truncated; see --json)
    Day 7 11:00 config_observed: v13 by controller_approved changed ['welcome_message']
      inputs: {"approval_id": "apr_00014", "event_id": 288136, "proposal_id": "nw_renewal:11:experiment_conclude"}
  superseded by v13 (controller_approved) at Day 7 11:00, dims ["welcome_message"], proposal nw_renewal:11:experiment_conclude: End welcome_message experiment: no challenger left; all traffic back to control W1
```

## public_02 - supervisor-edit respect (config history, final02)

Supervisor edits (actor = supervisor) in config_versions:

- ks_cancel v8, Day 3 11:30, prompt_version P1 -> P2 (the bad prompt). Only changed afterwards by v9 (controller_approved, approval apr_00008, proposal ks_cancel:9:halluc_fix), whose summary names it: "Revert P2 (set by supervisor Day 3 11:30) to P1". MTTR 135 min, fixed_by controller_approved.
- nw_renewal v11, Day 5 15:00, voice {V1 .5, V2 .5} -> {V2: 1.0}. The controller's later nw_renewal versions v12 (Day 6 11:00, dims welcome_message, apr_00012) and v13 (Day 7 11:00, dims welcome_message) leave voice at {V2: 1.0}; no controller version after v11 touches the voice dimension (checked in config_versions.body).
