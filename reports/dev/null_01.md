# Grade report — null_01

## Outcomes vs baseline (no-op controller)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| ks_cancel | 0.381 | +7.7% | 0.261 | +6.9% | 0.511 | +0.9% | 0% | 70 (61) |
| nw_kyc | 0.376 | +1.7% | 0.249 | +4.6% | 0.591 | -2.5% | 0% | 23 (19) |
| nw_renewal | 0.440 | +3.8% | 0.273 | +4.0% | 0.547 | -0.5% | 0% | 47 (50) |
| ALL | 0.400 | +5.0% | 0.263 | +5.4% | 0.539 | -0.4% | 0% | 140 (130) |

## Changes applied by the controller

8 applied — neutral: 5, beneficial: 3

- ks_cancel v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.004 → **neutral**
- nw_renewal v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.004 → **neutral**
- nw_kyc v2 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.008 → **neutral**
- ks_cancel v3 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.025 → **beneficial**
- ks_cancel v4 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.016 → **neutral**
- nw_renewal v3 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.035 → **beneficial**
- nw_renewal v4 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.009 → **neutral**
- nw_kyc v3 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.157 → **beneficial**

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

Credits used: 9 · validation runs: 3 · LLM fix calls: 0