# Grade report — public_03_load

## Outcomes vs baseline (no-op controller)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| arav_cancel_2 | 0.408 | +21.1% | 0.276 | +13.3% | 0.525 | +5.8% | 37% | 447 (409) |
| arav_kyc_1 | 0.469 | +30.8% | 0.266 | +23.6% | 0.608 | +1.2% | 18% | 411 (352) |
| arav_renewal_0 | 0.484 | +19.3% | 0.292 | +10.7% | 0.584 | +6.7% | 40% | 448 (408) |
| kest_cancel_2 | 0.405 | +20.3% | 0.272 | +12.3% | 0.527 | +5.6% | 38% | 420 (418) |
| kest_kyc_1 | 0.476 | +33.8% | 0.259 | +21.1% | 0.629 | +5.2% | 32% | 444 (370) |
| kest_renewal_0 | 0.484 | +20.3% | 0.292 | +10.5% | 0.584 | +7.3% | 40% | 473 (403) |
| nort_cancel_2 | 0.405 | +19.4% | 0.274 | +12.2% | 0.524 | +5.2% | 38% | 422 (368) |
| nort_kyc_1 | 0.359 | +1.0% | 0.218 | +1.1% | 0.595 | -0.2% | 1% | 341 (318) |
| nort_renewal_0 | 0.478 | +18.0% | 0.292 | +10.6% | 0.579 | +5.7% | 31% | 495 (419) |
| tide_cancel_2 | 0.408 | +19.0% | 0.274 | +12.0% | 0.528 | +5.4% | 38% | 422 (401) |
| tide_kyc_1 | 0.473 | +32.8% | 0.260 | +21.3% | 0.625 | +4.5% | 32% | 402 (376) |
| tide_renewal_0 | 0.475 | +17.5% | 0.293 | +10.9% | 0.572 | +4.7% | 23% | 488 (425) |
| ALL | 0.444 | +21.0% | 0.272 | +13.1% | 0.573 | +4.9% | 30% | 5213 (4667) |

## Changes applied by the controller

115 applied — neutral: 80, beneficial: 35

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
- kest_kyc_1 v3 (controller_approved) dims=['welcome_message', 'voice', 'caller_id', 'schedule'] engageΔ=+0.085 didΔ=+0.250 → **beneficial**
- nort_renewal_0 v10 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nort_cancel_2 v10 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- kest_renewal_0 v10 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- kest_cancel_2 v9 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- arav_renewal_0 v11 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- arav_cancel_2 v10 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- tide_renewal_0 v8 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- tide_cancel_2 v10 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nort_cancel_2 v11 (controller_approved) dims=['cohorts', 'welcome_message', 'voice'] engageΔ=+0.011 didΔ=+0.000 → **beneficial**
- arav_kyc_1 v4 (controller_approved) dims=['cohorts', 'welcome_message', 'voice', 'caller_id', 'schedule'] engageΔ=+0.056 didΔ=+0.137 → **beneficial**
- nort_renewal_0 v11 (controller_approved) dims=['cohorts', 'welcome_message', 'voice'] engageΔ=+0.082 didΔ=+0.000 → **beneficial**
- arav_renewal_0 v12 (controller_approved) dims=['cohorts', 'voice'] engageΔ=+0.018 didΔ=+0.000 → **beneficial**
- arav_cancel_2 v11 (controller_approved) dims=['cohorts', 'welcome_message', 'voice'] engageΔ=+0.004 didΔ=+0.000 → **neutral**
- kest_cancel_2 v10 (controller_approved) dims=['cohorts', 'welcome_message', 'voice'] engageΔ=+0.007 didΔ=+0.000 → **neutral**
- tide_renewal_0 v9 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.050 didΔ=+0.000 → **beneficial**
- kest_renewal_0 v11 (controller_approved) dims=['cohorts', 'voice'] engageΔ=+0.005 didΔ=+0.000 → **neutral**
- tide_kyc_1 v4 (controller_approved) dims=['caller_id', 'schedule'] engageΔ=+0.000 didΔ=+0.092 → **beneficial**
- nort_renewal_0 v12 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nort_cancel_2 v12 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- kest_renewal_0 v12 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- kest_cancel_2 v11 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- arav_renewal_0 v13 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- arav_cancel_2 v12 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- tide_renewal_0 v10 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- tide_cancel_2 v11 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- tide_cancel_2 v12 (controller_approved) dims=['welcome_message'] engageΔ=+0.007 didΔ=+0.000 → **neutral**
- nort_cancel_2 v13 (controller_approved) dims=['cohorts', 'welcome_message', 'voice'] engageΔ=+0.012 didΔ=+0.000 → **beneficial**
- arav_cancel_2 v13 (controller_approved) dims=['voice'] engageΔ=+0.008 didΔ=+0.000 → **neutral**
- tide_renewal_0 v11 (controller_approved) dims=['cohorts', 'welcome_message', 'voice'] engageΔ=+0.071 didΔ=+0.000 → **beneficial**
- nort_kyc_1 v2 (controller_approved) dims=['welcome_message', 'voice', 'caller_id', 'schedule'] engageΔ=+0.022 didΔ=+0.046 → **beneficial**
- kest_kyc_1 v4 (controller_approved) dims=['caller_id', 'schedule'] engageΔ=+0.000 didΔ=+0.122 → **beneficial**
- tide_kyc_1 v5 (controller_approved) dims=['caller_id', 'schedule'] engageΔ=+0.000 didΔ=+0.096 → **beneficial**
- nort_renewal_0 v13 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nort_cancel_2 v14 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- kest_renewal_0 v13 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- kest_cancel_2 v12 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- arav_renewal_0 v14 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- arav_cancel_2 v14 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- tide_renewal_0 v12 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- tide_cancel_2 v13 (controller_auto) dims=['schedule'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nort_kyc_1 v3 (controller_approved) dims=['caller_id', 'schedule'] engageΔ=+0.000 didΔ=+0.205 → **beneficial**
- arav_kyc_1 v5 (controller_approved) dims=['cohorts', 'welcome_message', 'caller_id', 'schedule'] engageΔ=+0.011 didΔ=+0.037 → **beneficial**
- nort_renewal_0 v14 (controller_approved) dims=['cohorts', 'voice'] engageΔ=+0.003 didΔ=+0.000 → **neutral**
- tide_kyc_1 v6 (controller_approved) dims=['caller_id', 'schedule'] engageΔ=+0.000 didΔ=+0.033 → **beneficial**
- arav_renewal_0 v15 (controller_approved) dims=['cohorts', 'voice'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- kest_renewal_0 v14 (controller_approved) dims=['cohorts', 'voice'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- kest_kyc_1 v5 (controller_approved) dims=['caller_id', 'schedule'] engageΔ=+0.000 didΔ=+0.042 → **beneficial**

## Governance

```
{
  "approval_requests": 51,
  "decisions": {
    "approved": 42,
    "rejected": 9,
    "expired": 0
  },
  "rejection_reasons": {
    "approver declined (judgement call)": 9
  },
  "applied_via_approval": 42,
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
    "4": 0.669
  },
  "kest_renewal_0:welcome_message=W3": {
    "3": 0.669,
    "4": 0.67
  },
  "arav_renewal_0:welcome_message=W3": {
    "3": 0.675,
    "4": 0.671
  }
}
```

Credits used: 0 · validation runs: 0 · LLM fix calls: 0