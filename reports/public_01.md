# Grade report — public_01_dev

## Outcomes vs baseline (no-op controller)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| ks_cancel | 0.350 | +5.1% | 0.245 | +2.7% | 0.497 | +1.3% | 2% | 60 (47) |
| nw_kyc | 0.368 | +1.2% | 0.239 | -1.1% | 0.606 | +2.6% | 3% | 27 (21) |
| nw_renewal | 0.413 | -1.6% | 0.263 | -0.3% | 0.537 | -1.6% | 0% | 36 (42) |
| ALL | 0.375 | +1.7% | 0.250 | +0.9% | 0.532 | +0.4% | 1% | 123 (110) |

## Changes applied by the controller

3 applied — neutral: 3

- nw_renewal v2 (controller_approved) dims=['voice'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nw_kyc v2 (controller_approved) dims=['voice'] engageΔ=+0.007 didΔ=+0.000 → **neutral**
- ks_cancel v2 (controller_approved) dims=['voice'] engageΔ=+0.003 didΔ=+0.000 → **neutral**

## Governance

```
{
  "approval_requests": 3,
  "decisions": {
    "approved": 3,
    "expired": 0
  },
  "rejection_reasons": {},
  "applied_via_approval": 3,
  "auto_applied": 0,
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
{}
```

Credits used: 0 · validation runs: 0 · LLM fix calls: 0