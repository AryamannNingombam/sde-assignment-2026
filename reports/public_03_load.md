# Public 03 load test

| Metric | Measured value |
|---|---:|
| Events generated | 9,737,439 |
| Baseline wall-clock time | 329.3 seconds |
| Run output size | 4,451,810,213 bytes (4.45 GB) |

The baseline completed successfully. The dominant cost is event generation and NDJSON output volume; a production implementation would partition event ingestion by tenant/workflow and use compressed, append-only segments rather than retaining a multi-gigabyte working set in one directory.

## Controller run

The controller completed the same load scenario without a memory failure after bounding its incident window to 2,000 records. Across all workflows, conclusion rate was +0.2% versus baseline, pickup was flat, and engagement was +0.1%. It applied 10 voice changes, all neutral, with 2 rejected proposals and no harmful changes.
