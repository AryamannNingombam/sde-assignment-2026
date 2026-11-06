# Grade report — bad_default

## Outcomes vs baseline (no-op controller)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| ks_cancel | 0.391 | +8.3% | 0.258 | +5.4% | 0.526 | +2.4% | 5% | 79 (224) |
| nw_kyc | 0.392 | +4.1% | 0.250 | +2.6% | 0.613 | +1.3% | 0% | 27 (26) |
| nw_renewal | 0.449 | +6.8% | 0.278 | +5.6% | 0.547 | -0.3% | 12% | 44 (53) |
| ALL | 0.410 | +6.9% | 0.263 | +4.9% | 0.550 | +1.1% | 7% | 150 (303) |

## Changes applied by the controller

18 applied — neutral: 9, beneficial: 8, harmful: 1

- ks_cancel v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.004 → **neutral**
- nw_renewal v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.004 → **neutral**
- nw_kyc v2 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.008 → **neutral**
- nw_renewal v3 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'schedule'] engageΔ=+0.015 didΔ=+0.000 → **beneficial**
- ks_cancel v3 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'prompt_version', 'schedule'] engageΔ=-0.017 didΔ=+0.000 → **harmful**
- nw_renewal v4 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- ks_cancel v4 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.030 → **beneficial**
- ks_cancel v5 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.019 → **neutral**
- nw_renewal v5 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.050 → **beneficial**
- nw_kyc v3 (controller_approved) dims=['cohorts', 'schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nw_renewal v6 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.026 didΔ=+0.000 → **beneficial**
- ks_cancel v6 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.022 didΔ=+0.000 → **beneficial**
- nw_renewal v7 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.009 → **neutral**
- ks_cancel v7 (controller_approved) dims=['welcome_message'] engageΔ=+0.021 didΔ=+0.000 → **beneficial**
- nw_kyc v4 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.154 → **beneficial**
- ks_cancel v8 (controller_approved) dims=['voice'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nw_renewal v8 (controller_approved) dims=['welcome_message'] engageΔ=+0.049 didΔ=+0.000 → **beneficial**
- nw_renewal v9 (controller_approved) dims=['voice'] engageΔ=-0.002 didΔ=+0.000 → **neutral**

## Governance

```
{
  "approval_requests": 14,
  "decisions": {
    "rejected": 3,
    "approved": 11,
    "expired": 0
  },
  "rejection_reasons": {
    "approver declined (judgement call)": 3
  },
  "applied_via_approval": 11,
  "auto_applied": 7,
  "auto_apply_rejected": 0,
  "apply_conflicts": 0,
  "lapsed": 0,
  "peak_requests_per_24h": {
    "nw_renewal": 1,
    "nw_kyc": 1,
    "ks_cancel": 1
  }
}
```

## Incidents

```
[]
```

## Decaying variants — share of in-population calls still on the variant, by day after onset

```
{
  "nw_renewal:welcome_message=W3": {
    "3": 0.213,
    "4": 0.2,
    "5": 0.201,
    "6": 0.093,
    "7": 0.0
  }
}
```

Credits used: 30 · validation runs: 12 · LLM fix calls: 0