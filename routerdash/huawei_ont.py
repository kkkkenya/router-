"""Client for Huawei fibre ONTs (EG8145V5, HG8145V5, HG8245H and similar).

These are the boxes Safaricom Home Fibre installs, usually at 192.168.100.1.
They have no public API, so this logs in the same way the web page does and
reads the data embedded in the status pages.

Login flow (matches the router's own login.asp):
  1. POST /asp/GetRandCount.asp            -> one-time token
  2. POST /login.cgi  UserName, PassWord, x.X_HW_Token
     with cookie "Cookie=body:Language:english:id=-1"
  3. The response sets "Cookie=sid=...", which authorises later requests.
"""

import base64
import hashlib
import re
import urllib.error
import urllib.parse
import urllib.request

from . import parse

DEFAULT_HOST = "192.168.100.1"
PRE_LOGIN_COOKIE = "Cookie=body:Language:english:id=-1"
USER_AGENT = "Mozilla/5.0 (router-dashboard)"

# Pages that list connected devices on the firmware versions we know about.
DEVICE_PAGES = [
    "/html/bbsp/common/GetLanUserDevInfo.asp",
    "/html/bbsp/userdevinfo/userdevinfo.asp",
]

# Status pages worth scanning for traffic counters during `probe`.
PROBE_PAGES = [
    "/html/bbsp/waninfo/waninfo.asp",
    "/html/bbsp/common/wan_list.asp",
    "/html/bbsp/common/wan_list_info.asp",
    "/html/bbsp/common/waninfo.asp",
    "/html/amp/ethinfo/ethinfo.asp",
    "/html/amp/wlaninfo/wlaninfo.asp",
    "/html/amp/wlaninfo/wlaninfo_5g.asp",
    "/html/ssmp/deviceinfo/deviceinfo.asp",
    "/html/amp/opticinfo/opticinfo.asp",
] + DEVICE_PAGES

# Never fetch anything that could change router state.
UNSAFE_PATH_RE = re.compile(r"reboot|reset|restore|logout|upgrade|factory|\.cgi", re.I)


class RouterError(Exception):
    pass


class LoginError(RouterError):
    pass


def encode_password(password, mode, username="", token=""):
    """Encode the password the way the router's login page does.

    "base64" is what most EG8145V5/HG8145V5 firmware uses. Some newer
    firmware hashes it instead; the "sha256" mode follows community notes for
    those and hasn't been checked against a Safaricom unit.
    """
    if mode == "sha256":
        inner = base64.b64encode(hashlib.sha256(password.encode()).hexdigest().encode()).decode()
        return hashlib.sha256((username + inner + token).encode()).hexdigest()
    return base64.b64encode(password.encode()).decode()


def _is_login_page(html):
    return "login.cgi" in html or "txt_Username" in html or "GetRandCount" in html


class HuaweiONT:
    def __init__(self, host=DEFAULT_HOST, username="", password="", password_mode="auto",
                 scheme="http", timeout=8):
        self.base = f"{scheme}://{host}"
        self.host = host
        self.username = username
        self.password = password
        self.password_mode = password_mode
        self.timeout = timeout
        self.cookie = PRE_LOGIN_COOKIE
        self.logged_in = False
        # The ONT is on the LAN; never route it through a proxy.
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    # -- HTTP -----------------------------------------------------------------

    def _request(self, path, data=None):
        if UNSAFE_PATH_RE.search(path) and path != "/login.cgi":
            raise RouterError(f"refusing to fetch {path}")
        body = urllib.parse.urlencode(data).encode() if data is not None else None
        req = urllib.request.Request(self.base + path, data=body, headers={
            "Cookie": self.cookie,
            "User-Agent": USER_AGENT,
            "Referer": self.base + "/",
            **({"Content-Type": "application/x-www-form-urlencoded"} if body else {}),
        })
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                raw = resp.read()
                set_cookie = resp.headers.get_all("Set-Cookie") or []
        except urllib.error.HTTPError as e:
            raise RouterError(f"{path}: HTTP {e.code}") from e
        except (urllib.error.URLError, OSError) as e:
            raise RouterError(f"can't reach the router at {self.host} ({e})") from e
        for c in set_cookie:
            first = c.split(";", 1)[0].strip()
            if first.startswith("Cookie="):
                self.cookie = first
        return raw.decode("utf-8", "replace").lstrip("﻿")

    # -- session --------------------------------------------------------------

    def login(self):
        # One attempt only: the router locks logins after a few failures.
        self.cookie = PRE_LOGIN_COOKIE
        self.logged_in = False
        login_page = self._request("/")
        mode = self.password_mode
        if mode == "auto":
            # Firmware that hashes the password ships a SHA-256 routine in login.asp.
            mode = "sha256" if re.search(r"sha256", login_page, re.I) else "base64"
        token = self._request("/asp/GetRandCount.asp", data={}).strip()
        html = self._request("/login.cgi", data={
            "UserName": self.username,
            "PassWord": encode_password(self.password, mode, self.username, token),
            "Language": "english",
            "x.X_HW_Token": token,
        })
        if "sid=" not in self.cookie:
            raise LoginError(_login_failure_reason(html) or "the router rejected the username or password")
        self.logged_in = True
        self.password_mode = mode

    def fetch(self, path):
        """GET a page, logging in again once if the session has expired."""
        if not self.logged_in:
            self.login()
        html = self._request(path)
        if _is_login_page(html):
            self.login()
            html = self._request(path)
            if _is_login_page(html):
                raise RouterError("session keeps expiring; is someone else logged in to the router?")
        return html

    # -- data -----------------------------------------------------------------

    def read_counters(self, sources):
        """Sum byte counters described by the config's "counters" list.

        Returns (down_bytes, up_bytes). Raises RouterError if a source
        matches nothing, so a wrong config is loud rather than silently zero.
        """
        down = up = 0
        pages = {}
        for src in sources:
            page = src["page"]
            if page not in pages:
                pages[page] = parse.find_constructs(self.fetch(page))
            matched = False
            for cls, args in pages[page]:
                if cls != src["class"]:
                    continue
                where = src.get("where")
                if where and (len(args) <= where[0] or where[1] not in args[where[0]]):
                    continue
                d = parse.as_int(args[src["down_arg"]]) if len(args) > src["down_arg"] else None
                u = parse.as_int(args[src["up_arg"]]) if len(args) > src["up_arg"] else None
                if d is None or u is None:
                    continue
                down += d
                up += u
                matched = True
            if not matched:
                raise RouterError(f"no {src['class']} counters found on {page}; re-run probe")
        return down, up

    def list_devices(self):
        for page in DEVICE_PAGES:
            try:
                html = self.fetch(page)
            except RouterError:
                continue
            devices = devices_from_constructs(parse.find_constructs(html))
            if devices:
                return devices
        return []


def devices_from_constructs(constructs):
    """Guess device fields by shape, so differing firmware field orders still work."""
    out, seen = [], set()
    for cls, args in constructs:
        mac = next((a for a in args if parse.looks_like_mac(a)), None)
        if not mac or mac.lower() in seen:
            continue
        seen.add(mac.lower())
        ip = next((a for a in args if parse.looks_like_ipv4(a)), "")
        status = next((a for a in args if a.lower() in ("online", "offline")), "")
        conn = next((a for a in args if re.fullmatch(r"(?i)(wifi|wlan|lan|eth)\d*|ssid\d+", a.strip())), "")
        name = next((a for a in args if _plausible_name(a)), "")
        out.append({
            "name": name or "Unknown device",
            "ip": ip,
            "mac": mac.upper().replace("-", ":"),
            "online": status.lower() != "offline",
            "connection": "Wi-Fi" if re.match(r"(?i)wifi|wlan|ssid", conn) else ("LAN" if conn else ""),
        })
    out.sort(key=lambda d: (not d["online"], d["name"].lower()))
    return out


def _plausible_name(a):
    a = a.strip()
    if not a or len(a) > 64 or parse.looks_like_mac(a) or parse.looks_like_ipv4(a):
        return False
    if re.search(r"[()\[\]{}]", a):  # unparsed JS, not a name
        return False
    if re.fullmatch(r"[\d.:\-/ ]+", a) or a.lower() in ("online", "offline", "--", "null"):
        return False
    if re.fullmatch(r"(?i)(wifi|wlan|lan|eth)\d*|ssid\d+|dhcp|static|ipv4|ipv6", a):
        return False
    return not a.startswith("InternetGatewayDevice.")


def _login_failure_reason(html):
    m = re.search(r"var\s+LockLeftTime\s*=\s*'?(\d+)", html)
    if m and int(m.group(1)) > 0:
        return f"the router locked logins after too many attempts; wait {m.group(1)} seconds"
    m = re.search(r"var\s+FailStat\s*=\s*'?(\d+)", html)
    if m and m.group(1) != "0":
        return "the router rejected the username or password"
    return None
