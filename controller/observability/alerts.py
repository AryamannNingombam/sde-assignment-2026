"""Alerts: always a structured ERROR log line; additionally POST to CTRL_ALERT_WEBHOOK (Slack-style {"text": ...}) if set.
Deduplicated per key for `cooldown` seconds; a failing webhook never affects the controller."""
import os
import time

import httpx


class Alerter:
    def __init__(self, log, cooldown: float = 300.0, webhook: str | None = None, clock=time.monotonic):
        self.log, self.cooldown, self.clock = log, cooldown, clock
        self.webhook = webhook if webhook is not None else os.environ.get("CTRL_ALERT_WEBHOOK")
        self.last: dict[str, float] = {}

    def fire(self, key: str, msg: str, **fields) -> bool:
        now = self.clock()
        if key in self.last and now - self.last[key] < self.cooldown:
            return False
        self.last[key] = now
        self.log("ALERT: " + msg, "error", alert=key, **fields)
        if self.webhook:
            try:
                httpx.post(self.webhook, json={"text": f":rotating_light: controller: {msg}"}, timeout=3)
            except Exception:
                pass
        return True
