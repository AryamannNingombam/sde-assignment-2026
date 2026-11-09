# Grade report — public_01_dev

## Outcomes vs baseline (no-op controller)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| ks_cancel | 0.352 | +5.7% | 0.249 | +4.5% | 0.495 | +0.9% | -0% | 48 (47) |
| nw_kyc | 0.430 | +18.3% | 0.280 | +15.8% | 0.597 | +1.1% | 0% | 22 (21) |
| nw_renewal | 0.439 | +4.5% | 0.268 | +1.8% | 0.562 | +3.0% | 14% | 50 (42) |
| ALL | 0.397 | +7.9% | 0.262 | +5.6% | 0.540 | +1.9% | 5% | 120 (110) |

## Changes applied by the controller

16 applied — neutral: 8, beneficial: 7, harmful: 1

- nw_renewal v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=-0.013 → **neutral**
- ks_cancel v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.007 → **neutral**
- nw_renewal v3 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.050 didΔ=+0.000 → **beneficial**
- ks_cancel v3 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=-0.003 didΔ=+0.000 → **neutral**
- nw_kyc v2 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.044 → **beneficial**
- nw_renewal v4 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.019 → **neutral**
- nw_renewal v5 (controller_approved) dims=['cohorts', 'welcome_message'] engageΔ=+0.051 didΔ=+0.000 → **beneficial**
- nw_renewal v6 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=-0.006 → **neutral**
- ks_cancel v4 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=-0.006 → **neutral**
- ks_cancel v5 (controller_approved) dims=['welcome_message'] engageΔ=+0.018 didΔ=+0.000 → **beneficial**
- nw_kyc v3 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.221 → **beneficial**
- nw_renewal v7 (controller_approved) dims=['voice'] engageΔ=-0.001 didΔ=+0.000 → **neutral**
- ks_cancel v6 (controller_approved) dims=['voice'] engageΔ=-0.014 didΔ=+0.000 → **harmful**
- nw_kyc v4 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.091 → **beneficial**
- nw_kyc v5 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=-0.001 → **neutral**
- nw_renewal v8 (controller_approved) dims=['welcome_message'] engageΔ=+0.047 didΔ=+0.000 → **beneficial**

## Governance

```
{
  "approval_requests": 12,
  "decisions": {
    "approved": 12,
    "expired": 0
  },
  "rejection_reasons": {},
  "applied_via_approval": 12,
  "auto_applied": 4,
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
    "3": 0.603,
    "4": 0.633,
    "5": 0.667,
    "6": 0.638,
    "7": 0.107
  }
}
```

Credits used: 0 · validation runs: 0 · LLM fix calls: 0