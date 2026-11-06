# Grade report — kyc_flag

## Outcomes vs baseline (no-op controller)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| ks_cancel | 0.381 | +9.8% | 0.261 | +8.5% | 0.498 | +0.5% | 0% | 78 (85) |
| nw_kyc | 0.284 | +24.9% | 0.189 | +18.8% | 0.597 | +1.9% | 0% | 27 (16) |
| nw_renewal | 0.473 | +17.1% | 0.286 | +9.1% | 0.550 | +5.8% | 18% | 146 (331) |
| ALL | 0.391 | +14.8% | 0.255 | +10.1% | 0.532 | +3.0% | 11% | 251 (432) |

## Changes applied by the controller

11 applied — neutral: 5, beneficial: 5, harmful: 1

- ks_cancel v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.004 → **neutral**
- nw_renewal v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.004 → **neutral**
- ks_cancel v3 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.025 → **beneficial**
- nw_renewal v3 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.042 → **beneficial**
- ks_cancel v4 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.016 → **neutral**
- nw_kyc v2 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.011 → **neutral**
- nw_renewal v4 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.017 → **neutral**
- nw_renewal v6 (controller_approved) dims=['prompt_version'] engageΔ=+0.102 didΔ=+0.000 → **beneficial**
- nw_renewal v7 (controller_approved) dims=['prompt_version'] engageΔ=-0.139 didΔ=+0.000 → **harmful**
- nw_kyc v3 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.772 → **beneficial**
- nw_renewal v8 (controller_approved) dims=['prompt_version'] engageΔ=+0.218 didΔ=+0.000 → **beneficial**

## Governance

```
{
  "approval_requests": 6,
  "decisions": {
    "rejected": 1,
    "approved": 5,
    "expired": 0
  },
  "rejection_reasons": {
    "approver declined (judgement call)": 1
  },
  "applied_via_approval": 5,
  "auto_applied": 6,
  "auto_apply_rejected": 0,
  "apply_conflicts": 0,
  "lapsed": 0,
  "peak_requests_per_24h": {
    "nw_kyc": 1,
    "nw_renewal": 2
  }
}
```

## Incidents

```
[
  {
    "type": "did_flagged",
    "workflow": "nw_kyc",
    "at": "D3 11:00",
    "flagged_did_share_by_day": {
      "3": 0.986,
      "4": 0.983,
      "5": 0.979,
      "6": 0.985,
      "7": 0.801,
      "8": 0.656,
      "9": 0.481
    }
  },
  {
    "type": "supervisor_edit",
    "workflow": "nw_renewal",
    "at": "D4 12:00",
    "mttr_minutes": 405,
    "fixed_by": "controller_approved"
  }
]
```

## Decaying variants — share of in-population calls still on the variant, by day after onset

```
{}
```

Credits used: 21 · validation runs: 6 · LLM fix calls: 1