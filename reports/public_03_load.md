# public_03_load: controller throughput

Measured on a 12-logical-core, 15 GB Windows 11 laptop with the simulator on the same machine. Not the 4 vCPU / 8 GB Linux target.

## Bootstrap
History: 5,537,379 events in 78.8s (70,238 events/s, measured with the simulator on the same machine).

## Steady state, after D0 00:00
- Events ingested: 4,200,140
- Ingest throughput while events were arriving: **33,255 events/s**
- Time in ingest: 147s. Time in decisions: 303s.
- Decide per 15-minute tick (12 workflows): median 685 ms, p99 1358 ms, max 4634 ms
- Ingest per tick: median 294 ms, p99 3312 ms, max 4029 ms
- Decision lag: at most one tick (15 simulated minutes) plus the ingest and decide time above
- Peak memory of the controller: **272 MB**

## Wall-clock per simulated day

Includes the simulator itself generating the day, on the same machine.

| day | events | wall seconds | ingest s | decide s |
|---|---|---|---|---|
| D0 | 840,050 | 71 | 24 | 29 |
| D1 | 840,040 | 108 | 27 | 59 |
| D2 | 840,017 | 137 | 33 | 79 |
| D3 | 840,017 | 172 | 40 | 101 |
| D4 | 840,016 | 80 | 23 | 35 |
| D5 | 0 | 1 | 0 | 0 |

Database size at finish: 140 MB.
