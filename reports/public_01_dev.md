# Grade report — public_01_dev

## Outcomes vs baseline (no-op controller)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| ks_cancel | 0.381 | +14.5% | 0.257 | +8.0% | 0.515 | +4.9% | 23% | 48 (47) |
| nw_kyc | 0.390 | +7.2% | 0.259 | +6.9% | 0.591 | +0.0% | 0% | 18 (21) |
| nw_renewal | 0.455 | +8.4% | 0.279 | +6.0% | 0.556 | +1.9% | 7% | 47 (42) |
| ALL | 0.408 | +10.6% | 0.265 | +7.1% | 0.544 | +2.7% | 11% | 113 (110) |

## Changes applied by the controller

19 applied — neutral: 11, beneficial: 8

- ks_cancel v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.004 → **neutral**
- nw_renewal v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.004 → **neutral**
- ks_cancel v3 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'schedule'] engageΔ=+0.001 didΔ=+0.000 → **neutral**
- nw_renewal v3 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'schedule'] engageΔ=+0.015 didΔ=+0.000 → **beneficial**
- nw_kyc v2 (controller_approved) dims=['cohorts', 'caller_id', 'schedule'] engageΔ=+0.000 didΔ=+0.009 → **neutral**
- ks_cancel v4 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- ks_cancel v5 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.029 → **beneficial**
- ks_cancel v6 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.019 → **neutral**
- nw_renewal v4 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.029 → **beneficial**
- ks_cancel v7 (controller_approved) dims=['voice'] engageΔ=+0.011 didΔ=+0.000 → **beneficial**
- nw_renewal v5 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.025 didΔ=+0.000 → **beneficial**
- nw_renewal v6 (controller_approved) dims=['voice'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- ks_cancel v8 (controller_approved) dims=['welcome_message'] engageΔ=+0.007 didΔ=+0.000 → **neutral**
- ks_cancel v9 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- ks_cancel v10 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.029 didΔ=+0.000 → **beneficial**
- ks_cancel v11 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nw_kyc v3 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.154 → **beneficial**
- ks_cancel v12 (controller_approved) dims=['voice'] engageΔ=+0.032 didΔ=+0.000 → **beneficial**
- ks_cancel v13 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**

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
  "applied_via_approval": 10,
  "auto_applied": 9,
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
    "3": 0.202,
    "4": 0.202,
    "5": 0.19,
    "6": 0.199,
    "7": 0.204
  }
}
```

Credits used: 24 · validation runs: 10 · LLM fix calls: 0