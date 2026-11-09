# public_03 load numbers

Machine: Windows-11-10.0.26300-SP0, 8 logical CPUs, Python 3.13.1. Simulator and controller on the same machine.

| metric | value |
|---|---|
| total wall time (bootstrap + 5 simulated days) | 961 s |
| history bootstrap (14 days, chunk 0) | 137.2 s |
| wall seconds per simulated day (advance + ingest + decide) | D0: 237.3, D1: 70.2, D2: 67.6, D3: 64.7, D4: 520.0 |
| mean wall per simulated day | 192.0 s (target < 600 s) |
| ingest throughput (all chunks, parse + commit) | 12,824 events/s over 9,737,502 events in 759 s |
| last decision pass | 109.8 ms (12 workflows) |
| peak RSS (controller) | 481.1 MB |
| store size at end | 582 MB (30.6 MB per simulated day incl. history) |
| calls dialled after D0 (aggregated) | 3,240,000 |
| rows | leads=2,304,000, agg=567,848, calls_log=3,240,000, decisions=390, proposals=40 |

The simulator's own advance time is included in the per-day wall time.
