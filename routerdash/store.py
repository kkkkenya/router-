"""Usage history (SQLite) and billing-cycle maths."""

import calendar
import json
import sqlite3
import threading
from datetime import datetime, timedelta

WRAP_32 = 2 ** 32
# Fastest plausible line rate, used to reject garbage deltas: 1 Gbit/s, plus headroom.
MAX_BYTES_PER_SEC = 1.5 * 125_000_000


def counter_delta(old, new, seconds):
    """Bytes transferred between two readings of a cumulative counter.

    Handles the two ways a counter goes backwards: a 32-bit wrap (some
    firmware counts in 32 bits, which rolls over every 4.29 GB) and a router
    reboot (counter restarts from zero). Returns None for a reading that
    can't be trusted.
    """
    limit = max(seconds, 1) * MAX_BYTES_PER_SEC
    if new >= old:
        d = new - old
    elif old < WRAP_32 and (WRAP_32 - old + new) <= limit:
        d = WRAP_32 - old + new
    else:
        d = new  # rebooted: everything since boot is new traffic
    return d if d <= limit else None


def cycle_bounds(now, reset_day):
    """Start and end of the billing cycle containing `now` (local time)."""

    def anchor(year, month):
        day = min(reset_day, calendar.monthrange(year, month)[1])
        return datetime(year, month, day)

    start = anchor(now.year, now.month)
    if now < start:
        y, m = (now.year, now.month - 1) if now.month > 1 else (now.year - 1, 12)
        start = anchor(y, m)
    y, m = (start.year, start.month + 1) if start.month < 12 else (start.year + 1, 1)
    return start, anchor(y, m)


def hour_floor(ts):
    return int(datetime.fromtimestamp(ts).replace(minute=0, second=0, microsecond=0).timestamp())


class Store:
    def __init__(self, path):
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock, self._db:
            self._db.executescript("""
                CREATE TABLE IF NOT EXISTS hourly (
                    hour_ts INTEGER PRIMARY KEY, down INTEGER NOT NULL, up INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS adjustments (
                    cycle_start INTEGER PRIMARY KEY, bytes INTEGER NOT NULL);
            """)

    # -- key/value ------------------------------------------------------------

    def get(self, key, default=None):
        with self._lock:
            row = self._db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def put(self, key, value):
        with self._lock, self._db:
            self._db.execute("INSERT OR REPLACE INTO kv VALUES (?,?)", (key, json.dumps(value)))

    # -- counters -------------------------------------------------------------

    def ingest(self, ts, down_total, up_total):
        """Record a counter reading. Returns (down_delta, up_delta, seconds) or None.

        The last reading is persisted, so if this app was closed for a while
        the traffic in between is still counted on restart (unless the
        router rebooted or a 32-bit counter wrapped in the gap).
        """
        last = self.get("last_reading")
        self.put("last_reading", [ts, down_total, up_total])
        if not last:
            return None
        secs = ts - last[0]
        dd = counter_delta(last[1], down_total, secs)
        du = counter_delta(last[2], up_total, secs)
        if dd is None or du is None or secs <= 0:
            return None
        self.add(ts, dd, du)
        return dd, du, secs

    def add(self, ts, down, up):
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO hourly VALUES (?,?,?) ON CONFLICT(hour_ts) DO UPDATE "
                "SET down = down + excluded.down, up = up + excluded.up",
                (hour_floor(ts), int(down), int(up)))

    def hourly(self, start_ts, end_ts):
        with self._lock:
            return self._db.execute(
                "SELECT hour_ts, down, up FROM hourly WHERE hour_ts >= ? AND hour_ts < ? ORDER BY hour_ts",
                (start_ts, end_ts)).fetchall()

    # -- calibration ----------------------------------------------------------

    def set_adjustment(self, cycle_start_ts, nbytes):
        with self._lock, self._db:
            self._db.execute("INSERT OR REPLACE INTO adjustments VALUES (?,?)", (cycle_start_ts, int(nbytes)))

    def adjustment(self, cycle_start_ts):
        with self._lock:
            row = self._db.execute(
                "SELECT bytes FROM adjustments WHERE cycle_start=?", (cycle_start_ts,)).fetchone()
        return row[0] if row else 0

    # -- reporting ------------------------------------------------------------

    def summary(self, now, cap_bytes, reset_day):
        start, end = cycle_bounds(now, reset_day)
        s_ts, e_ts = int(start.timestamp()), int(end.timestamp())
        rows = self.hourly(s_ts, e_ts)
        adj = self.adjustment(s_ts)

        days = {}
        d = start
        while d < end:
            days[d.date().isoformat()] = [0, 0]
            d += timedelta(days=1)
        for ts, dn, up in rows:
            key = datetime.fromtimestamp(ts).date().isoformat()
            if key in days:
                days[key][0] += dn
                days[key][1] += up
        tracked = sum(dn + up for _, dn, up in rows)
        used = max(tracked + adj, 0)

        total_secs = (end - start).total_seconds()
        elapsed = max((now - start).total_seconds(), 1)
        left_secs = max((end - now).total_seconds(), 0)
        projected = used / elapsed * total_secs
        today = days.get(now.date().isoformat(), [0, 0])

        # Heatmap: last 14 days x 24 hours.
        hm_start = (now - timedelta(days=13)).replace(hour=0, minute=0, second=0, microsecond=0)
        heat = {}
        for ts, dn, up in self.hourly(int(hm_start.timestamp()), int(now.timestamp()) + 3600):
            t = datetime.fromtimestamp(ts)
            heat.setdefault(t.date().isoformat(), [0] * 24)[t.hour] += dn + up

        return {
            "cycle_start": start.date().isoformat(),
            "cycle_end": end.date().isoformat(),
            "cap_bytes": cap_bytes,
            "used_bytes": used,
            "tracked_bytes": tracked,
            "adjustment_bytes": adj,
            "projected_bytes": projected,
            "today_bytes": today[0] + today[1],
            "days_total": round(total_secs / 86400),
            "days_left": left_secs / 86400,
            "daily_budget_bytes": max(cap_bytes - used, 0) / max(left_secs / 86400, 1 / 24),
            "even_pace_bytes": cap_bytes / (total_secs / 86400),
            "days": [{"date": k, "down": v[0], "up": v[1]} for k, v in days.items()],
            "heatmap": [{"date": (hm_start + timedelta(days=i)).date().isoformat(),
                         "hours": heat.get((hm_start + timedelta(days=i)).date().isoformat(), [0] * 24)}
                        for i in range(14)],
        }
