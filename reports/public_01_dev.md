# Grade report — public_01_dev

## Outcomes vs baseline (no-op controller)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| ks_cancel | 0.386 | +15.8% | 0.259 | +8.7% | 0.515 | +4.8% | 19% | 66 (47) |
| nw_kyc | 0.382 | +5.2% | 0.253 | +4.6% | 0.588 | -0.4% | 0% | 26 (21) |
| nw_renewal | 0.435 | +3.7% | 0.277 | +5.3% | 0.536 | -1.7% | -5% | 58 (42) |
| ALL | 0.401 | +9.0% | 0.264 | +6.7% | 0.536 | +1.2% | 6% | 150 (110) |

## Changes applied by the controller

19 applied — neutral: 11, beneficial: 7, harmful: 1

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
- ks_cancel v7 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.022 didΔ=+0.000 → **beneficial**
- nw_renewal v5 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.024 didΔ=+0.000 → **beneficial**
- nw_renewal v6 (controller_approved) dims=['voice'] engageΔ=+0.001 didΔ=+0.000 → **neutral**
- ks_cancel v8 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nw_renewal v7 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.009 → **neutral**
- nw_renewal v8 (controller_approved) dims=['welcome_message'] engageΔ=-0.058 didΔ=+0.000 → **harmful**
- nw_kyc v4 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.231 → **beneficial**
- ks_cancel v9 (controller_approved) dims=['voice'] engageΔ=+0.060 didΔ=+0.000 → **beneficial**
- nw_renewal v9 (controller_approved) dims=['voice'] engageΔ=-0.001 didΔ=+0.000 → **neutral**

## Governance

```
{
  "approval_requests": 11,
  "decisions": {
    "approved": 11,
    "expired": 0
  },
  "rejection_reasons": {},
  "applied_via_approval": 11,
  "auto_applied": 8,
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
    "3": 0.201,
    "4": 0.203,
    "5": 0.683,
    "6": 0.894,
    "7": 0.899
  }
}
```

Credits used: 24 · validation runs: 10 · LLM fix calls: 0