"""Dev/CI helper: baseline (cached) -> serve -> ./run.sh-equivalent controller -> grade.

    python scripts/run_scenario.py scenarios/public_01_dev.yaml [--port 8711]

This script drives the *simulator CLI* (allowed for tooling); the controller itself still only sees HTTP.
Output: reports/<scenario>.md, state/<scenario>.db, runs/mine_<scenario>/.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent


def wait_ready(url: str, timeout: float = 60) -> None:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if httpx.get(f"{url}/health", timeout=2).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.3)
    raise SystemExit(f"simulator at {url} did not come up")


def serve(scenario: str, run_dir: Path, port: int) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-m", "sim", "serve", "--scenario", scenario, "--run-dir", str(run_dir),
                             "--port", str(port), "--force"], cwd=ROOT, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario")
    ap.add_argument("--port", type=int, default=8711)
    ap.add_argument("--no-grade", action="store_true")
    a = ap.parse_args()
    name = Path(a.scenario).stem
    base, mine = ROOT / "runs" / f"base_{name}", ROOT / "runs" / f"mine_{name}"
    if not (base / "_truth" / "aggregates.json").exists():
        subprocess.run([sys.executable, "-m", "sim", "baseline", "--scenario", a.scenario, "--run-dir", str(base)],
                       cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    db = ROOT / "state" / f"{name}.db"
    for suffix in ("", "-wal", "-shm"):
        Path(str(db) + suffix).unlink(missing_ok=True)
    url = f"http://127.0.0.1:{a.port}"
    sim = serve(a.scenario, mine, a.port)
    try:
        wait_ready(url)
        t0 = time.time()
        env = {**os.environ, "CONTROLLER_STRICT": "1"}   # dev runs: fail loudly instead of paging
        subprocess.run([sys.executable, "-m", "controller.main", "--url", url, "--db", str(db)], cwd=ROOT, check=True,
                       env=env)
        print(f"controller wall time: {time.time() - t0:.1f}s", file=sys.stderr)
    finally:
        sim.terminate()
        sim.wait()
    if not a.no_grade:
        out = ROOT / "reports" / f"{name}.md"
        out.parent.mkdir(exist_ok=True)
        env = {**os.environ, "PYTHONUTF8": "1"}        # the grade report contains non-ASCII; Windows needs this
        subprocess.run([sys.executable, "-m", "sim", "grade", "--run", str(mine), "--baseline", str(base),
                        "--out", str(out)], cwd=ROOT, check=True, env=env, stdout=subprocess.DEVNULL)
        print(f"grade report: {out}")


if __name__ == "__main__":
    main()
