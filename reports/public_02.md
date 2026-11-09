# Grade report — public_02_incidents

## Outcomes vs baseline (no-op controller)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| ks_cancel | 0.248 | +0.1% | 0.183 | -0.7% | 0.482 | +1.2% | 1% | 329 (330) |
| nw_kyc | 0.375 | +0.2% | 0.240 | -0.9% | 0.599 | +1.1% | 4% | 22 (31) |
| nw_renewal | 0.428 | +0.4% | 0.258 | -1.6% | 0.558 | +1.7% | 4% | 58 (55) |
| ALL | 0.335 | +0.3% | 0.220 | -1.1% | 0.537 | +1.4% | 3% | 409 (416) |

## Changes applied by the controller

3 applied — neutral: 3

- nw_renewal v2 (controller_approved) dims=['voice'] engageΔ=-0.002 didΔ=+0.000 → **neutral**
- nw_kyc v2 (controller_approved) dims=['voice'] engageΔ=+0.004 didΔ=+0.000 → **neutral**
- ks_cancel v2 (controller_approved) dims=['voice'] engageΔ=+0.001 didΔ=+0.000 → **neutral**

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
[
  {
    "type": "did_flagged",
    "workflow": "ks_cancel",
    "at": "D2 10:00",
    "flagged_did_share_by_day": {
      "2": 0.499,
      "3": 0.499,
      "4": 0.503,
      "5": 0.492,
      "6": 0.514,
      "7": 0.5,
      "8": 0.517,
      "9": 0.494
    }
  },
  {
    "type": "supervisor_edit",
    "workflow": "ks_cancel",
    "at": "D3 11:30",
    "mttr_minutes": null,
    "fixed_by": null
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

Credits used: 0 · validation runs: 0 · LLM fix calls: 0