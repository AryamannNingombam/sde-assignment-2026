"""Hand-rolled Prometheus metrics + health/readiness/metrics HTTP endpoints (stdlib only, no new dependencies)."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60)


def _lbl(labels: tuple) -> str:
    return "{" + ",".join(f'{k}="{v}"' for k, v in labels) + "}" if labels else ""


class Metrics:
    def __init__(self):
        self.lock = threading.Lock()
        self.counters: dict = {}
        self.gauges: dict = {}
        self.hists: dict = {}

    def inc(self, name, v=1.0, **labels):
        with self.lock:
            k = (name, tuple(sorted(labels.items())))
            self.counters[k] = self.counters.get(k, 0.0) + v

    def set(self, name, v, **labels):
        with self.lock:
            self.gauges[(name, tuple(sorted(labels.items())))] = float(v)

    def observe(self, name, v, **labels):
        with self.lock:
            k = (name, tuple(sorted(labels.items())))
            h = self.hists.setdefault(k, [[0] * len(BUCKETS), 0.0, 0])
            for i, b in enumerate(BUCKETS):
                if v <= b:
                    h[0][i] += 1
            h[1] += v
            h[2] += 1

    def render(self) -> str:
        out = []
        with self.lock:
            for typ, d in (("counter", self.counters), ("gauge", self.gauges)):
                for n in sorted({k[0] for k in d}):
                    out.append(f"# TYPE ctrl_{n} {typ}")
                    out += [f"ctrl_{n}{_lbl(l)} {v}" for (nn, l), v in sorted(d.items()) if nn == n]
            for n in sorted({k[0] for k in self.hists}):
                out.append(f"# TYPE ctrl_{n} histogram")
                for (nn, l), (cnt, s, c) in sorted(self.hists.items()):
                    if nn != n:
                        continue
                    out += [f'ctrl_{n}_bucket{_lbl(l + (("le", b),))} {cnt[i]}' for i, b in enumerate(BUCKETS)]
                    out += [f'ctrl_{n}_bucket{_lbl(l + (("le", "+Inf"),))} {c}', f"ctrl_{n}_sum{_lbl(l)} {s}", f"ctrl_{n}_count{_lbl(l)} {c}"]
        return "\n".join(out) + "\n"


def serve(port: int, metrics: Metrics, health, host: str = "0.0.0.0"):
    """health() -> dict with at least `ready` (bool). Serves /healthz, /readyz, /metrics in a daemon thread."""
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/metrics":
                code, body, ct = 200, metrics.render().encode(), "text/plain; version=0.0.4"
            elif self.path in ("/healthz", "/readyz"):
                h = health()
                code = 200 if self.path == "/healthz" or h["ready"] else 503
                body, ct = json.dumps(h, default=str).encode(), "application/json"
            else:
                code, body, ct = 404, b"not found", "text/plain"
            self.send_response(code); self.send_header("Content-Type", ct); self.send_header("Content-Length", str(len(body)))
            self.end_headers(); self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer((host, port), H)
    threading.Thread(target=srv.serve_forever, daemon=True, name="ctrl-http").start()
    return srv
