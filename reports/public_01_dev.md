# Grade report — public_01_dev

## Outcomes vs baseline (no-op controller)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| ks_cancel | 0.341 | -0.0% | 0.238 | -0.5% | 0.500 | +0.1% | 5% | 68 (52) |
| nw_kyc | 0.443 | +17.5% | 0.284 | +17.4% | 0.602 | -1.6% | 0% | 25 (21) |
| nw_renewal | 0.412 | -2.0% | 0.250 | -4.5% | 0.561 | +2.5% | 13% | 43 (39) |
| ALL | 0.386 | +3.0% | 0.251 | +1.4% | 0.543 | +1.0% | 7% | 136 (112) |

## Changes applied by the controller

9 applied — neutral: 3, beneficial: 6

- ks_cancel v2 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=-0.007 didΔ=+0.000 → **neutral**
- nw_renewal v2 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.021 didΔ=+0.000 → **beneficial**
- nw_kyc v2 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.095 → **beneficial**
- nw_renewal v3 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.004 → **neutral**
- ks_cancel v3 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.022 didΔ=+0.000 → **beneficial**
- nw_renewal v4 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.007 didΔ=+0.000 → **neutral**
- nw_kyc v3 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.114 → **beneficial**
- nw_renewal v5 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.157 → **beneficial**
- nw_renewal v6 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.230 → **beneficial**

## Governance

```
{
  "approval_requests": 8,
  "decisions": {
    "approved": 7,
    "rejected": 1,
    "expired": 0
  },
  "rejection_reasons": {
    "approver declined (judgement call)": 1
  },
  "applied_via_approval": 7,
  "auto_applied": 2,
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
    "3": 0.0,
    "4": 0.0,
    "5": 0.0,
    "6": 0.0,
    "7": 0.0
  }
}
```

Credits used: 0 · validation runs: 0 · LLM fix calls: 0