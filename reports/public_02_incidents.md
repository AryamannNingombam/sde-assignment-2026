# Grade report — public_02_incidents

## Outcomes vs baseline (no-op controller)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| ks_cancel | 0.335 | +35.2% | 0.252 | +37.2% | 0.503 | +5.5% | 26% | 84 (330) |
| nw_kyc | 0.362 | -3.3% | 0.254 | +4.9% | 0.605 | +2.1% | 0% | 16 (31) |
| nw_renewal | 0.421 | -1.3% | 0.284 | +8.5% | 0.552 | +0.7% | 3% | 47 (55) |
| ALL | 0.369 | +10.5% | 0.264 | +18.7% | 0.540 | +1.9% | 13% | 147 (416) |

## Changes applied by the controller

12 applied — neutral: 6, beneficial: 6

- ks_cancel v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.004 → **neutral**
- nw_renewal v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.004 → **neutral**
- nw_kyc v2 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.010 → **neutral**
- ks_cancel v3 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.024 → **beneficial**
- ks_cancel v4 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.015 → **neutral**
- nw_renewal v3 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.044 → **beneficial**
- ks_cancel v5 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.155 → **beneficial**
- ks_cancel v6 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.113 → **beneficial**
- nw_renewal v4 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.017 → **neutral**
- ks_cancel v8 (controller_approved) dims=['prompt_version'] engageΔ=+0.102 didΔ=+0.000 → **beneficial**
- ks_cancel v9 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=-0.004 → **neutral**
- nw_kyc v3 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.246 → **beneficial**

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
  "auto_applied": 9,
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
      "2": 0.087,
      "3": 0.0,
      "4": 0.004,
      "5": 0.008,
      "6": 0.006,
      "7": 0.005
    }
  },
  {
    "type": "supervisor_edit",
    "workflow": "ks_cancel",
    "at": "D3 11:30",
    "mttr_minutes": 180,
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