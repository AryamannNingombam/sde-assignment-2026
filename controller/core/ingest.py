"""Event ingestion: NDJSON chunk -> small aggregates (per workflow x sim-hour x key). Idempotent via per-chunk atomic commit.

Aggregate keys (columns: dials, conn, eng, flag):
  all            every call
  did|<D>        per caller ID: dials and connected (pickup rate)
  prm|<P>        per prompt, connected calls only: conn and hallucination flags
  eng|<dim>|<opt>|<age>|<lang>|<P>   connected calls per variant x lead segment x prompt: conn and engaged
  fla|<P>        per prompt, connected calls with qa: [n, sum(flow_adherence), n(adherence < 0.8), 0]
"""
import json
import sys
from collections import defaultdict

from .timeutil import day_of, hr_of, min_of


class Ingestor:
    def __init__(self, store):
        self.store = store
        self.leads: dict[str, tuple] = {}  # lead_id -> (day, age, lang)
        self.max_day = store.get("max_day", -99)
        self.leads = store.load_leads(self.max_day - 5)

    def process(self, text: str):
        """Returns (agg, new_leads, notable_events, n_events)."""
        agg = defaultdict(lambda: [0, 0, 0, 0])
        new_leads, notable = [], []
        leads = self.leads
        n = 0
        intern = sys.intern
        for line in text.split("\n"):
            if not line:
                continue
            n += 1
            ev = json.loads(line)
            t = ev["type"]
            if t == "call":
                wf = ev["workflow_id"]
                hr = hr_of(ev["ts"])
                v = ev["variant"]
                conn = 1 if ev["connected"] else 0
                a = agg[(wf, hr, "all")]
                a[0] += 1; a[1] += conn
                d = agg[(wf, hr, "did|" + v["caller_id"])]
                d[0] += 1; d[1] += conn
                if conn:
                    eng = 1 if ev["engaged"] else 0
                    a[2] += eng
                    p = v["prompt_version"]
                    pr = agg[(wf, hr, "prm|" + p)]
                    pr[0] += 1; pr[1] += 1
                    qa = ev.get("qa")
                    if qa and qa.get("hallucination_flag"):
                        pr[3] += 1
                    if qa and qa.get("flow_adherence") is not None:
                        fa = qa["flow_adherence"]
                        fl = agg[(wf, hr, "fla|" + p)]
                        fl[0] += 1; fl[1] += fa
                        if fa < 0.8:
                            fl[2] += 1
                    lf = leads.get(ev["lead_id"])
                    if lf:
                        suffix = f"|{lf[1]}|{lf[2]}|{p}"
                        for dim in ("voice", "welcome_message"):
                            e = agg[(wf, hr, f"eng|{dim}|{v[dim]}{suffix}")]
                            e[1] += 1; e[2] += eng
            elif t == "lead":
                f = ev["features"]
                day = day_of(ev["ts"])
                rec = (day, intern(f["age_band"]), intern(f["lang"]))
                leads[ev["lead_id"]] = rec
                new_leads.append((ev["lead_id"], *rec))
                if day > self.max_day:
                    self.max_day = day
            elif t in ("config_changed", "approval_decided", "campaign_created"):
                notable.append(ev)
        return agg, new_leads, notable, n

    def evict_old(self):
        cut = self.max_day - 5
        if len(self.leads) > 50_000:
            self.leads = {k: v for k, v in self.leads.items() if v[0] >= cut}
        self.store.prune_leads(cut)

    @staticmethod
    def event_min(ev) -> int:
        return min_of(ev["ts"])
