"""Find which numbers on the router's status pages are traffic counters.

Huawei firmware differs between versions, so instead of hard-coding where the
byte counters live, this reads every status page twice and reports the
numbers that went up in between. With a video playing during the probe,
the counters that grow fastest are downloads.

The printed report contains only page paths, class names and numbers (no
Wi-Fi names, passwords or device names), so it is safe to share.
"""

import re
import time

from . import parse
from .huawei_ont import PROBE_PAGES, UNSAFE_PATH_RE, RouterError

_DISCOVER_RE = re.compile(r"""["'(/]((?:/)?html/[\w/.-]+?\.asp)""")
_INTERESTING_RE = re.compile(r"info|stat|wan|eth|wlan|lan|user|dev|traffic|flow", re.I)


def discover_pages(router):
    pages = list(PROBE_PAGES)
    for start in ("/index.asp", "/html/ssmp/menu/menu.asp"):
        try:
            html = router.fetch(start)
        except RouterError:
            continue
        for m in _DISCOVER_RE.finditer(html):
            p = "/" + m.group(1).lstrip("/")
            if p not in pages and _INTERESTING_RE.search(p) and not UNSAFE_PATH_RE.search(p):
                pages.append(p)
    return pages[:45]


def snapshot(router, pages):
    out = {}
    for p in pages:
        try:
            out[p] = parse.find_constructs(router.fetch(p))
        except RouterError:
            pass
    return out


def growing_counters(before, after, seconds):
    """Return numeric arguments that increased between two snapshots."""
    rows = []
    for page, cons_b in before.items():
        cons_a = after.get(page, [])
        seen = {}
        for i, (cls, args_b) in enumerate(cons_b):
            occ = seen[cls] = seen.get(cls, -1) + 1
            if i >= len(cons_a) or cons_a[i][0] != cls:
                continue
            args_a = cons_a[i][1]
            for j, (vb, va) in enumerate(zip(args_b, args_a)):
                b, a = parse.as_int(vb), parse.as_int(va)
                if b is None or a is None or a <= b or a < 10_000:
                    continue
                label_arg = next((k for k, x in enumerate(args_b)
                                  if x and parse.as_int(x) is None and len(x) < 40), None)
                rows.append({"page": page, "class": cls, "occurrence": occ, "arg": j,
                             "label_arg": label_arg,
                             "label": args_b[label_arg] if label_arg is not None else "",
                             "value": a, "delta": a - b,
                             "rate_kbps": round((a - b) * 8 / seconds / 1000, 1)})
    rows.sort(key=lambda r: -r["delta"])
    return rows


def suggest_counters(rows):
    """Turn probe results into a "counters" config, or [] if nothing fits.

    Prefers a WAN counter (true internet usage). Falls back to summing the
    LAN/Wi-Fi port counters, which also include traffic between your own
    devices but is close enough for most homes.
    """
    groups = {}
    for r in rows:
        groups.setdefault((r["page"], r["class"], r["occurrence"]), []).append(r)
    pairs = []
    for (page, cls, occ), rs in groups.items():
        if len(rs) < 2:
            continue
        rs = sorted(rs, key=lambda r: -r["delta"])
        pairs.append({"page": page, "class": cls, "occurrence": occ, "label": rs[0]["label"],
                      "down": rs[0], "up": rs[1], "total": rs[0]["delta"] + rs[1]["delta"]})
    if not pairs:
        return []

    wan = [p for p in pairs if re.search(r"wan|ppp|internet", p["page"] + p["class"] + p["label"], re.I)]
    if wan:
        best = max(wan, key=lambda p: p["total"])
        src = {"page": best["page"], "class": best["class"],
               "down_arg": best["down"]["arg"], "up_arg": best["up"]["arg"]}
        # ONTs usually have several WAN connections (internet, TR-069, voice);
        # pin the busiest one by its name.
        if best["down"]["label_arg"] is not None:
            src["where"] = [best["down"]["label_arg"], best["label"]]
        return [src]

    # LAN side: one source per (page, class), summed over every port.
    out, done = [], set()
    for p in sorted(pairs, key=lambda p: -p["total"]):
        key = (p["page"], p["class"])
        if key in done or not re.search(r"eth|wlan|lan", p["page"], re.I):
            continue
        done.add(key)
        out.append({"page": p["page"], "class": p["class"],
                    "down_arg": p["down"]["arg"], "up_arg": p["up"]["arg"]})
    return out


def run_probe(router, wait=20, log=print):
    log("Finding status pages...")
    pages = discover_pages(router)
    log(f"Reading {len(pages)} pages, then again in {wait}s. Keep a video playing meanwhile.")
    t0 = time.time()
    before = snapshot(router, pages)
    time.sleep(wait)
    after = snapshot(router, pages)
    rows = growing_counters(before, after, time.time() - t0)
    return pages, before, rows, suggest_counters(rows)
