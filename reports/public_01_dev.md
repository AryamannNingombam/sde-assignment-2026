# Grade report — public_01_dev

## Outcomes vs baseline (no-op controller)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| ks_cancel | 0.370 | +11.1% | 0.261 | +9.4% | 0.491 | -0.0% | 0% | 68 (47) |
| nw_kyc | 0.382 | +5.0% | 0.257 | +6.2% | 0.583 | -1.3% | 0% | 17 (21) |
| nw_renewal | 0.446 | +6.2% | 0.278 | +5.5% | 0.547 | +0.2% | 0% | 56 (42) |
| ALL | 0.398 | +7.9% | 0.266 | +7.4% | 0.528 | -0.3% | 0% | 141 (110) |

## Changes applied by the controller

9 applied — neutral: 4, beneficial: 4, harmful: 1

- ks_cancel v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.004 → **neutral**
- nw_renewal v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.004 → **neutral**
- nw_kyc v2 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.009 → **neutral**
- ks_cancel v3 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.022 → **beneficial**
- ks_cancel v4 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.015 → **neutral**
- nw_renewal v3 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.039 → **beneficial**
- nw_renewal v4 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=-0.096 → **harmful**
- nw_renewal v5 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.115 → **beneficial**
- nw_kyc v3 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.212 → **beneficial**

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
  "auto_applied": 7,
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