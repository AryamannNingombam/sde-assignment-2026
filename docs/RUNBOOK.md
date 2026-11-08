# Controller runbook

For the engineer who gets paged. Design reasoning is in [SUBMISSION.md](../SUBMISSION.md). This file
is how to run it, read it and fix it.

## Run it

```bash
python -m venv .venv && . .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python -m sim baseline --scenario scenarios/public_02_incidents.yaml --run-dir runs/base02
python -m sim serve    --scenario scenarios/public_02_incidents.yaml --run-dir runs/mine02 --force   # terminal 1
./run.sh http://127.0.0.1:8700                                                                       # terminal 2
python -m sim grade --run runs/mine02 --baseline runs/base02 --out reports/public_02.md
```

On Windows set `PYTHONUTF8=1` before `sim grade`, because the report contains a non-ASCII character.
If `pip` fails with a certificate error behind antivirus HTTPS scanning, add `--use-feature=truststore`.

Tests: `python -m pytest -q tests`. Kill/restart test: `python scripts/crash_test.py`.

State lives in `state/controller.db`, set with `--db` or `CONTROLLER_DB`. Raw events for per-call
audit are in `state/events/`. If the simulator was restarted, the old database is set aside as
`*.old` automatically and a fresh one starts.

## See what it is doing

All of these are read-only and safe while the loop is running.

| Question | Command |
|---|---|
| Is the loop healthy? | `python -m controller health` |
| One screen for a supervisor | `python -m controller view --workflow ks_cancel` |
| Why did this change? | `python -m controller why --workflow ks_cancel --at "D3 18:00"` |
| What did this person hear, and why? | `python -m controller why-call --lead nw_renewal:l00012345 --day 3` |

Anything else: `sqlite3 state/controller.db`. The `decisions` table is the append-only audit log, and
`kind` is the useful filter.

## How it works, in one minute

Every 15 simulated minutes: ingest new chunks, then for each workflow pick up config edits, progress
open proposals, run detectors, once a day review experiments, and send any queued changes.

- `controller/ingest.py`: each chunk's rollups and cursor commit in one transaction.
- `controller/cohorts.py`: the single cohort definition.
- `controller/experiments.py`: experiment design, winners, slices, decay.
- `controller/incidents.py`: hallucination, caller-ID and drift detection, and the fix workflow.
- `controller/governance.py`: every config change goes through here.
- `controller/evidence.py`: impact score, affected leads, dry run.
- `controller/config.py`: every tunable, with why it has that value.

## Alerts

`health` lists open alerts. Pages need someone now, tickets can wait until morning.

| Alert | Severity | What it means | What to do |
|---|---|---|---|
| `Incident ... needs a human` | page | A hallucination incident has no fix it can apply: nothing passed validation, the credit cap was reached, or approvers kept declining | Run `why` on the workflow. Talk to the client's approver, or validate a candidate prompt by hand |
| `Only N credits remain` | page | The next incident may not be fixable | Top up credits, or lower `VALIDATION_N` |
| `drift ...` | ticket | A KPI moved 10%+ against the same hours last week. Expected after a promotion | Check `view` for a change that explains it. If nothing does, investigate |
| `routine changes are waiting for approval request budget` | ticket | The workflow hit its request cap | Usually none. Persistent means too many changes are being generated |
| `calls had no lead record` | ticket | A call arrived without its lead, so it is in cohort -1 | Check ingest ordering |

A process crash does not page by itself. `run.sh` restarts the controller, which resumes from its
database. Investigate if it restarts repeatedly (`controller exited with` in stderr).

## When something goes wrong

**The controller crashes.** Restart it. It re-reads anything not committed, asks the simulator what
happened to each open proposal, and carries on. Do not edit the database first.

**A proposal is stuck.** `SELECT * FROM proposals WHERE status IN ('drafted','pending','approved','applying')`.
The next tick should move it. If it does not, compare with `GET /approvals/{id}` on the simulator.

**A client says we changed something we should not have.** Run `why` for the time they name. It shows
the actor, the approval id and the evidence. If the actor is `supervisor`, the change was theirs.

**Stop all changes on a workflow.** Stop the controller, then `UPDATE intents SET status='cancelled'
WHERE workflow_id='X' AND status='queued'`. There is no pause switch yet (see SUBMISSION.md section 13).

## Extending it

- New detector: add a method to `Incidents` and call it from `step`. Thresholds go in `config.py`.
  A detector run every tick needs a p-value that accounts for its look count, and an exact test if
  the expected count is small.
- New kind of change: enqueue an intent with data-only ops (`configops.py`) so it can be replayed on a
  new base. If the claim behind it can go out of date, register it in `governance.on_released`.
- Change allocation weights only through `configops`. The weight grid is what stops a write reporting
  a dimension as changed when it was not.
