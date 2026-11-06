# Outcome-First Agent Loop Controller

Controller for the Formi SDE-2026 assignment.

## Run

```bash
./run.sh
```

## Configuration

All settings are environment variables (see `config.py`):

| variable            | default                  | meaning                        |
|---------------------|--------------------------|--------------------------------|
| `SIM_BASE_URL`      | `http://localhost:8700`  | simulator base URL             |
| `TICK_MINUTES`      | `15`                     | simulated minutes per tick     |
| `DB_PATH`           | `./controller.db`        | SQLite state file              |
| `HTTP_TIMEOUT`      | `30`                     | HTTP timeout in seconds        |
| `IDLE_SLEEP_SECONDS`| `1.0`                    | wall-clock sleep between ticks |