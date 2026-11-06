# Grade report — public_02_incidents

## Outcomes vs baseline (no-op controller)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| ks_cancel | 0.364 | +47.0% | 0.248 | +35.0% | 0.499 | +4.8% | 36% | 89 (330) |
| nw_kyc | 0.405 | +8.0% | 0.259 | +6.9% | 0.591 | -0.1% | 0% | 31 (31) |
| nw_renewal | 0.460 | +7.8% | 0.279 | +6.4% | 0.549 | +0.1% | 7% | 68 (55) |
| ALL | 0.404 | +21.0% | 0.261 | +17.4% | 0.535 | +1.0% | 23% | 188 (416) |

## Changes applied by the controller

26 applied — neutral: 19, beneficial: 7

- ks_cancel v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.004 → **neutral**
- nw_renewal v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.004 → **neutral**
- ks_cancel v3 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'schedule'] engageΔ=+0.006 didΔ=+0.000 → **neutral**
- nw_renewal v3 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'schedule'] engageΔ=+0.008 didΔ=+0.000 → **neutral**
- nw_kyc v2 (controller_approved) dims=['cohorts', 'caller_id', 'schedule'] engageΔ=+0.000 didΔ=+0.010 → **neutral**
- nw_renewal v4 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- ks_cancel v4 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.030 → **beneficial**
- ks_cancel v5 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.019 → **neutral**
- nw_renewal v5 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.004 → **neutral**
- nw_renewal v6 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.036 → **beneficial**
- nw_kyc v3 (controller_approved) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nw_renewal v7 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=-0.009 didΔ=+0.000 → **neutral**
- ks_cancel v6 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.154 → **beneficial**
- ks_cancel v7 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.115 → **beneficial**
- nw_renewal v8 (controller_approved) dims=['welcome_message'] engageΔ=+0.005 didΔ=+0.000 → **neutral**
- ks_cancel v9 (controller_approved) dims=['welcome_message', 'voice', 'prompt_version'] engageΔ=+0.109 didΔ=+0.000 → **beneficial**
- nw_renewal v9 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.019 → **neutral**
- ks_cancel v10 (controller_approved) dims=['welcome_message'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- ks_cancel v11 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=-0.004 → **neutral**
- nw_renewal v10 (controller_approved) dims=['welcome_message'] engageΔ=+0.020 didΔ=+0.000 → **beneficial**
- ks_cancel v12 (controller_approved) dims=['voice'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nw_kyc v4 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.154 → **beneficial**
- ks_cancel v13 (controller_approved) dims=['voice'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nw_renewal v12 (controller_approved) dims=['welcome_message'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- ks_cancel v14 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.004 → **neutral**
- ks_cancel v15 (controller_approved) dims=['voice'] engageΔ=-0.002 didΔ=+0.000 → **neutral**

## Governance

```
{
  "approval_requests": 16,
  "decisions": {
    "approved": 16,
    "expired": 0
  },
  "rejection_reasons": {},
  "applied_via_approval": 14,
  "auto_applied": 12,
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
      "2": 0.088,
      "3": 0.0,
      "4": 0.005,
      "5": 0.005,
      "6": 0.008,
      "7": 0.009,
      "8": 0.006,
      "9": 0.0
    }
  },
  {
    "type": "supervisor_edit",
    "workflow": "ks_cancel",
    "at": "D3 11:30",
    "mttr_minutes": 135,
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
    "2": 0.077,
    "3": 0.159,
    "4": 0.197,
    "5": 0.037,
    "6": 0.0,
    "7": 0.0,
    "8": 0.0,
    "9": 0.0
  }
}
```

Credits used: 26 · validation runs: 11 · LLM fix calls: 0