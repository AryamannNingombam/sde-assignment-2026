# Detector false-positive replay on history

Baselines from the dev window (days -14..-9); shipped thresholds from `controller/settings.py`; the same
verdict functions and persistence rule the controller runs. History may hold real incidents, so these are
upper bounds on the false-positive rate.

| scenario | workflow | window | caller-ID alarms | (windows evaluated) | hallucination alarms | (windows evaluated) |
|---|---|---|---|---|---|---|
| public_01_dev | ks_cancel | dev | 0 | 124 | 0 | 61 |
| public_01_dev | ks_cancel | A | 0 | 88 | 0 | 42 |
| public_01_dev | nw_kyc | dev | 0 | 56 | 0 | 8 |
| public_01_dev | nw_kyc | A | 0 | 40 | 0 | 0 |
| public_01_dev | nw_renewal | dev | 0 | 116 | 0 | 55 |
| public_01_dev | nw_renewal | A | 1 | 84 | 0 | 38 |
| public_02_incidents | ks_cancel | dev | 0 | 124 | 0 | 60 |
| public_02_incidents | ks_cancel | A | 0 | 88 | 0 | 43 |
| public_02_incidents | nw_kyc | dev | 0 | 56 | 0 | 6 |
| public_02_incidents | nw_kyc | A | 0 | 40 | 0 | 0 |
| public_02_incidents | nw_renewal | dev | 0 | 117 | 0 | 55 |
| public_02_incidents | nw_renewal | A | 0 | 84 | 0 | 40 |

- **dev**: caller-ID 0 alarms / 36 workflow-days = 0.000 per workflow-day; hallucination 0 / 36 = 0.000 per workflow-day
- **A**: caller-ID 1 alarms / 24 workflow-days = 0.042 per workflow-day; hallucination 0 / 24 = 0.000 per workflow-day

Holdout A passes the bar of at most 1 alarm per 10 workflow-days. Holdout B stays untouched (no retuning happened).
