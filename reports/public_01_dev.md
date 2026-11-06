# Grade report — public_01_dev

## Outcomes vs baseline (no-op controller)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| ks_cancel | 0.376 | +12.8% | 0.260 | +8.9% | 0.502 | +2.2% | 8% | 61 (47) |
| nw_kyc | 0.383 | +5.3% | 0.252 | +4.0% | 0.591 | -0.0% | 0% | 20 (21) |
| nw_renewal | 0.458 | +9.1% | 0.281 | +6.5% | 0.554 | +1.5% | 6% | 37 (42) |
| ALL | 0.405 | +9.8% | 0.265 | +7.1% | 0.537 | +1.3% | 5% | 118 (110) |

## Changes applied by the controller

19 applied — neutral: 11, beneficial: 8

- ks_cancel v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.004 → **neutral**
- nw_renewal v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.004 → **neutral**
- ks_cancel v3 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'schedule'] engageΔ=+0.001 didΔ=+0.000 → **neutral**
- nw_renewal v3 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'schedule'] engageΔ=+0.015 didΔ=+0.000 → **beneficial**
- nw_kyc v2 (controller_approved) dims=['cohorts', 'caller_id', 'schedule'] engageΔ=+0.000 didΔ=+0.009 → **neutral**
- ks_cancel v4 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- ks_cancel v5 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.030 → **beneficial**
- nw_kyc v3 (controller_approved) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- ks_cancel v6 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.020 → **neutral**
- nw_renewal v4 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.049 → **beneficial**
- ks_cancel v7 (controller_approved) dims=['voice'] engageΔ=+0.011 didΔ=+0.000 → **beneficial**
- nw_renewal v5 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.025 didΔ=+0.000 → **beneficial**
- ks_cancel v8 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nw_renewal v6 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.009 → **neutral**
- nw_renewal v7 (controller_approved) dims=['welcome_message'] engageΔ=+0.018 didΔ=+0.000 → **beneficial**
- ks_cancel v9 (controller_approved) dims=['welcome_message'] engageΔ=+0.004 didΔ=+0.000 → **neutral**
- nw_kyc v4 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.216 → **beneficial**
- nw_renewal v8 (controller_approved) dims=['welcome_message'] engageΔ=+0.067 didΔ=+0.000 → **beneficial**
- ks_cancel v10 (controller_approved) dims=['welcome_message'] engageΔ=+0.007 didΔ=+0.000 → **neutral**

## Governance

```
{
  "approval_requests": 12,
  "decisions": {
    "approved": 11,
    "rejected": 1,
    "expired": 0
  },
  "rejection_reasons": {
    "approver declined (judgement call)": 1
  },
  "applied_via_approval": 11,
  "auto_applied": 8,
  "auto_apply_rejected": 0,
  "apply_conflicts": 0,
  "lapsed": 0,
  "peak_requests_per_24h": {
    "nw_renewal": 2,
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
    "3": 0.207,
    "4": 0.684,
    "5": 0.583,
    "6": 0.0,
    "7": 0.0
  }
}
```

Credits used: 24 · validation runs: 10 · LLM fix calls: 0