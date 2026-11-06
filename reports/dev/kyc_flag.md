# Grade report — kyc_flag

## Outcomes vs baseline (no-op controller)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| ks_cancel | 0.378 | +9.0% | 0.262 | +8.9% | 0.495 | -0.1% | 3% | 77 (85) |
| nw_kyc | 0.409 | +79.8% | 0.264 | +66.4% | 0.589 | +0.5% | 0% | 28 (16) |
| nw_renewal | 0.474 | +17.3% | 0.284 | +8.7% | 0.554 | +6.5% | 42% | 85 (331) |
| ALL | 0.417 | +22.3% | 0.270 | +16.4% | 0.534 | +3.3% | 21% | 190 (432) |

## Changes applied by the controller

25 applied — neutral: 18, beneficial: 7

- ks_cancel v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.004 → **neutral**
- nw_renewal v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.004 → **neutral**
- nw_renewal v3 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'schedule'] engageΔ=+0.008 didΔ=+0.000 → **neutral**
- ks_cancel v3 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'schedule'] engageΔ=+0.006 didΔ=+0.000 → **neutral**
- ks_cancel v4 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.030 → **beneficial**
- ks_cancel v5 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.019 → **neutral**
- nw_kyc v2 (controller_approved) dims=['cohorts', 'caller_id', 'schedule'] engageΔ=+0.000 didΔ=+0.011 → **neutral**
- nw_renewal v4 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.057 → **beneficial**
- nw_renewal v5 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.033 didΔ=+0.000 → **beneficial**
- ks_cancel v6 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.009 didΔ=+0.000 → **neutral**
- nw_renewal v6 (controller_approved) dims=['voice'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- ks_cancel v7 (controller_approved) dims=['voice'] engageΔ=-0.006 didΔ=+0.000 → **neutral**
- nw_renewal v7 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.018 → **neutral**
- nw_kyc v3 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+1.859 → **beneficial**
- nw_kyc v4 (controller_approved) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- ks_cancel v8 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=-0.009 didΔ=+0.000 → **neutral**
- nw_renewal v9 (controller_approved) dims=['prompt_version'] engageΔ=+0.102 didΔ=+0.000 → **beneficial**
- nw_kyc v5 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=-0.001 → **neutral**
- ks_cancel v9 (controller_approved) dims=['voice'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nw_renewal v10 (controller_approved) dims=['prompt_version'] engageΔ=+0.031 didΔ=+0.000 → **beneficial**
- nw_kyc v6 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.002 → **neutral**
- nw_renewal v11 (controller_approved) dims=['welcome_message'] engageΔ=+0.020 didΔ=+0.000 → **beneficial**
- ks_cancel v10 (controller_approved) dims=['welcome_message'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nw_kyc v7 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=-0.004 → **neutral**
- nw_renewal v12 (controller_approved) dims=['welcome_message'] engageΔ=+0.000 didΔ=+0.000 → **neutral**

## Governance

```
{
  "approval_requests": 20,
  "decisions": {
    "approved": 19,
    "rejected": 1,
    "expired": 0
  },
  "rejection_reasons": {
    "approver declined (judgement call)": 1
  },
  "applied_via_approval": 19,
  "auto_applied": 6,
  "auto_apply_rejected": 0,
  "apply_conflicts": 0,
  "lapsed": 0,
  "peak_requests_per_24h": {
    "nw_renewal": 2,
    "nw_kyc": 2,
    "ks_cancel": 1
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
      "3": 0.985,
      "4": 0.623,
      "5": 0.322,
      "6": 0.0,
      "7": 0.0,
      "8": 0.003,
      "9": 0.004
    }
  },
  {
    "type": "supervisor_edit",
    "workflow": "nw_renewal",
    "at": "D4 12:00",
    "mttr_minutes": 300,
    "fixed_by": "controller_approved"
  }
]
```

## Decaying variants — share of in-population calls still on the variant, by day after onset

```
{
  "nw_renewal:welcome_message=W3": {
    "2": 0.206,
    "3": 0.194,
    "4": 0.199,
    "5": 0.21,
    "6": 0.05,
    "7": 0.0,
    "8": 0.0,
    "9": 0.0
  }
}
```

Credits used: 41 · validation runs: 14 · LLM fix calls: 2