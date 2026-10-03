"""A fake router with realistic traffic, for trying the dashboard without hardware."""

import math
import random
import time
from datetime import datetime, timedelta

GB = 1000 ** 3


def _evening_curve(hour):
    """Relative household traffic by hour: quiet overnight, peak around 21:00."""
    return 0.15 + math.exp(-((hour - 21) ** 2) / 8) + 0.4 * math.exp(-((hour - 13) ** 2) / 10)


class DemoRouter:
    host = "demo"

    def __init__(self, username="", password=""):
        self.logged_in = False
        self._down = 3_000_000_000
        self._up = 400_000_000
        self._t = time.time()

    def login(self):
        self.logged_in = True

    def read_counters(self, sources=None):
        now = time.time()
        dt, self._t = now - self._t, now
        h = datetime.now().hour + datetime.now().minute / 60
        down_rate = 2_500_000 * _evening_curve(h) * random.uniform(0.3, 1.8)
        if random.random() < 0.08:
            down_rate *= 4  # someone starts a 4K stream or a game update
        self._down += int(down_rate * dt)
        self._up += int(down_rate * dt * random.uniform(0.06, 0.15))
        return self._down, self._up

    def list_devices(self):
        return [
            {"name": "Living-room TV", "ip": "192.168.100.11", "mac": "3C:2E:F9:10:4A:01", "online": True, "connection": "LAN"},
            {"name": "iPhone", "ip": "192.168.100.23", "mac": "A4:83:E7:22:91:0C", "online": True, "connection": "Wi-Fi"},
            {"name": "Galaxy A54", "ip": "192.168.100.24", "mac": "D0:1B:49:5C:7E:33", "online": True, "connection": "Wi-Fi"},
            {"name": "Work laptop", "ip": "192.168.100.31", "mac": "F4:6D:04:AA:12:9B", "online": True, "connection": "Wi-Fi"},
            {"name": "PS5", "ip": "192.168.100.40", "mac": "00:D9:D1:3F:66:20", "online": False, "connection": "LAN"},
            {"name": "Unknown device", "ip": "192.168.100.52", "mac": "6E:14:9A:0B:C2:7D", "online": True, "connection": "Wi-Fi"},
        ]


def seed_history(store, reset_day):
    """Fill the store with ~6 weeks of plausible hourly usage (only if empty)."""
    if store.get("demo_seeded"):
        return
    rng = random.Random(7)
    now = datetime.now().replace(minute=0, second=0, microsecond=0)
    t = now - timedelta(days=42)
    while t < now:
        weekend = 1.35 if t.weekday() >= 5 else 1.0
        down = 0.95 * GB * _evening_curve(t.hour) * weekend * rng.uniform(0.5, 1.6)
        if rng.random() < 0.03:
            down += rng.uniform(15, 60) * GB  # console or OS update
        store.add(t.timestamp(), down, down * rng.uniform(0.06, 0.14))
        t += timedelta(hours=1)
    store.put("demo_seeded", True)
