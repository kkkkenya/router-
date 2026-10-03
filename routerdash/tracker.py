"""Background poller: reads router counters, records usage, keeps live speed."""

import collections
import threading
import time

from .huawei_ont import LoginError, RouterError

LIVE_WINDOW_SECS = 10 * 60


class Tracker:
    def __init__(self, store, config):
        self.store = store
        self.config = config
        self.router = None
        self.live = collections.deque()
        self.devices = []
        self.devices_at = 0
        self.error = None
        self.last_ok = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None

    def attach(self, router):
        """Start polling a logged-in router (replaces any previous one)."""
        with self._lock:
            self.router = router
            self.live.clear()
            self.devices = []
            self.devices_at = 0
            self.error = None
        if not self._thread:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def detach(self):
        with self._lock:
            self.router = None
            self.live.clear()
            self.devices = []

    def stop(self):
        self._stop.set()

    def _run(self):
        while not self._stop.is_set():
            self.poll_once()
            self._stop.wait(self.config["poll_seconds"])

    def poll_once(self):
        router = self.router
        if router is None:
            return
        counters = self.config.get("counters") or []
        try:
            if counters or router.host == "demo":
                now = time.time()
                down, up = router.read_counters(counters)
                result = self.store.ingest(now, down, up)
                if result:
                    dd, du, secs = result
                    with self._lock:
                        self.live.append((now, dd * 8 / secs, du * 8 / secs))
                        while self.live and self.live[0][0] < now - LIVE_WINDOW_SECS:
                            self.live.popleft()
            if time.time() - self.devices_at > 60:
                devices = router.list_devices()
                with self._lock:
                    self.devices, self.devices_at = devices, time.time()
            self.error = None if counters or router.host == "demo" else "not_configured"
            self.last_ok = time.time()
        except LoginError as e:
            self.error = f"Login failed: {e}"
        except RouterError as e:
            self.error = str(e)

    def live_points(self):
        with self._lock:
            return [{"t": t, "down_bps": d, "up_bps": u} for t, d, u in self.live]
