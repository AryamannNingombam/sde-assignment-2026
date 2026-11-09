# public_02_incidents: 3 runs

Run 1 is the published scenario; the others change only its random seed (same policies and hidden truth).
Each run has its own fresh no-op baseline; Δ = change vs that run's baseline.

| run | conclusion Δ (ALL) | ks_cancel primary Δ | nw_kyc primary Δ | nw_renewal primary Δ | changes | harmful | incident MTTR (min) | credits |
|---|---|---|---|---|---|---|---|---|
| published | +14.7% | +4.8% | +18.6% | -0.7% | 8 | 0 | 330 | 5 |
| seed 2202 | +13.9% | +8.9% | +19.8% | +0.5% | 14 | 0 | 450 | 5 |
| seed 3202 | +16.8% | +7.7% | +18.7% | -0.5% | 9 | 0 | 510 | 10 |

**Range:** conclusion rate +13.9% to +16.8% vs baseline; harmful changes 0-0 per run.
