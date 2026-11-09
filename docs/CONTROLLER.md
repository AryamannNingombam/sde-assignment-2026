# Controller runbook

For the engineer who gets paged while the author is on leave. Everything here is in `controller/` (about 2k lines,
Python 3.10+, dependencies: `httpx`, `numpy`; SQLite is in the standard library).

## Run it

```bash
pip install -r requirements.txt
python -m sim serve --scenario scenarios/public_02_incidents.yaml --run-dir runs/mine --force   # the world
./run.sh http://127.0.0.1:8700                    # the controller; resumes from runs/controller.db if it exists
CTL_FRESH=1 ./run.sh http://127.0.0.1:8700        # wipe controller state (do this when the simulator restarted)
CTL_SERVE=1 ./run.sh http://127.0.0.1:8700        # also serve the supervisor view on http://127.0.0.1:8800
scripts/run_scenario.sh public_02_incidents       # sim + controller + grade, report in reports/
python scripts/crash_test.py --kills 7            # kill -9 / hard-exit it at random + named points, check invariants
python -m pytest -q tests
```

## Answer "why did X change?"

```bash
python -m controller why --db runs/controller.db --wf ks_cancel --at "D3 19:00"
python -m controller view --db runs/controller.db           # the one-screen view as JSON
sqlite3 runs/controller.db "select minute,kind,summary from decision where wf='ks_cancel' order by id"
```

`decision` is append-only and is the audit log: every proposal links to the decision row that holds the inputs
(test tables, thresholds, guardrail readings) and the outputs. `proposal` holds the full request, the approver's
outcome and timestamps. `cfgchg` is every config change the simulator reported (including supervisor edits).

## Layout

| file | job |
|---|---|
| `ingest.py` | NDJSON chunk -> aggregate rows + feature join; chunk and cursor commit in one transaction |
| `learn.py` | read-side queries: decay-weighted counts per slice, hour profiles, caller-ID stats |
| `stats.py` | two-proportion test, Benjamini-Hochberg, binomial z. Pure and deterministic |
| `planner.py` | caller-ID, per-person call hour, variant experiments, cohorts, decay and guardrail checks |
| `incidents.py` | hallucination incident state machine |
| `governance.py` | the only code that changes client config; proposal state machine; crash recovery |
| `loop.py` | the tick loop, Track A (auto-apply), the daily approval bundle, supervisor-edit handling |
| `view.py`, `audit.py` | supervisor view / loop health; `why` |

## State, and what a restart does

All state is in one SQLite file (WAL). On start the controller re-reads any event chunk after the stored cursor,
reconciles every non-terminal `proposal` row with `GET /approvals` and the config history, and continues. Nothing is
decided from memory alone. If the file is lost the controller can rebuild aggregates from `history` + `events`
chunks (the simulator keeps them) but loses its proposal ledger, so reconcile by hand (see Playbooks).

## Alerts

`alert` table / `view.json`. Only `severity='page'` should wake a human:

| code | page? | what to look at |
|---|---|---|
| `hallucination_spike` | page | `incident` table; a fix is already being validated/proposed. Look for the proposal in `waiting_on_approver`. |
| `no_validated_fix` | page | no candidate prompt passed validation. A person must choose a prompt. |
| `incident_fix_failed` | page | flag rate stayed high after the fix applied; the prompt itself may be fine and the detector wrong, check `qa` events. |
| `credits_low` | page | fewer than 12 credits during an incident. |
| `approval_lapsed` | warn | an approved change missed its apply window: the loop was stalled. Look at tick time in `metric`. |
| `guardrail_breach` | warn | exploration frozen for that workflow; it recovers on its own when the guardrail KPI does. |
| `caller_id_degraded`, `supervisor_edit`, `stale_base` | info | recorded, never page; they are visible in the supervisor view. |

## Playbooks

* **Controller won't start / crash loops**: run it in the foreground (`python -m controller run --url ... --db ...`);
  the traceback is the answer. State is safe to keep. If a code bug is in a decision path, fix and restart: all
  decision functions are idempotent per `(workflow, day, slot)` through `plan_log`.
* **A proposal is stuck in `intent`**: normal for one tick after a crash; `Gov.reconcile` resolves it by looking the
  proposal id up in `GET /approvals` (adopt) or the config history (auto-apply), and re-sends only if the base version
  is still current.
* **Simulator restarted (new world)**: delete the controller DB (`CTL_FRESH=1`), the old ledger refers to a world that
  no longer exists.
* **Stop it from changing a workflow**: set `hold` for the dims in `wfstate.js` (`{"hold": {"voice": 99999}}`), or
  stop the process; nothing is applied without an explicit call.

## Extending

New lever: add a planner method returning a desired value plus an `info` dict, include the evidence in the
`decision` row, and route it through `Gov.submit_auto` (only if the policy lists the dim) or `Gov.submit_approval`.
Never call the simulator's config endpoints from anywhere else.
