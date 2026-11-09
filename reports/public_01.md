# Grade report — public_01_dev

## Outcomes vs baseline (no-op controller)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| ks_cancel | 0.356 | +7.1% | 0.242 | +1.6% | 0.511 | +4.1% | 14% | 44 (47) |
| nw_kyc | 0.367 | +0.8% | 0.238 | -1.7% | 0.607 | +2.8% | 0% | 17 (21) |
| nw_renewal | 0.415 | -1.1% | 0.264 | +0.0% | 0.540 | -1.0% | 1% | 41 (42) |
| ALL | 0.378 | +2.6% | 0.249 | +0.4% | 0.539 | +1.8% | 5% | 102 (110) |

## Changes applied by the controller

2 applied — neutral: 1, beneficial: 1

- nw_renewal v2 (controller_approved) dims=['voice'] engageΔ=+0.002 didΔ=+0.000 → **neutral**
- ks_cancel v2 (controller_approved) dims=['voice'] engageΔ=+0.022 didΔ=+0.000 → **beneficial**

## Governance

```
{
  "approval_requests": 3,
  "decisions": {
    "approved": 2,
    "rejected": 1,
    "expired": 0
  },
  "rejection_reasons": {
    "approver declined (judgement call)": 1
  },
  "applied_via_approval": 2,
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