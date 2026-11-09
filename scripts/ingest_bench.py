"""Quick check: run the controller's ingestion over a finished baseline run's chunks (benchmark only)."""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from controller.ingest import Ingestor
from controller.store import Store

run, db = sys.argv[1], sys.argv[2]
Path(db).unlink(missing_ok=True)
ing = Ingestor(Store(db))
t0 = time.time(); n = 0
for sub in ("history", "events"):
    for f in sorted((Path(run) / sub).glob("*.jsonl")):
        n += ing.ingest(f.read_text(), sub, int(f.stem))["events"]
dt = time.time() - t0
print(f"{n} events in {dt:.1f}s = {n/dt:,.0f} events/s")
