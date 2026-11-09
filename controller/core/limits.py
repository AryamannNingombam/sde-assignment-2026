"""Token bucket on SIM time (minutes), one bucket per key (workflow). Caps credit-spending calls so one incident cannot drain credits."""


class TokenBucket:
    def __init__(self, capacity: float = 6, refill_per_min: float = 1 / 30):
        self.capacity, self.rate = capacity, refill_per_min
        self.b: dict[str, tuple[float, float]] = {}   # key -> (tokens, last_min)

    def take(self, key: str, now_min: float, n: float = 1) -> bool:
        tokens, last = self.b.get(key, (self.capacity, now_min))
        tokens = min(self.capacity, tokens + max(0.0, now_min - last) * self.rate)
        ok = tokens >= n
        self.b[key] = (tokens - n if ok else tokens, now_min)
        return ok
