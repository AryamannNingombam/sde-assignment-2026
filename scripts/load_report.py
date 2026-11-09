"""Turns the controller's own metrics table into the numbers memo 03 and README section 8 ask for.

    python scripts/load_report.py --db state/03/controller.db --out reports/public_03_load.md
"""
import argparse
import os
import sqlite3


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--note", default="", help="free text about the machine the run used")
    a = ap.parse_args()
    db = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    first = db.execute("SELECT * FROM metrics ORDER BY minute LIMIT 1").fetchone()
    rows = db.execute("SELECT * FROM metrics WHERE minute>? ORDER BY minute", (first["minute"],)).fetchall()
    events = sum(r["events"] for r in rows)
    ingest_s = sum(r["ingest_ms"] for r in rows) / 1000
    decide_s = sum(r["decide_ms"] for r in rows) / 1000
    decide = sorted(r["decide_ms"] for r in rows)
    ingest_tick = sorted(r["ingest_ms"] for r in rows)
    busy = [r for r in rows if r["events"] > 0]
    busy_rate = sum(r["events"] for r in busy) * 1000 / max(sum(r["ingest_ms"] for r in busy), 1)
    days: dict[int, list] = {}
    for r in [first] + list(rows):
        days.setdefault(r["minute"] // 1440, []).append(r)
    out = ["# public_03_load: controller throughput", "", a.note, "",
           "## Bootstrap", f"History: {first['events']:,} events in {first['ingest_ms'] / 1000:.1f}s ({first['events'] * 1000 / max(first['ingest_ms'], 1):,.0f} events/s, measured with the simulator on the same machine).", "",
           "## Steady state, after D0 00:00",
           f"- Events ingested: {events:,}",
           f"- Ingest throughput while events were arriving: **{busy_rate:,.0f} events/s**",
           f"- Time in ingest: {ingest_s:.0f}s. Time in decisions: {decide_s:.0f}s.",
           f"- Decide per 15-minute tick (12 workflows): median {decide[len(decide) // 2]} ms, p99 {decide[int(len(decide) * .99)]} ms, max {decide[-1]} ms",
           f"- Ingest per tick: median {ingest_tick[len(ingest_tick) // 2]} ms, p99 {ingest_tick[int(len(ingest_tick) * .99)]} ms, max {ingest_tick[-1]} ms",
           f"- Decision lag: at most one tick (15 simulated minutes) plus the ingest and decide time above",
           f"- Peak memory of the controller: **{max(r['rss_mb'] for r in rows):,.0f} MB**", "",
           "## Wall-clock per simulated day", "", "Includes the simulator itself generating the day, on the same machine.", "",
           "| day | events | wall seconds | ingest s | decide s |", "|---|---|---|---|---|"]
    previous_end = first["wall_s"]
    for day in sorted(days):
        d_rows = [r for r in days[day] if r["minute"] != first["minute"]]
        if not d_rows:
            continue
        end = d_rows[-1]["wall_s"]
        out.append(f"| D{day} | {sum(r['events'] for r in d_rows):,} | {end - previous_end:.0f} | {sum(r['ingest_ms'] for r in d_rows) / 1000:.0f} | {sum(r['decide_ms'] for r in d_rows) / 1000:.0f} |")
        previous_end = end
    size = os.path.getsize(a.db) / (1024 ** 2)
    out += ["", f"Database size at finish: {size:,.0f} MB."]
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
