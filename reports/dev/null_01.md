# Grade report — null_01

## Outcomes vs baseline (no-op controller)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| ks_cancel | 0.364 | +3.0% | 0.254 | +3.9% | 0.500 | -1.3% | 0% | 53 (61) |
| nw_kyc | 0.451 | +21.9% | 0.292 | +22.6% | 0.591 | -2.5% | 0% | 23 (19) |
| nw_renewal | 0.449 | +5.8% | 0.279 | +6.6% | 0.550 | -0.1% | 0% | 45 (50) |
| ALL | 0.411 | +7.9% | 0.270 | +8.3% | 0.537 | -0.8% | 0% | 121 (130) |

## Changes applied by the controller

19 applied — neutral: 15, beneficial: 4

- ks_cancel v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.004 → **neutral**
- nw_renewal v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.004 → **neutral**
- ks_cancel v3 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nw_kyc v2 (controller_approved) dims=['cohorts', 'caller_id', 'schedule'] engageΔ=+0.000 didΔ=+0.008 → **neutral**
- nw_renewal v3 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nw_kyc v3 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.375 → **beneficial**
- ks_cancel v4 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.033 → **beneficial**
- ks_cancel v5 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.021 → **beneficial**
- nw_renewal v4 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.048 → **beneficial**
- nw_renewal v5 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- ks_cancel v6 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nw_kyc v4 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=-0.001 → **neutral**
- nw_kyc v5 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.010 → **neutral**
- ks_cancel v7 (controller_approved) dims=['welcome_message'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nw_renewal v6 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nw_kyc v6 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nw_renewal v7 (controller_approved) dims=['voice'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nw_renewal v8 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.009 → **neutral**
- ks_cancel v8 (controller_approved) dims=['voice'] engageΔ=+0.000 didΔ=+0.000 → **neutral**

## Governance

```
{
  "approval_requests": 16,
  "decisions": {
    "approved": 14,
    "rejected": 2,
    "expired": 0
  },
  "rejection_reasons": {
    "approver declined (judgement call)": 2
  },
  "applied_via_approval": 13,
  "auto_applied": 6,
  "auto_apply_rejected": 0,
  "apply_conflicts": 0,
  "lapsed": 0,
  "peak_requests_per_24h": {
    "nw_renewal": 1,
    "nw_kyc": 2,
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
{}
```

Credits used: 30 · validation runs: 12 · LLM fix calls: 0