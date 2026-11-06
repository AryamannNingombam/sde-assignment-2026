# Grade report — public_02_incidents

## Outcomes vs baseline (no-op controller)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| ks_cancel | 0.355 | +43.4% | 0.246 | +34.1% | 0.495 | +3.9% | 31% | 86 (330) |
| nw_kyc | 0.410 | +9.3% | 0.264 | +9.2% | 0.588 | -0.7% | 0% | 31 (31) |
| nw_renewal | 0.480 | +12.5% | 0.286 | +9.2% | 0.561 | +2.4% | 5% | 58 (55) |
| ALL | 0.408 | +22.2% | 0.264 | +18.7% | 0.538 | +1.5% | 16% | 175 (416) |

## Changes applied by the controller

17 applied — neutral: 6, beneficial: 9, harmful: 2

- ks_cancel v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.004 → **neutral**
- nw_renewal v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.004 → **neutral**
- nw_kyc v2 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.010 → **neutral**
- ks_cancel v3 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.024 → **beneficial**
- ks_cancel v4 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.015 → **neutral**
- nw_renewal v3 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.044 → **beneficial**
- ks_cancel v5 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.154 → **beneficial**
- ks_cancel v6 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.113 → **beneficial**
- nw_renewal v4 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.020 → **neutral**
- ks_cancel v8 (controller_approved) dims=['prompt_version'] engageΔ=+0.102 didΔ=+0.000 → **beneficial**
- ks_cancel v9 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=-0.004 → **neutral**
- nw_kyc v3 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.155 → **beneficial**
- ks_cancel v10 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=-0.113 → **harmful**
- ks_cancel v11 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=-0.092 → **harmful**
- ks_cancel v12 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.140 → **beneficial**
- ks_cancel v13 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.093 → **beneficial**
- nw_kyc v4 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.030 → **beneficial**

## Governance

```
{
  "approval_requests": 4,
  "decisions": {
    "approved": 4,
    "expired": 0
  },
  "rejection_reasons": {},
  "applied_via_approval": 4,
  "auto_applied": 13,
  "auto_apply_rejected": 0,
  "apply_conflicts": 0,
  "lapsed": 0,
  "peak_requests_per_24h": {
    "nw_kyc": 1,
    "ks_cancel": 1
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
      "2": 0.09,
      "3": 0.0,
      "4": 0.005,
      "5": 0.005,
      "6": 0.007,
      "7": 0.059,
      "8": 0.0,
      "9": 0.0
    }
  },
  {
    "type": "supervisor_edit",
    "workflow": "ks_cancel",
    "at": "D3 11:30",
    "mttr_minutes": 165,
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
{}
```

Credits used: 9 · validation runs: 3 · LLM fix calls: 0