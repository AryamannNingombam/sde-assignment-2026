# public_02_incidents: 3 runs

Run 1 is the published scenario; the others change only its random seed (same policies and hidden truth).
Each run has its own fresh no-op baseline; Δ = change vs that run's baseline.

| run | conclusion Δ (ALL) | ks_cancel primary Δ | nw_kyc primary Δ | nw_renewal primary Δ | changes | harmful | incident MTTR (min) | credits |
|---|---|---|---|---|---|---|---|---|
| published | +15.5% | +7.7% | +8.1% | +0.7% | 9 | 0 | 330 | 5 |
| seed 2202 | +17.1% | +9.4% | +16.6% | -2.9% | 11 | 0 | 330 | 15 |
| seed 3202 | +16.2% | +7.4% | +18.1% | -0.7% | 11 | 0 | 330 | 5 |

**Range:** conclusion rate +15.5% to +17.1% vs baseline; harmful changes 0-0 per run.
