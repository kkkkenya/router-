"""Collect the router's login code without logging in.

When the router accepts a password in the browser but rejects it from this
app, the firmware wants the password encoded differently. This saves the
relevant parts of the login page and its scripts to a text file, so the
login code can be matched to it. It makes no login attempt, so it can't
trigger the router's lockout, and the login page holds no passwords.
"""

import re
import urllib.parse

from .huawei_ont import HuaweiONT, RouterError

KEYWORDS = re.compile(r"PassWord|Password|GetRand|Token|sha256|pbkdf|base64|login\.cgi|CfgMode|encrypt|salt", re.I)
MARKERS = ["GetRandCount", "GetRandInfo", "sha256", "SHA256", "pbkdf2", "PBKDF2", "base64encode",
           "x.X_HW_Token", "login.cgi", "loginLDAP", "CfgMode", "salt"]


def _excerpts(text, context=3, limit=400):
    lines = text.splitlines()
    keep = set()
    for i, line in enumerate(lines):
        if KEYWORDS.search(line):
            keep.update(range(max(0, i - context), min(len(lines), i + context + 1)))
    out, prev = [], -2
    for i in sorted(keep)[:limit]:
        if i != prev + 1:
            out.append("   ...")
        out.append(f"{i + 1:5}: {lines[i][:300]}")
        prev = i
    return out


def run_diagnose(host, path_out, log=print):
    router = HuaweiONT(host)
    report = [f"Router: {host}", ""]
    pages = {}
    for p in ("/", "/login.asp"):
        try:
            pages[p] = router._request(p)
        except RouterError as e:
            report.append(str(e))
    if not pages:
        raise RouterError(f"can't reach the router at {host}")

    scripts = []
    for html in list(pages.values()):
        for src in re.findall(r"""<script[^>]+src\s*=\s*["']([^"']+)["']""", html, re.I):
            path = urllib.parse.urljoin("/", src.split("?")[0])
            if path.startswith("/") and path not in scripts and path not in pages:
                scripts.append(path)
    for p in scripts[:15]:
        try:
            pages[p] = router._request(p)
        except RouterError as e:
            report.append(str(e))

    found = sorted({m for text in pages.values() for m in MARKERS if m in text})
    report.append("Markers found: " + (", ".join(found) or "none"))
    for p, text in pages.items():
        report += ["", f"===== {p} ({len(text)} chars) ====="] + _excerpts(text)

    with open(path_out, "w", encoding="utf-8") as f:
        f.write("\n".join(report) + "\n")
    log(f"Read {len(pages)} files from the router (no login attempted).")
    log("Markers found: " + (", ".join(found) or "none"))
    return found
