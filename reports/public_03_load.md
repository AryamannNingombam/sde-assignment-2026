# public_03 load numbers

Machine: Linux-6.18.54.1-microsoft-standard-WSL2-x86_64-with-glibc2.35, 8 logical CPUs, Python 3.10.12. Simulator and controller on the same machine.

| metric | value |
|---|---|
| total wall time (bootstrap + 5 simulated days) | 276 s |
| history bootstrap (14 days, chunk 0) | 84.9 s |
| wall seconds per simulated day (advance + ingest + decide) | D0: 123.2, D1: 33.6, D2: 39.9, D3: 38.7, D4: 39.5 |
| mean wall per simulated day | 55.0 s (target < 600 s) |
| ingest throughput (all chunks, parse + commit) | 60,105 events/s over 9,737,078 events in 162 s |
| last decision pass | 277.2 ms (12 workflows) |
| peak RSS (controller) | 527.7 MB |
| store size at end | 581 MB (30.6 MB per simulated day incl. history) |
| calls dialled after D0 (aggregated) | 3,240,000 |
| rows | leads=2,304,000, agg=560,538, calls_log=3,240,000, decisions=390, proposals=39 |

The simulator's own advance time is included in the per-day wall time.
