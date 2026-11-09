# Grade report — public_03_load

## Outcomes vs baseline (no-op controller)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| arav_cancel_2 | 0.341 | -0.2% | 0.244 | +0.0% | 0.501 | +0.0% | 2% | 438 (408) |
| arav_kyc_1 | 0.358 | +1.3% | 0.214 | -0.2% | 0.602 | +1.1% | 2% | 352 (370) |
| arav_renewal_0 | 0.401 | -0.4% | 0.264 | -0.2% | 0.544 | +0.1% | 0% | 401 (440) |
| kest_cancel_2 | 0.341 | +0.7% | 0.244 | +0.3% | 0.499 | +0.1% | 2% | 390 (411) |
| kest_kyc_1 | 0.358 | +1.3% | 0.215 | +0.6% | 0.597 | +0.5% | 2% | 366 (339) |
| kest_renewal_0 | 0.402 | +0.7% | 0.264 | +0.2% | 0.545 | +0.6% | 0% | 445 (433) |
| nort_cancel_2 | 0.337 | -0.5% | 0.243 | +0.3% | 0.495 | -0.8% | 1% | 387 (393) |
| nort_kyc_1 | 0.360 | +1.7% | 0.215 | +0.9% | 0.599 | +0.7% | 2% | 355 (323) |
| nort_renewal_0 | 0.405 | +0.1% | 0.265 | +0.4% | 0.547 | -0.0% | 0% | 461 (411) |
| tide_cancel_2 | 0.339 | -0.0% | 0.244 | -0.2% | 0.497 | -0.3% | 2% | 374 (407) |
| tide_kyc_1 | 0.356 | +0.6% | 0.214 | -0.3% | 0.597 | +0.8% | 2% | 353 (356) |
| tide_renewal_0 | 0.400 | -0.1% | 0.262 | -0.7% | 0.545 | +0.4% | 0% | 462 (438) |
| ALL | 0.367 | +0.4% | 0.241 | +0.1% | 0.545 | +0.3% | 1% | 4784 (4729) |

## Changes applied by the controller

12 applied — neutral: 12

- nort_renewal_0 v2 (controller_approved) dims=['voice'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- kest_renewal_0 v2 (controller_approved) dims=['voice'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- kest_kyc_1 v2 (controller_approved) dims=['voice'] engageΔ=+0.007 didΔ=+0.000 → **neutral**
- kest_cancel_2 v2 (controller_approved) dims=['voice'] engageΔ=+0.003 didΔ=+0.000 → **neutral**
- arav_kyc_1 v2 (controller_approved) dims=['voice'] engageΔ=+0.007 didΔ=+0.000 → **neutral**
- arav_cancel_2 v2 (controller_approved) dims=['voice'] engageΔ=+0.003 didΔ=+0.000 → **neutral**
- tide_renewal_0 v2 (controller_approved) dims=['voice'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- tide_cancel_2 v2 (controller_approved) dims=['voice'] engageΔ=+0.003 didΔ=+0.000 → **neutral**
- nort_kyc_1 v2 (controller_approved) dims=['voice'] engageΔ=+0.007 didΔ=+0.000 → **neutral**
- nort_cancel_2 v2 (controller_approved) dims=['voice'] engageΔ=+0.003 didΔ=+0.000 → **neutral**
- arav_renewal_0 v2 (controller_approved) dims=['voice'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- tide_kyc_1 v2 (controller_approved) dims=['voice'] engageΔ=+0.007 didΔ=+0.000 → **neutral**

## Governance

```
{
  "approval_requests": 16,
  "decisions": {
    "approved": 12,
    "rejected": 4,
    "expired": 0
  },
  "rejection_reasons": {
    "approver declined (judgement call)": 4
  },
  "applied_via_approval": 12,
  "auto_applied": 0,
  "auto_apply_rejected": 0,
  "apply_conflicts": 0,
  "lapsed": 0,
  "peak_requests_per_24h": {
    "nort_renewal_0": 1,
    "nort_kyc_1": 1,
    "nort_cancel_2": 1,
    "kest_renewal_0": 1,
    "kest_kyc_1": 1,
    "kest_cancel_2": 1,
    "arav_renewal_0": 1,
    "arav_kyc_1": 1,
    "arav_cancel_2": 1,
    "tide_renewal_0": 1,
    "tide_kyc_1": 1,
    "tide_cancel_2": 1
  }
}
```

## Incidents

```
[]
```

## Decaying variants — share of in-population calls still on the variant, by day after onset

```
{}
```

Credits used: 0 · validation runs: 0 · LLM fix calls: 0