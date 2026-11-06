# Grade report — null_01

## Outcomes vs baseline (no-op controller)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| ks_cancel | 0.368 | +4.0% | 0.256 | +4.7% | 0.501 | -1.0% | 0% | 68 (61) |
| nw_kyc | 0.465 | +25.7% | 0.298 | +25.0% | 0.595 | -1.9% | 0% | 24 (19) |
| nw_renewal | 0.445 | +4.9% | 0.278 | +6.1% | 0.544 | -1.2% | 0% | 51 (50) |
| ALL | 0.414 | +8.8% | 0.271 | +8.9% | 0.536 | -0.9% | 0% | 143 (130) |

## Changes applied by the controller

17 applied — neutral: 14, beneficial: 3

- ks_cancel v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.004 → **neutral**
- nw_renewal v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.004 → **neutral**
- ks_cancel v3 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nw_kyc v2 (controller_approved) dims=['cohorts', 'caller_id', 'schedule'] engageΔ=+0.000 didΔ=+0.008 → **neutral**
- nw_renewal v3 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nw_kyc v3 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.375 → **beneficial**
- ks_cancel v4 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.030 → **beneficial**
- ks_cancel v5 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.019 → **neutral**
- ks_cancel v6 (controller_approved) dims=['welcome_message'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nw_renewal v4 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.037 → **beneficial**
- nw_kyc v4 (controller_approved) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nw_renewal v5 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nw_kyc v5 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=-0.000 → **neutral**
- nw_renewal v6 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.009 → **neutral**
- nw_renewal v7 (controller_approved) dims=['voice'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- ks_cancel v7 (controller_approved) dims=['voice'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- ks_cancel v8 (controller_approved) dims=['welcome_message'] engageΔ=+0.000 didΔ=+0.000 → **neutral**

## Governance

```
{
  "approval_requests": 16,
  "decisions": {
    "approved": 14,
    "rejected": 2,
    "expired": 0
  },
  "rejection_reasons": {
    "approver declined (judgement call)": 2
  },
  "applied_via_approval": 11,
  "auto_applied": 6,
  "auto_apply_rejected": 0,
  "apply_conflicts": 0,
  "lapsed": 0,
  "peak_requests_per_24h": {
    "nw_renewal": 1,
    "nw_kyc": 2,
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

Credits used: 30 · validation runs: 12 · LLM fix calls: 0