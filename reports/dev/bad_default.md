# Grade report — bad_default

## Outcomes vs baseline (no-op controller)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| ks_cancel | 0.392 | +8.7% | 0.258 | +5.5% | 0.525 | +2.2% | 0% | 249 (224) |
| nw_kyc | 0.395 | +4.8% | 0.256 | +5.0% | 0.607 | +0.2% | 0% | 26 (26) |
| nw_renewal | 0.455 | +8.5% | 0.284 | +8.0% | 0.549 | -0.0% | 0% | 38 (53) |
| ALL | 0.414 | +7.8% | 0.267 | +6.3% | 0.549 | +0.9% | 0% | 313 (303) |

## Changes applied by the controller

8 applied — neutral: 5, beneficial: 3

- ks_cancel v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.004 → **neutral**
- nw_renewal v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.004 → **neutral**
- nw_kyc v2 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.008 → **neutral**
- ks_cancel v3 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.023 → **beneficial**
- ks_cancel v4 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.015 → **neutral**
- nw_renewal v3 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.034 → **beneficial**
- nw_renewal v4 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.009 → **neutral**
- nw_kyc v3 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.156 → **beneficial**

## Governance

```
{
  "approval_requests": 2,
  "decisions": {
    "approved": 2,
    "expired": 0
  },
  "rejection_reasons": {},
  "applied_via_approval": 2,
  "auto_applied": 6,
  "auto_apply_rejected": 0,
  "apply_conflicts": 0,
  "lapsed": 0,
  "peak_requests_per_24h": {
    "nw_kyc": 1
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

Credits used: 12 · validation runs: 4 · LLM fix calls: 0