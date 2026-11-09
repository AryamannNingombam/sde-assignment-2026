# Grade report — public_03_load

## Outcomes vs baseline (no-op controller)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| arav_cancel_2 | 0.362 | +6.1% | 0.244 | -0.1% | 0.528 | +5.5% | 37% | 393 (408) |
| arav_kyc_1 | 0.465 | +31.4% | 0.269 | +25.6% | 0.594 | -0.3% | 0% | 399 (370) |
| arav_renewal_0 | 0.439 | +9.2% | 0.265 | +0.2% | 0.590 | +8.6% | 41% | 458 (440) |
| kest_cancel_2 | 0.384 | +13.5% | 0.258 | +6.2% | 0.525 | +5.3% | 36% | 424 (411) |
| kest_kyc_1 | 0.434 | +22.8% | 0.254 | +18.6% | 0.595 | +0.1% | 0% | 399 (339) |
| kest_renewal_0 | 0.467 | +16.9% | 0.280 | +6.1% | 0.591 | +8.9% | 42% | 444 (433) |
| nort_cancel_2 | 0.384 | +13.4% | 0.258 | +6.5% | 0.525 | +5.3% | 37% | 426 (393) |
| nort_kyc_1 | 0.469 | +32.3% | 0.271 | +27.3% | 0.594 | -0.2% | 0% | 462 (323) |
| nort_renewal_0 | 0.466 | +15.2% | 0.279 | +5.9% | 0.590 | +7.8% | 41% | 443 (411) |
| tide_cancel_2 | 0.366 | +7.9% | 0.244 | -0.1% | 0.533 | +6.8% | 48% | 403 (407) |
| tide_kyc_1 | 0.469 | +32.8% | 0.272 | +26.7% | 0.594 | +0.4% | 0% | 456 (356) |
| tide_renewal_0 | 0.463 | +15.5% | 0.278 | +5.2% | 0.585 | +7.9% | 34% | 501 (438) |
| ALL | 0.431 | +18.0% | 0.264 | +9.9% | 0.571 | +5.1% | 25% | 5208 (4729) |

## Changes applied by the controller

46 applied — neutral: 23, beneficial: 23

- nort_renewal_0 v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=-0.013 → **neutral**
- nort_cancel_2 v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.006 → **neutral**
- kest_renewal_0 v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=-0.013 → **neutral**
- arav_renewal_0 v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=-0.013 → **neutral**
- arav_cancel_2 v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.006 → **neutral**
- tide_renewal_0 v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=-0.013 → **neutral**
- tide_cancel_2 v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.006 → **neutral**
- nort_cancel_2 v3 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=-0.003 didΔ=+0.000 → **neutral**
- tide_renewal_0 v3 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.020 → **neutral**
- tide_cancel_2 v3 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=-0.003 didΔ=+0.000 → **neutral**
- kest_cancel_2 v2 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.006 → **neutral**
- arav_renewal_0 v3 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.020 → **neutral**
- kest_renewal_0 v3 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.020 → **neutral**
- nort_renewal_0 v3 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.051 didΔ=+0.000 → **beneficial**
- arav_cancel_2 v3 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=-0.003 didΔ=+0.000 → **neutral**
- nort_renewal_0 v4 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.019 → **neutral**
- kest_cancel_2 v3 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=-0.003 didΔ=+0.000 → **neutral**
- kest_renewal_0 v4 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.051 didΔ=+0.000 → **beneficial**
- nort_kyc_1 v2 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.060 → **beneficial**
- arav_renewal_0 v4 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.051 didΔ=+0.000 → **beneficial**
- kest_kyc_1 v2 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.064 → **beneficial**
- tide_kyc_1 v2 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.066 → **beneficial**
- arav_kyc_1 v2 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.066 → **beneficial**
- nort_renewal_0 v5 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.033 → **beneficial**
- kest_renewal_0 v5 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.033 → **beneficial**
- arav_renewal_0 v5 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=-0.006 → **neutral**
- arav_cancel_2 v4 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=-0.006 → **neutral**
- tide_renewal_0 v4 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.033 → **beneficial**
- tide_cancel_2 v4 (controller_auto) dims=['caller_id'] engageΔ=+0.000 didΔ=-0.006 → **neutral**
- arav_cancel_2 v5 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.076 didΔ=+0.000 → **beneficial**
- nort_cancel_2 v4 (controller_approved) dims=['welcome_message', 'voice', 'caller_id'] engageΔ=+0.078 didΔ=+0.035 → **beneficial**
- kest_renewal_0 v6 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.071 didΔ=+0.000 → **beneficial**
- nort_renewal_0 v6 (controller_approved) dims=['cohorts', 'welcome_message', 'voice'] engageΔ=+0.066 didΔ=+0.000 → **beneficial**
- tide_cancel_2 v5 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.104 didΔ=+0.000 → **beneficial**
- kest_cancel_2 v4 (controller_approved) dims=['welcome_message', 'voice', 'caller_id'] engageΔ=+0.077 didΔ=+0.038 → **beneficial**
- arav_renewal_0 v6 (controller_approved) dims=['cohorts', 'welcome_message', 'voice'] engageΔ=+0.071 didΔ=+0.000 → **beneficial**
- tide_kyc_1 v3 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.549 → **beneficial**
- tide_renewal_0 v5 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.050 didΔ=+0.000 → **beneficial**
- nort_kyc_1 v3 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.559 → **beneficial**
- arav_kyc_1 v3 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.569 → **beneficial**
- kest_kyc_1 v3 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.416 → **beneficial**
- tide_renewal_0 v6 (controller_approved) dims=['welcome_message', 'voice'] engageΔ=+0.071 didΔ=+0.000 → **beneficial**
- tide_kyc_1 v4 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nort_renewal_0 v7 (controller_approved) dims=['voice'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- arav_renewal_0 v7 (controller_approved) dims=['voice'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- kest_kyc_1 v4 (controller_approved) dims=['caller_id'] engageΔ=+0.000 didΔ=+0.000 → **neutral**

## Governance

```
{
  "approval_requests": 34,
  "decisions": {
    "approved": 31,
    "rejected": 3,
    "expired": 0
  },
  "rejection_reasons": {
    "approver declined (judgement call)": 3
  },
  "applied_via_approval": 28,
  "auto_applied": 18,
  "auto_apply_rejected": 0,
  "apply_conflicts": 3,
  "lapsed": 0,
  "peak_requests_per_24h": {
    "nort_renewal_0": 1,
    "nort_kyc_1": 1,
    "nort_cancel_2": 1,
    "kest_renewal_0": 2,
    "kest_kyc_1": 1,
    "arav_renewal_0": 2,
    "arav_kyc_1": 1,
    "arav_cancel_2": 1,
    "tide_renewal_0": 2,
    "tide_kyc_1": 1,
    "tide_cancel_2": 1,
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
    "3": 0.741,
    "4": 0.743
  },
  "kest_renewal_0:welcome_message=W3": {
    "3": 0.848,
    "4": 0.852
  },
  "arav_renewal_0:welcome_message=W3": {
    "3": 0.848,
    "4": 0.85
  },
  "tide_renewal_0:welcome_message=W3": {
    "4": 0.849
  }
}
```

Credits used: 0 · validation runs: 0 · LLM fix calls: 0