"""Run a scenario several times and report the RANGE of results, not a single best run.

    python scripts/multi_run.py scenarios/public_02_incidents.yaml [--runs 3] [--port 8741]

Run 1 uses the scenario as published. Runs 2..N use a temporary copy whose only change is the top-level random
`seed:` (same policies, same hidden truth, different dice), each with its own fresh no-op baseline. That measures
how much a result depends on luck rather than on the controller. Tooling only: the controller never reads a
scenario file. Writes reports/<scenario>_runs.md; run 1's full grade report is copied to reports/<scenario>.md.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.run_scenario import serve, wait_ready  # noqa: E402


def reseeded(scenario: str, name: str, run: int) -> tuple[str, str]:
    """Run 1: the published scenario. Later runs: a copy with only the top-level `seed:` changed."""
    if run == 1:
        return scenario, "published"
    text = (ROOT / scenario).read_text(encoding="utf-8")
    m = re.search(r"^seed:\s*(\d+)\s*$", text, re.M)
    new_seed = int(m[1]) + 1000 * run
    out = ROOT / "runs" / f"multi_scenario_{name}_{run}.yaml"
    out.write_text(text[:m.start()] + f"seed: {new_seed}" + text[m.end():], encoding="utf-8")
    return str(out.relative_to(ROOT)), f"seed {new_seed}"


def one_run(scenario: str, name: str, seed: int, port: int) -> dict:
    scenario, label = reseeded(scenario, name, seed)
    env = {**os.environ, "PYTHONUTF8": "1", "CONTROLLER_STRICT": "1"}
    base, mine = ROOT / "runs" / f"multi_base_{name}_{seed}", ROOT / "runs" / f"multi_mine_{name}_{seed}"
    shutil.rmtree(base, ignore_errors=True)
    subprocess.run([sys.executable, "-m", "sim", "baseline", "--scenario", scenario, "--run-dir", str(base)],
                   cwd=ROOT, env=env, check=True, stdout=subprocess.DEVNULL)
    db = ROOT / "state" / f"multi_{name}_{seed}.db"
    for suffix in ("", "-wal", "-shm"):
        Path(str(db) + suffix).unlink(missing_ok=True)
    url = f"http://127.0.0.1:{port}"
    sim = serve(scenario, mine, port, env)
    try:
        wait_ready(url)
        for w in httpx.get(f"{url}/workflows").json():          # objectives from the API, like the controller
            PRIMARY[w["workflow_id"]] = w["objective"]["primary"]
        subprocess.run([sys.executable, "-m", "controller.main", "--url", url, "--db", str(db)], cwd=ROOT, env=env,
                       check=True, stderr=subprocess.DEVNULL)
    finally:
        sim.terminate()
        sim.wait()
    md = ROOT / "reports" / f"_run_{name}_{seed}.md"
    subprocess.run([sys.executable, "-m", "sim", "grade", "--run", str(mine), "--baseline", str(base), "--out", str(md)],
                   cwd=ROOT, env=env, check=True, stdout=subprocess.DEVNULL)
    g = json.loads(subprocess.run([sys.executable, "-m", "sim", "grade", "--run", str(mine), "--baseline", str(base),
                                   "--json"], cwd=ROOT, env=env, check=True, capture_output=True,
                                  text=True, encoding="utf-8").stdout)
    return {"seed": label, "grade": g, "md": md}


def summarise(name: str, runs: list[dict]) -> str:
    wfs = [w for w in runs[0]["grade"]["kpis"] if w != "ALL"]
    pct = lambda x: "—" if x is None else f"{x * 100:+.1f}%"
    L = [f"# {name}: {len(runs)} runs", "",
         "Run 1 is the published scenario; the others change only its random seed (same policies and hidden truth).",
         "Each run has its own fresh no-op baseline; Δ = change vs that run's baseline.", "",
         "| run | conclusion Δ (ALL) | " + " | ".join(f"{w} primary Δ" for w in wfs) +
         " | changes | harmful | incident MTTR (min) | credits |",
         "|---|---|" + "---|" * len(wfs) + "---|---|---|---|"]
    for r in runs:
        g = r["grade"]
        prim = []
        for w in wfs:
            prim.append(pct(g["delta_vs_baseline"][w][PRIMARY[w]]))
        v = g["controller_changes"]["verdicts"]
        mttr = [i.get("mttr_minutes") for i in g["incidents"] if "mttr_minutes" in i]
        L.append(f"| {r['seed']} | {pct(g['delta_vs_baseline']['ALL']['conclusion_rate'])} | " + " | ".join(prim) +
                 f" | {g['controller_changes']['count']} | {v.get('harmful', 0)} | "
                 f"{', '.join(str(m) for m in mttr) or '—'} | {g['credits_used']:.0f} |")
    allc = [r["grade"]["delta_vs_baseline"]["ALL"]["conclusion_rate"] for r in runs]
    harm = [r["grade"]["controller_changes"]["verdicts"].get("harmful", 0) for r in runs]
    L += ["", f"**Range:** conclusion rate {min(allc) * 100:+.1f}% to {max(allc) * 100:+.1f}% vs baseline; "
              f"harmful changes {min(harm)}-{max(harm)} per run."]
    for r in runs:
        bad = [d for d in r["grade"]["controller_changes"]["detail"] if d["verdict"] == "harmful"]
        for d in bad:
            L.append(f"- seed {r['seed']}: harmful {d['workflow_id']} v{d['version']} dims={d['dims']} "
                     f"engageΔ={d['engage_delta']:+.3f} didΔ={d['did_health_delta']:+.3f}")
    return "\n".join(L) + "\n"


PRIMARY: dict[str, str] = {}        # workflow -> primary KPI, read from GET /workflows during the run


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--port", type=int, default=8741)
    a = ap.parse_args()
    name = Path(a.scenario).stem
    runs = [one_run(a.scenario, name, seed, a.port + i) for i, seed in enumerate(range(1, a.runs + 1))]
    shutil.copy(runs[0]["md"], ROOT / "reports" / f"{name}.md")
    for r in runs:
        r["md"].unlink(missing_ok=True)
    out = ROOT / "reports" / f"{name}_runs.md"
    out.write_text(summarise(name, runs), encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
