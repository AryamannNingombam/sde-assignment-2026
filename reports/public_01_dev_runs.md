# public_01_dev: 3 runs

Run 1 is the published scenario; the others change only its random seed (same policies and hidden truth).
Each run has its own fresh no-op baseline; Δ = change vs that run's baseline.

| run | conclusion Δ (ALL) | ks_cancel primary Δ | nw_kyc primary Δ | nw_renewal primary Δ | changes | harmful | incident MTTR (min) | credits |
|---|---|---|---|---|---|---|---|---|
| published | +3.0% | +0.1% | +17.4% | +2.5% | 9 | 0 | — | 0 |
| seed 2101 | +4.4% | -0.2% | +17.5% | +3.0% | 7 | 0 | — | 0 |
| seed 3101 | +4.0% | -0.8% | +21.2% | +1.2% | 6 | 0 | — | 0 |

**Range:** conclusion rate +3.0% to +4.4% vs baseline; harmful changes 0-0 per run.
