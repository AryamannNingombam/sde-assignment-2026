# Grade report — public_03_load

## Outcomes vs baseline (no-op controller)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| arav_cancel_2 | 0.406 | +20.5% | 0.275 | +13.0% | 0.525 | +5.7% | 36% | 425 (409) |
| arav_kyc_1 | 0.480 | +33.8% | 0.267 | +24.2% | 0.616 | +2.6% | 22% | 440 (352) |
| arav_renewal_0 | 0.483 | +19.1% | 0.292 | +10.7% | 0.584 | +6.5% | 40% | 473 (408) |
| kest_cancel_2 | 0.404 | +20.1% | 0.274 | +13.0% | 0.523 | +4.7% | 37% | 427 (418) |
| kest_kyc_1 | 0.487 | +37.1% | 0.265 | +23.8% | 0.627 | +5.0% | 32% | 397 (370) |
| kest_renewal_0 | 0.485 | +20.7% | 0.293 | +10.5% | 0.586 | +7.6% | 40% | 454 (403) |
| nort_cancel_2 | 0.403 | +18.7% | 0.273 | +12.0% | 0.522 | +4.7% | 38% | 412 (368) |
| nort_kyc_1 | 0.374 | +5.3% | 0.226 | +5.0% | 0.593 | -0.4% | 3% | 373 (318) |
| nort_renewal_0 | 0.477 | +17.7% | 0.292 | +10.4% | 0.578 | +5.6% | 31% | 492 (419) |
| tide_cancel_2 | 0.405 | +18.0% | 0.274 | +12.1% | 0.524 | +4.6% | 38% | 435 (401) |
| tide_kyc_1 | 0.479 | +34.5% | 0.263 | +22.3% | 0.626 | +4.7% | 32% | 434 (376) |
| tide_renewal_0 | 0.473 | +16.8% | 0.292 | +10.7% | 0.571 | +4.5% | 20% | 492 (425) |
| ALL | 0.446 | +21.8% | 0.274 | +13.7% | 0.572 | +4.9% | 31% | 5254 (4667) |

## Changes applied by the controller

114 applied — neutral: 79, beneficial: 35

- nort_renewal_0 v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=-0.007 → **neutral**
- nort_cancel_2 v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.006 → **neutral**
- kest_renewal_0 v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=-0.007 → **neutral**
- kest_cancel_2 v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.006 → **neutral**
- arav_renewal_0 v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=-0.007 → **neutral**
- arav_cancel_2 v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.006 → **neutral**
- tide_renewal_0 v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=-0.007 → **neutral**
- tide_cancel_2 v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.006 → **neutral**
- nort_renewal_0 v3 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nort_cancel_2 v3 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- kest_renewal_0 v3 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- kest_cancel_2 v3 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- arav_renewal_0 v3 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- arav_cancel_2 v3 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- tide_renewal_0 v3 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- tide_cancel_2 v3 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nort_renewal_0 v4 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.004 → **neutral**
- kest_renewal_0 v4 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.029 → **beneficial**
- kest_cancel_2 v4 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.023 → **beneficial**
- arav_renewal_0 v4 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.004 → **neutral**
- tide_renewal_0 v4 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.027 → **beneficial**
- tide_cancel_2 v4 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.017 → **neutral**
- nort_cancel_2 v4 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.018 → **neutral**
- arav_cancel_2 v4 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.017 → **neutral**
- nort_renewal_0 v5 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.035 didΔ=+0.000 → **beneficial**
- arav_cancel_2 v5 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=-0.003 didΔ=+0.000 → **neutral**
- tide_cancel_2 v5 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=-0.003 didΔ=+0.000 → **neutral**
- nort_renewal_0 v6 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.023 → **beneficial**
- nort_cancel_2 v5 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=-0.002 didΔ=+0.000 → **neutral**
- arav_kyc_1 v2 (controller_approved) dims=['welcome_message', 'voice', 'caller_id', 'schedule'] engageΔ=+0.022 didΔ=+0.037 → **beneficial**
- tide_renewal_0 v5 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.010 → **neutral**
- tide_cancel_2 v6 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.011 → **neutral**
- nort_cancel_2 v6 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.011 → **neutral**
- kest_cancel_2 v5 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=-0.003 didΔ=+0.000 → **neutral**
- kest_cancel_2 v6 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.009 → **neutral**
- arav_cancel_2 v6 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.011 → **neutral**
- arav_renewal_0 v5 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.050 didΔ=+0.000 → **beneficial**
- arav_renewal_0 v6 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.023 → **beneficial**
- tide_kyc_1 v2 (controller_approved) dims=['welcome_message', 'voice', 'caller_id', 'schedule'] engageΔ=+0.022 didΔ=+0.040 → **beneficial**
- kest_renewal_0 v5 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.050 didΔ=+0.000 → **beneficial**
- kest_renewal_0 v6 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.008 → **neutral**
- nort_renewal_0 v7 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.012 → **neutral**
- tide_renewal_0 v6 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.004 → **neutral**
- tide_cancel_2 v7 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.006 → **neutral**
- nort_cancel_2 v7 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.006 → **neutral**
- arav_cancel_2 v7 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.006 → **neutral**
- arav_renewal_0 v7 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.011 → **neutral**
- nort_renewal_0 v8 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.005 → **neutral**
- kest_kyc_1 v2 (controller_approved) dims=['welcome_message', 'voice', 'caller_id', 'schedule'] engageΔ=+0.022 didΔ=+0.048 → **beneficial**
- arav_renewal_0 v8 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.007 → **neutral**
- nort_renewal_0 v9 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nort_cancel_2 v8 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- kest_renewal_0 v7 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- kest_cancel_2 v7 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- arav_renewal_0 v9 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- arav_cancel_2 v8 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- tide_renewal_0 v7 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- tide_cancel_2 v8 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- arav_cancel_2 v9 (controller_approved) dims=['cohorts', 'welcome_message', 'voice'] engageΔ=+0.071 didΔ=+0.000 → **beneficial**
- nort_cancel_2 v9 (controller_approved) dims=['cohorts', 'welcome_message', 'voice'] engageΔ=+0.065 didΔ=+0.000 → **beneficial**
- tide_cancel_2 v9 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.078 didΔ=+0.000 → **beneficial**
- kest_cancel_2 v8 (controller_approved) dims=['cohorts', 'welcome_message', 'voice'] engageΔ=+0.078 didΔ=+0.000 → **beneficial**
- tide_kyc_1 v3 (controller_approved) dims=['welcome_message', 'voice', 'caller_id', 'schedule'] engageΔ=+0.085 didΔ=+0.168 → **beneficial**
- arav_renewal_0 v10 (controller_approved) dims=['cohorts', 'welcome_message'] engageΔ=+0.051 didΔ=+0.000 → **beneficial**
- kest_renewal_0 v8 (controller_approved) dims=['cohorts', 'welcome_message', 'voice'] engageΔ=+0.066 didΔ=+0.000 → **beneficial**
- kest_renewal_0 v9 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.003 → **neutral**
- arav_kyc_1 v3 (controller_approved) dims=['caller_id', 'schedule'] engageΔ=+0.000 didΔ=+0.225 → **beneficial**
- kest_kyc_1 v3 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'caller_id', 'schedule'] engageΔ=+0.085 didΔ=+0.241 → **beneficial**
- nort_renewal_0 v10 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nort_cancel_2 v10 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- kest_renewal_0 v10 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- kest_cancel_2 v9 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- arav_renewal_0 v11 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- arav_cancel_2 v10 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- tide_renewal_0 v8 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- tide_cancel_2 v10 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- arav_renewal_0 v12 (controller_approved) dims=['cohorts', 'voice'] engageΔ=+0.018 didΔ=+0.000 → **beneficial**
- arav_cancel_2 v11 (controller_approved) dims=['welcome_message'] engageΔ=+0.007 didΔ=+0.000 → **neutral**
- nort_kyc_1 v2 (controller_approved) dims=['welcome_message', 'voice', 'caller_id', 'schedule'] engageΔ=+0.022 didΔ=+0.038 → **beneficial**
- nort_cancel_2 v11 (controller_approved) dims=['cohorts', 'welcome_message', 'voice'] engageΔ=+0.020 didΔ=+0.000 → **beneficial**
- kest_renewal_0 v11 (controller_approved) dims=['cohorts', 'voice'] engageΔ=+0.005 didΔ=+0.000 → **neutral**
- kest_kyc_1 v4 (controller_approved) dims=['caller_id', 'schedule'] engageΔ=+0.000 didΔ=+0.140 → **beneficial**
- tide_kyc_1 v4 (controller_approved) dims=['caller_id', 'schedule'] engageΔ=+0.000 didΔ=+0.163 → **beneficial**
- nort_renewal_0 v11 (controller_approved) dims=['cohorts', 'welcome_message', 'voice'] engageΔ=+0.086 didΔ=+0.000 → **beneficial**
- tide_renewal_0 v9 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.050 didΔ=+0.000 → **beneficial**
- arav_kyc_1 v4 (controller_approved) dims=['welcome_message', 'voice', 'caller_id', 'schedule'] engageΔ=+0.085 didΔ=+0.149 → **beneficial**
- nort_renewal_0 v12 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nort_cancel_2 v12 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- kest_renewal_0 v12 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- kest_cancel_2 v10 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- arav_renewal_0 v13 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- arav_cancel_2 v12 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- tide_renewal_0 v10 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- tide_cancel_2 v11 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- tide_cancel_2 v12 (controller_approved) dims=['welcome_message'] engageΔ=+0.007 didΔ=+0.000 → **neutral**
- nort_kyc_1 v3 (controller_approved) dims=['caller_id', 'schedule'] engageΔ=+0.000 didΔ=+0.178 → **beneficial**
- kest_cancel_2 v11 (controller_approved) dims=['welcome_message'] engageΔ=+0.007 didΔ=+0.000 → **neutral**
- tide_renewal_0 v11 (controller_approved) dims=['cohorts', 'welcome_message', 'voice'] engageΔ=+0.052 didΔ=+0.000 → **beneficial**
- kest_kyc_1 v5 (controller_approved) dims=['caller_id', 'schedule'] engageΔ=+0.000 didΔ=+0.059 → **beneficial**
- arav_kyc_1 v5 (controller_approved) dims=['caller_id', 'schedule'] engageΔ=+0.000 didΔ=+0.064 → **beneficial**
- nort_renewal_0 v13 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nort_cancel_2 v13 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- kest_renewal_0 v13 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- kest_cancel_2 v12 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- arav_renewal_0 v14 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- arav_cancel_2 v13 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- tide_renewal_0 v12 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- tide_cancel_2 v13 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- arav_renewal_0 v15 (controller_approved) dims=['voice'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- tide_kyc_1 v5 (controller_approved) dims=['caller_id', 'schedule'] engageΔ=+0.000 didΔ=+0.044 → **beneficial**
- tide_renewal_0 v13 (controller_approved) dims=['cohorts', 'welcome_message', 'voice'] engageΔ=+0.018 didΔ=+0.000 → **beneficial**
- nort_kyc_1 v4 (controller_approved) dims=['welcome_message', 'voice', 'caller_id', 'schedule'] engageΔ=+0.085 didΔ=+0.085 → **beneficial**
- arav_kyc_1 v6 (controller_approved) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- kest_kyc_1 v6 (controller_approved) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**

## Governance

```
{
  "approval_requests": 47,
  "decisions": {
    "approved": 41,
    "rejected": 6,
    "expired": 0
  },
  "rejection_reasons": {
    "approver declined (judgement call)": 6
  },
  "applied_via_approval": 41,
  "auto_applied": 73,
  "auto_apply_rejected": 0,
  "apply_conflicts": 0,
  "lapsed": 0,
  "peak_requests_per_24h": {
    "nort_renewal_0": 1,
    "nort_kyc_1": 1,
    "nort_cancel_2": 1,
    "arav_renewal_0": 1,
    "arav_kyc_1": 1,
    "arav_cancel_2": 1,
    "tide_renewal_0": 1,
    "tide_kyc_1": 1,
    "tide_cancel_2": 1,
    "kest_renewal_0": 1,
    "kest_kyc_1": 1,
    "kest_cancel_2": 1
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
  "nort_renewal_0:welcome_message=W3": {
    "3": 0.667,
    "4": 0.67
  },
  "kest_renewal_0:welcome_message=W3": {
    "3": 0.675,
    "4": 0.667
  },
  "arav_renewal_0:welcome_message=W3": {
    "3": 0.67,
    "4": 0.668
  }
}
```

Credits used: 0 · validation runs: 0 · LLM fix calls: 0