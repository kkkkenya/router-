import base64
import os
import tempfile
import threading
import unittest
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

from routerdash import parse
from routerdash.huawei_ont import HuaweiONT, LoginError, RouterError, devices_from_constructs
from routerdash.probe import growing_counters, suggest_counters
from routerdash.store import WRAP_32, Store, counter_delta, cycle_bounds

GB = 1000 ** 3


class ParseTests(unittest.TestCase):
    def test_constructs_and_escapes(self):
        html = r'''var a = new Array(new USERDevice("Phone","192\x2e168\x2e100\x2e5","aa:bb:cc:dd:ee:ff","Online","WIFI"),null);
                   new Stats('x\'y', 123, "45", f(1, 2), [1,2]);'''
        cons = parse.find_constructs(html)
        self.assertEqual(cons[0], ("USERDevice", ["Phone", "192.168.100.5", "aa:bb:cc:dd:ee:ff", "Online", "WIFI"]))
        self.assertEqual(cons[1], ("Stats", ["x'y", "123", "45", "f(1, 2)", "[1,2]"]))

    def test_empty_and_unterminated(self):
        self.assertEqual(parse.find_constructs("new X()"), [("X", [])])
        self.assertEqual(parse.find_constructs('new X("a", 1'), [("X", ["a", "1"])])

    def test_devices_by_shape(self):
        cons = [("Dev", ["", "10.0.0.2", "11-22-33-44-55-66", "Offline", "LAN1", "f(1)"]),
                ("Dev", ["Laptop", "WIFI", "Online", "AA:BB:CC:DD:EE:01", "10.0.0.3"]),
                ("Dev", ["dup", "aa:bb:cc:dd:ee:01"])]
        devs = devices_from_constructs(cons)
        self.assertEqual([d["name"] for d in devs], ["Laptop", "Unknown device"])
        self.assertEqual(devs[1]["mac"], "11:22:33:44:55:66")
        self.assertEqual(devs[1]["connection"], "LAN")
        self.assertFalse(devs[1]["online"])


class CounterTests(unittest.TestCase):
    def test_normal_increase(self):
        self.assertEqual(counter_delta(1000, 5000, 5), 4000)

    def test_32bit_wrap(self):
        self.assertEqual(counter_delta(WRAP_32 - 100, 400, 5), 500)

    def test_reboot_counts_since_boot(self):
        self.assertEqual(counter_delta(50 * GB, 2_000_000, 5), 2_000_000)

    def test_implausible_jump_rejected(self):
        self.assertIsNone(counter_delta(0, 10 * GB, 5))

    def test_cycle_bounds(self):
        s, e = cycle_bounds(datetime(2026, 10, 3, 12), 15)
        self.assertEqual((s, e), (datetime(2026, 9, 15), datetime(2026, 10, 15)))
        s, e = cycle_bounds(datetime(2026, 2, 28, 12), 31)
        self.assertEqual(s, datetime(2026, 2, 28))  # clamps to the last day of February
        self.assertEqual(e, datetime(2026, 3, 31))
        s, e = cycle_bounds(datetime(2026, 1, 2), 5)
        self.assertEqual((s, e), (datetime(2025, 12, 5), datetime(2026, 1, 5)))


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = Store(os.path.join(self.dir.name, "t.sqlite3"))

    def tearDown(self):
        self.dir.cleanup()

    def test_ingest_and_summary(self):
        now = datetime(2026, 10, 11, 12).timestamp()
        self.assertIsNone(self.store.ingest(now - 10, 1_000, 100))
        self.assertEqual(self.store.ingest(now, 1_000 + 50_000_000, 100 + 5_000_000), (50_000_000, 5_000_000, 10))
        s = self.store.summary(datetime(2026, 10, 11, 13), 1500 * GB, 1)
        self.assertEqual(s["used_bytes"], 55_000_000)
        self.assertEqual(s["today_bytes"], 55_000_000)
        self.assertEqual(len(s["days"]), 31)
        self.assertEqual(len(s["heatmap"]), 14)
        self.assertEqual(s["heatmap"][-1]["hours"][12], 55_000_000)

    def test_calibration(self):
        start, _ = cycle_bounds(datetime(2026, 10, 11), 1)
        self.store.add(datetime(2026, 10, 2).timestamp(), 10 * GB, 0)
        self.store.set_adjustment(int(start.timestamp()), 600 * GB - 10 * GB)
        s = self.store.summary(datetime(2026, 10, 11), 1500 * GB, 1)
        self.assertEqual(s["used_bytes"], 600 * GB)


class ProbeTests(unittest.TestCase):
    def test_finds_wan_counter_pair(self):
        before = {"/wan.asp": [("WanInfo", ["TR069", "500000", "400000"]),
                               ("WanInfo", ["INTERNET_R_VID_10", "9000000", "1000000"])]}
        after = {"/wan.asp": [("WanInfo", ["TR069", "500000", "400000"]),
                              ("WanInfo", ["INTERNET_R_VID_10", "29000000", "1600000"])]}
        rows = growing_counters(before, after, 10)
        self.assertEqual([(r["occurrence"], r["arg"]) for r in rows], [(1, 1), (1, 2)])
        self.assertEqual(suggest_counters(rows), [
            {"page": "/wan.asp", "class": "WanInfo", "down_arg": 1, "up_arg": 2, "where": [0, "INTERNET_R_VID_10"]}])


class FakeONT(BaseHTTPRequestHandler):
    """Mimics the Huawei login handshake and a couple of status pages."""
    PASSWORD = "s3cret"
    counters = [10_000_000, 2_000_000]

    def log_message(self, *a):
        pass

    def _reply(self, body, cookie=None):
        self.send_response(200)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body.encode())

    def _authed(self):
        return "sid=" in self.headers.get("Cookie", "")

    def do_GET(self):
        if self.path == "/":
            return self._reply('<form action="login.cgi"><input id="txt_Username"></form>')
        if not self._authed():
            return self._reply('<script>location="/login.asp"; /* login.cgi */</script>')
        if self.path == "/wan.asp":
            FakeONT.counters = [self.counters[0] + 5_000_000, self.counters[1] + 500_000]
            return self._reply(f'new WanStat("INTERNET_R_VID_10","{self.counters[0]}","{self.counters[1]}");')
        if self.path == "/html/bbsp/common/GetLanUserDevInfo.asp":
            return self._reply('var d=new Array(new USERDevice("TV","192\\x2e168\\x2e100\\x2e9","00:11:22:33:44:55","Online","LAN1"),null);')
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        body = parse_qs(self.rfile.read(int(self.headers.get("Content-Length", 0))).decode())
        if self.path == "/asp/GetRandCount.asp":
            return self._reply("﻿tok123")
        if self.path == "/login.cgi":
            ok = (body.get("PassWord", [""])[0] == base64.b64encode(self.PASSWORD.encode()).decode()
                  and body.get("x.X_HW_Token", [""])[0] == "tok123"
                  and "body:Language" in self.headers.get("Cookie", ""))
            if ok:
                return self._reply("<script>location='/index.asp'</script>", "Cookie=sid=abc:Language:english:id=1;path=/")
            return self._reply("var FailStat = '1';")
        self.send_response(404)
        self.end_headers()


class RouterClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), FakeONT)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.host = f"127.0.0.1:{cls.httpd.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()

    def test_login_counters_devices(self):
        r = HuaweiONT(self.host, "user", "s3cret")
        r.login()
        self.assertEqual(r.password_mode, "base64")
        src = [{"page": "/wan.asp", "class": "WanStat", "down_arg": 1, "up_arg": 2, "where": [0, "INTERNET"]}]
        d1, u1 = r.read_counters(src)
        d2, u2 = r.read_counters(src)
        self.assertEqual((d2 - d1, u2 - u1), (5_000_000, 500_000))
        devs = r.list_devices()
        self.assertEqual(devs[0]["ip"], "192.168.100.9")
        self.assertEqual(devs[0]["name"], "TV")

    def test_wrong_password(self):
        with self.assertRaises(LoginError):
            HuaweiONT(self.host, "user", "nope").login()

    def test_missing_counter_is_loud(self):
        r = HuaweiONT(self.host, "user", "s3cret")
        with self.assertRaises(RouterError):
            r.read_counters([{"page": "/wan.asp", "class": "Nope", "down_arg": 1, "up_arg": 2}])

    def test_refuses_unsafe_paths(self):
        r = HuaweiONT(self.host, "user", "s3cret")
        with self.assertRaises(RouterError):
            r.fetch("/html/ssmp/reset/reboot.asp")


if __name__ == "__main__":
    unittest.main()
