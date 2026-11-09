# Grade report — public_02_incidents

## Outcomes vs baseline (no-op controller)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| ks_cancel | 0.332 | +36.3% | 0.224 | +22.5% | 0.508 | +7.7% | 44% | 73 (310) |
| nw_kyc | 0.418 | +8.7% | 0.268 | +8.1% | 0.596 | -0.6% | 0% | 42 (38) |
| nw_renewal | 0.444 | +3.2% | 0.269 | +2.2% | 0.551 | +0.7% | 5% | 47 (58) |
| ALL | 0.388 | +15.5% | 0.248 | +11.1% | 0.543 | +2.4% | 21% | 162 (406) |

## Changes applied by the controller

9 applied — neutral: 2, beneficial: 7

- ks_cancel v2 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.008 didΔ=+0.000 → **neutral**
- nw_kyc v2 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.111 → **beneficial**
- ks_cancel v3 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.193 → **beneficial**
- ks_cancel v4 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.200 → **beneficial**
- ks_cancel v6 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.031 didΔ=+0.000 → **beneficial**
- ks_cancel v7 (controller_approved) dims=['prompt_version'] engageΔ=+0.102 didΔ=+0.000 → **beneficial**
- ks_cancel v8 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.417 → **beneficial**
- ks_cancel v9 (controller_approved) dims=['voice'] engageΔ=+0.011 didΔ=+0.000 → **beneficial**
- ks_cancel v10 (controller_auto) dims=['welcome_message'] engageΔ=-0.009 didΔ=+0.000 → **neutral**

## Governance

```
{
  "approval_requests": 9,
  "decisions": {
    "rejected": 2,
    "approved": 7,
    "expired": 0
  },
  "rejection_reasons": {
    "approver declined (judgement call)": 2
  },
  "applied_via_approval": 7,
  "auto_applied": 2,
  "auto_apply_rejected": 0,
  "apply_conflicts": 0,
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
      "2": 0.216,
      "3": 0.051,
      "4": 0.047,
      "5": 0.048,
      "6": 0.05,
      "7": 0.049,
      "8": 0.053,
      "9": 0.044
    }
  },
  {
    "type": "supervisor_edit",
    "workflow": "ks_cancel",
    "at": "D3 11:30",
    "mttr_minutes": 330,
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

Credits used: 5 · validation runs: 1 · LLM fix calls: 0