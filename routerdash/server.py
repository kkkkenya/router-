"""Local web server: serves the dashboard and a small JSON API."""

import json
import mimetypes
import os
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config as config_mod
from .huawei_ont import HuaweiONT, RouterError
from .store import cycle_bounds

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
GB = 1000 ** 3


class App:
    def __init__(self, cfg, cfg_path, store, tracker, demo=False):
        self.cfg = cfg
        self.cfg_path = cfg_path
        self.store = store
        self.tracker = tracker
        self.demo = demo

    def save_config(self):
        if not self.demo:
            config_mod.save(self.cfg_path, self.cfg)

    def status(self):
        t = self.tracker
        return {
            "demo": self.demo,
            "logged_in": t.router is not None,
            "router_host": self.cfg["router_host"],
            "username": self.cfg["username"],
            "counters_configured": bool(self.cfg.get("counters")) or self.demo,
            "error": t.error,
            "last_ok": t.last_ok,
            "poll_seconds": self.cfg["poll_seconds"],
            "cap_gb": self.cfg["cap_gb"],
            "reset_day": self.cfg["reset_day"],
        }

    def login(self, body):
        host = (body.get("host") or self.cfg["router_host"]).strip()
        user = (body.get("username") or "").strip()
        pw = body.get("password") or ""
        router = HuaweiONT(host, user, pw, self.cfg.get("password_mode", "auto"))
        router.login()  # raises LoginError / RouterError
        self.cfg.update(router_host=host, username=user, password_mode=router.password_mode,
                        password=pw if body.get("remember") else "")
        self.save_config()
        self.tracker.attach(router)
        self.tracker.poll_once()

    def logout(self):
        self.tracker.detach()
        self.cfg["password"] = ""
        self.save_config()

    def usage(self):
        return self.store.summary(datetime.now(), self.cfg["cap_gb"] * GB, self.cfg["reset_day"])

    def settings(self, body):
        if "cap_gb" in body:
            cap = float(body["cap_gb"])
            if not 1 <= cap <= 100_000:
                raise ValueError("cap must be between 1 and 100000 GB")
            self.cfg["cap_gb"] = cap
        if "reset_day" in body:
            day = int(body["reset_day"])
            if not 1 <= day <= 31:
                raise ValueError("reset day must be 1-31")
            self.cfg["reset_day"] = day
        self.save_config()

    def calibrate(self, body):
        """"Safaricom says I've used X GB": offset this cycle to match."""
        used = float(body["used_gb"]) * GB
        if used < 0:
            raise ValueError("usage can't be negative")
        start, _ = cycle_bounds(datetime.now(), self.cfg["reset_day"])
        tracked = self.usage()["tracked_bytes"]
        self.store.set_adjustment(int(start.timestamp()), used - tracked)


def make_handler(app):
    allowed_hosts = {f"127.0.0.1:{app.cfg['listen_port']}", f"localhost:{app.cfg['listen_port']}"}
    open_to_lan = app.cfg["listen_host"] not in ("127.0.0.1", "localhost")

    class Handler(BaseHTTPRequestHandler):
        server_version = "router-dashboard"

        def log_message(self, fmt, *args):
            pass

        def _send(self, code, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def _host_ok(self):
            # Blocks DNS-rebinding: a website can't pose as localhost.
            return open_to_lan or self.headers.get("Host", "") in allowed_hosts

        def do_GET(self):
            if not self._host_ok():
                return self._send(403, {"error": "bad host"})
            path = self.path.split("?", 1)[0]
            routes = {
                "/api/status": app.status,
                "/api/usage": app.usage,
                "/api/live": lambda: {"points": app.tracker.live_points(), "now": time.time()},
                "/api/devices": lambda: {"devices": app.tracker.devices, "updated": app.tracker.devices_at},
            }
            if path in routes:
                return self._send(200, routes[path]())
            self._static(path)

        def do_POST(self):
            # Requiring a JSON body and a custom header forces a CORS
            # preflight, so other websites can't drive this API.
            if (not self._host_ok() or self.headers.get("X-Router-Dash") != "1"
                    or "application/json" not in self.headers.get("Content-Type", "")):
                return self._send(403, {"error": "forbidden"})
            try:
                n = min(int(self.headers.get("Content-Length", 0)), 64_000)
                body = json.loads(self.rfile.read(n) or b"{}")
            except ValueError:
                return self._send(400, {"error": "bad json"})
            actions = {
                "/api/login": app.login,
                "/api/logout": lambda _b: app.logout(),
                "/api/settings": app.settings,
                "/api/calibrate": app.calibrate,
            }
            action = actions.get(self.path)
            if not action:
                return self._send(404, {"error": "not found"})
            if app.demo and self.path in ("/api/login", "/api/logout"):
                return self._send(200, {"ok": True})
            try:
                action(body)
            except (RouterError, ValueError, KeyError) as e:
                return self._send(400, {"error": str(e)})
            self._send(200, {"ok": True})

        def _static(self, path):
            rel = "index.html" if path in ("/", "") else path.lstrip("/")
            full = os.path.realpath(os.path.join(WEB_DIR, rel))
            if not full.startswith(os.path.realpath(WEB_DIR) + os.sep) or not os.path.isfile(full):
                return self._send(404, {"error": "not found"})
            with open(full, "rb") as f:
                data = f.read()
            ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype.endswith("javascript"):
                ctype += "; charset=utf-8"
            self._send(200, data, ctype)

    return Handler


def serve(app):
    httpd = ThreadingHTTPServer((app.cfg["listen_host"], app.cfg["listen_port"]), make_handler(app))
    return httpd
