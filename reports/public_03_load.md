# public_03 load numbers

Machine: Windows-11-10.0.26300-SP0, 8 logical CPUs, Python 3.13.1. Simulator and controller on the same machine.

| metric | value |
|---|---|
| total wall time (bootstrap + 5 simulated days) | 608 s |
| history bootstrap (14 days, chunk 0) | 150.3 s |
| wall seconds per simulated day (advance + ingest + decide) | D0: 246.3, D1: 87.9, D2: 95.8, D3: 92.3, D4: 84.1 |
| mean wall per simulated day | 121.3 s (target < 600 s) |
| ingest throughput (all chunks, parse + commit) | 28,448 events/s over 9,737,508 events in 342 s |
| last decision pass | 209.3 ms (12 workflows) |
| peak RSS (controller) | 481.0 MB |
| store size at end | 580 MB (30.5 MB per simulated day incl. history) |
| calls dialled after D0 (aggregated) | 3,240,000 |
| rows | leads=2,304,000, agg=549,881, calls_log=3,240,000, decisions=400, proposals=42 |

The simulator's own advance time is included in the per-day wall time.
