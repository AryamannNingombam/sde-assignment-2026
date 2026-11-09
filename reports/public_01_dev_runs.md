# public_01_dev: 3 runs

Run 1 is the published scenario; the others change only its random seed (same policies and hidden truth).
Each run has its own fresh no-op baseline; Δ = change vs that run's baseline.

| run | conclusion Δ (ALL) | ks_cancel primary Δ | nw_kyc primary Δ | nw_renewal primary Δ | changes | harmful | incident MTTR (min) | credits |
|---|---|---|---|---|---|---|---|---|
| published | +6.5% | +2.1% | +13.7% | +1.7% | 9 | 0 | — | 0 |
| seed 2101 | +5.3% | +2.0% | +16.9% | +1.0% | 11 | 0 | — | 0 |
| seed 3101 | +3.9% | -2.7% | +16.0% | -0.5% | 11 | 0 | — | 0 |

**Range:** conclusion rate +3.9% to +6.5% vs baseline; harmful changes 0-0 per run.
