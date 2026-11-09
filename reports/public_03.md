# Grade report — public_03_load

## Outcomes vs baseline (no-op controller)

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| arav_cancel_2 | 0.338 | -0.9% | 0.244 | +0.0% | 0.497 | -0.6% | 2% | 381 (408) |
| arav_kyc_1 | 0.355 | +0.4% | 0.214 | -0.2% | 0.596 | +0.1% | 2% | 361 (370) |
| arav_renewal_0 | 0.402 | +0.0% | 0.265 | +0.2% | 0.544 | +0.2% | 0% | 386 (440) |
| kest_cancel_2 | 0.340 | +0.3% | 0.244 | +0.4% | 0.497 | -0.4% | 0% | 427 (411) |
| kest_kyc_1 | 0.357 | +1.1% | 0.213 | -0.5% | 0.600 | +1.0% | 2% | 359 (339) |
| kest_renewal_0 | 0.400 | +0.0% | 0.263 | -0.4% | 0.546 | +0.6% | 0% | 408 (433) |
| nort_cancel_2 | 0.341 | +0.5% | 0.244 | +0.6% | 0.499 | +0.1% | 2% | 417 (393) |
| nort_kyc_1 | 0.356 | +0.6% | 0.214 | +0.3% | 0.599 | +0.5% | 2% | 350 (323) |
| nort_renewal_0 | 0.404 | -0.2% | 0.264 | +0.3% | 0.547 | -0.1% | 0% | 431 (411) |
| tide_cancel_2 | 0.338 | -0.4% | 0.244 | -0.2% | 0.496 | -0.5% | 2% | 369 (407) |
| tide_kyc_1 | 0.355 | +0.5% | 0.214 | -0.3% | 0.593 | +0.2% | 0% | 350 (356) |
| tide_renewal_0 | 0.401 | -0.0% | 0.264 | -0.2% | 0.544 | +0.4% | 0% | 454 (438) |
| ALL | 0.366 | +0.2% | 0.241 | +0.0% | 0.544 | +0.1% | 1% | 4693 (4729) |

## Changes applied by the controller

10 applied — neutral: 10

- nort_renewal_0 v2 (controller_approved) dims=['voice'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- nort_kyc_1 v2 (controller_approved) dims=['voice'] engageΔ=+0.007 didΔ=+0.000 → **neutral**
- nort_cancel_2 v2 (controller_approved) dims=['voice'] engageΔ=+0.003 didΔ=+0.000 → **neutral**
- kest_renewal_0 v2 (controller_approved) dims=['voice'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- kest_kyc_1 v2 (controller_approved) dims=['voice'] engageΔ=+0.007 didΔ=+0.000 → **neutral**
- arav_renewal_0 v2 (controller_approved) dims=['voice'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- arav_kyc_1 v2 (controller_approved) dims=['voice'] engageΔ=+0.007 didΔ=+0.000 → **neutral**
- arav_cancel_2 v2 (controller_approved) dims=['voice'] engageΔ=+0.003 didΔ=+0.000 → **neutral**
- tide_renewal_0 v2 (controller_approved) dims=['voice'] engageΔ=+0.000 didΔ=+0.000 → **neutral**
- tide_cancel_2 v2 (controller_approved) dims=['voice'] engageΔ=+0.003 didΔ=+0.000 → **neutral**

## Governance

```
{
  "approval_requests": 12,
  "decisions": {
    "approved": 10,
    "rejected": 2,
    "expired": 0
  },
  "rejection_reasons": {
    "approver declined (judgement call)": 2
  },
  "applied_via_approval": 10,
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