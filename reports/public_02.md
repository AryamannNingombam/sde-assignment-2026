# Grade report — public_02_incidents

## Outcomes vs baseline (no-op controller)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| ks_cancel | 0.326 | +31.5% | 0.222 | +20.9% | 0.503 | +5.6% | 37% | 109 (330) |
| nw_kyc | 0.388 | +3.5% | 0.252 | +4.0% | 0.589 | -0.6% | 0% | 33 (31) |
| nw_renewal | 0.439 | +3.0% | 0.266 | +1.6% | 0.552 | +0.8% | 15% | 55 (55) |
| ALL | 0.377 | +12.7% | 0.243 | +9.5% | 0.539 | +1.7% | 25% | 197 (416) |

## Changes applied by the controller

17 applied — neutral: 5, beneficial: 10, harmful: 2

- nw_renewal v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.013 → **neutral**
- ks_cancel v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.007 → **neutral**
- nw_kyc v2 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.039 → **beneficial**
- ks_cancel v3 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.017 didΔ=+0.000 → **beneficial**
- nw_renewal v3 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.032 didΔ=+0.000 → **beneficial**
- ks_cancel v4 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.190 → **beneficial**
- nw_renewal v4 (controller_approved) dims=['welcome_message'] engageΔ=+0.101 didΔ=+0.000 → **beneficial**
- ks_cancel v6 (controller_approved) dims=['caller_id', 'prompt_version'] engageΔ=+0.102 didΔ=+0.203 → **beneficial**
- ks_cancel v7 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=-0.020 → **harmful**
- nw_renewal v5 (controller_approved) dims=['voice'] engageΔ=+0.018 didΔ=+0.000 → **beneficial**
- ks_cancel v8 (controller_approved) dims=['cohorts', 'welcome_message'] engageΔ=+0.003 didΔ=+0.000 → **neutral**
- nw_renewal v6 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=-0.011 → **neutral**
- nw_kyc v3 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=-0.032 → **harmful**
- nw_renewal v8 (controller_approved) dims=['welcome_message'] engageΔ=+0.092 didΔ=+0.000 → **beneficial**
- ks_cancel v9 (controller_approved) dims=['voice'] engageΔ=-0.005 didΔ=+0.000 → **neutral**
- ks_cancel v10 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.113 → **beneficial**
- ks_cancel v11 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.344 → **beneficial**

## Governance

```
{
  "approval_requests": 15,
  "decisions": {
    "approved": 13,
    "rejected": 2,
    "expired": 0
  },
  "rejection_reasons": {
    "approver declined (judgement call)": 2
  },
  "applied_via_approval": 11,
  "auto_applied": 6,
  "auto_apply_rejected": 0,
  "apply_conflicts": 2,
  "lapsed": 0,
  "peak_requests_per_24h": {
    "nw_renewal": 1,
    "nw_kyc": 1,
    "ks_cancel": 2
  }
}
```

## Incidents

```
[
  {
    "type": "did_flagged",
    "workflow": "ks_cancel",
    "at": "D2 10:00",
    "flagged_did_share_by_day": {
      "2": 0.311,
      "3": 0.211,
      "4": 0.0,
      "5": 0.0,
      "6": 0.0,
      "7": 0.0,
      "8": 0.0,
      "9": 0.0
    }
  },
  {
    "type": "supervisor_edit",
    "workflow": "ks_cancel",
    "at": "D3 11:30",
    "mttr_minutes": 390,
    "fixed_by": "controller_approved"
  },
  {
    "type": "supervisor_edit",
    "workflow": "nw_renewal",
    "at": "D5 15:00"
  }
]
```

## Decaying variants — share of in-population calls still on the variant, by day after onset

```
{
  "nw_renewal:welcome_message=W3": {
    "3": 0.84,
    "4": 0.862,
    "5": 0.846,
    "6": 0.174,
    "7": 0.0,
    "8": 0.0,
    "9": 0.0
  }
}
```

Credits used: 5 · validation runs: 1 · LLM fix calls: 0