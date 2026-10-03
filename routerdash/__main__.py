"""Command line entry point.

    python -m routerdash            start the dashboard (opens your browser)
    python -m routerdash --demo     try it with a simulated router
    python -m routerdash probe      find your router's traffic counters
"""

import argparse
import getpass
import json
import os
import re
import sys
import threading
import webbrowser

from . import config as config_mod
from .huawei_ont import HuaweiONT, RouterError
from .store import Store
from .tracker import Tracker

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SAFE_LABEL_RE = re.compile(r"(?i)wan|internet|tr069|voip|ppp|vid|^(lan|eth|ssid|wlan)\d*$")


def cmd_serve(args):
    from .server import App, serve

    cfg = config_mod.load(args.config)
    if args.port:
        cfg["listen_port"] = args.port
    if args.lan:
        cfg["listen_host"] = "0.0.0.0"
    db_path = os.path.join(ROOT, "demo.sqlite3" if args.demo else "usage.sqlite3")
    store = Store(db_path)

    # Counter positions changed since the last run? Then the last stored
    # reading can't be compared with the next one.
    signature = json.dumps([cfg["router_host"], cfg.get("counters")], sort_keys=True)
    if args.demo or store.get("counter_signature") != signature:
        store.put("last_reading", None)
        store.put("counter_signature", signature)

    if args.demo:
        from .demo import DemoRouter, seed_history
        cfg["poll_seconds"] = 2
        seed_history(store, cfg["reset_day"])

    tracker = Tracker(store, cfg)
    app = App(cfg, args.config, store, tracker, demo=args.demo)
    if args.demo:
        tracker.attach(DemoRouter())
    elif cfg.get("password"):
        try:
            app.login({"host": cfg["router_host"], "username": cfg["username"],
                       "password": cfg["password"], "remember": True})
            print(f"Logged in to {cfg['router_host']} with saved credentials.")
        except RouterError as e:
            print(f"Saved login didn't work ({e}); log in from the dashboard.")

    httpd = serve(app)
    url = f"http://localhost:{cfg['listen_port']}/"
    print(f"Router dashboard running at {url}")
    if cfg["listen_host"] != "127.0.0.1":
        print("Warning: reachable from other devices on your network. Anyone on your Wi-Fi can open it.")
    if not cfg.get("counters") and not args.demo:
        print("Usage tracking is off until you run:  python -m routerdash probe")
    print("Press Ctrl+C to stop.")
    if not args.no_browser:
        threading.Timer(0.8, webbrowser.open, [url]).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        tracker.stop()


def cmd_probe(args):
    from .probe import run_probe

    cfg = config_mod.load(args.config)
    host = input(f"Router address [{cfg['router_host']}]: ").strip() or cfg["router_host"]
    user = input(f"Router username [{cfg['username']}]: ").strip() or cfg["username"]
    pw = getpass.getpass("Router password (not shown): ")
    router = HuaweiONT(host, user, pw, cfg.get("password_mode", "auto"))
    try:
        router.login()
    except RouterError as e:
        sys.exit(f"Login failed: {e}")
    print(f"Logged in ({router.password_mode} password mode).\n")
    print("Start a YouTube video in 1080p or higher on any device now, so")
    print("the probe can tell downloads from uploads.\n")
    try:
        input("Press Enter when it's playing...")
    except EOFError:
        pass

    pages, snap, rows, suggestion = run_probe(router, wait=args.wait)

    print(f"\nPages read: {len(snap)} of {len(pages)} tried")
    for p, cons in snap.items():
        classes = sorted({c for c, _ in cons})
        print(f"  {p}: {', '.join(classes) or '(no data objects)'}")
    print(f"\nGrowing numbers ({len(rows)}), fastest first:")
    print(f"  {'page':44} {'class':22} {'#':>2} {'arg':>3} {'label':20} {'kbit/s':>9}")
    for r in rows[:40]:
        label = r["label"] if _SAFE_LABEL_RE.search(r["label"]) else ("(hidden)" if r["label"] else "")
        print(f"  {r['page'][-44:]:44} {r['class'][:22]:22} {r['occurrence']:>2} {r['arg']:>3} "
              f"{label[:20]:20} {r['rate_kbps']:>9}")

    if not suggestion:
        print("\nNo counter pairs found. Paste this whole output to Claude (it's safe to share)")
        print("and the counters can be wired up by hand.")
        return
    print("\nSuggested counter config:")
    print(json.dumps(suggestion, indent=2))
    ans = input(f"\nSave this to {os.path.basename(args.config)}? [Y/n] ").strip().lower()
    if ans in ("", "y", "yes"):
        cfg.update(router_host=host, username=user, password_mode=router.password_mode, counters=suggestion)
        config_mod.save(args.config, cfg)
        print("Saved. Start the dashboard with:  python -m routerdash")
        print("Check its live speed against a speed test (fast.com); if download and")
        print("upload look swapped or 10x off, paste this output to Claude.")


def main():
    ap = argparse.ArgumentParser(prog="routerdash", description="Bandwidth dashboard for Huawei fibre routers")
    ap.add_argument("--config", default=os.path.join(ROOT, "config.json"))
    sub = ap.add_subparsers(dest="cmd")
    ap.add_argument("--demo", action="store_true", help="use a simulated router")
    ap.add_argument("--port", type=int)
    ap.add_argument("--lan", action="store_true", help="let phones on your Wi-Fi open the dashboard")
    ap.add_argument("--no-browser", action="store_true")
    pr = sub.add_parser("probe", help="find the traffic counters on your router")
    pr.add_argument("--wait", type=int, default=20)
    args = ap.parse_args()
    if args.cmd == "probe":
        cmd_probe(args)
    else:
        cmd_serve(args)


if __name__ == "__main__":
    main()
