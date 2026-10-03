"""Pull data out of Huawei ONT web pages.

Huawei's web UI doesn't serve JSON. Each .asp page embeds its data as
JavaScript constructor calls, for example:

    new USERDevice("Phone","192\\x2e168\\x2e100\\x2e5","aa:bb:cc:dd:ee:ff","Online",...)

This module finds every `new Name(...)` call and returns its arguments as
plain Python strings, with JS escapes such as \\x2e already decoded.
"""

import re

_NEW_RE = re.compile(r"\bnew\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")
_ESCAPE_RE = re.compile(r"\\(x[0-9a-fA-F]{2}|u[0-9a-fA-F]{4}|.)", re.S)
_SIMPLE_ESCAPES = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}

# Constructors that are JavaScript built-ins, not router data.
_IGNORED = {"Array", "Object", "Date", "RegExp", "Image", "Option", "Error", "XMLHttpRequest"}


def js_unescape(s):
    def repl(m):
        e = m.group(1)
        if e[0] in "xu" and len(e) > 1:
            return chr(int(e[1:], 16))
        return _SIMPLE_ESCAPES.get(e, e)

    return _ESCAPE_RE.sub(repl, s)


def _parse_args(text, i):
    """Parse a comma-separated argument list starting just after '('.

    Returns (args, index_after_closing_paren). Nested calls and arrays are
    kept as raw text. Never raises; stops at end of text.
    """
    args, cur, depth, n = [], [], 0, len(text)
    is_str = False  # current arg is a single string literal
    while i < n:
        c = text[i]
        if c in "\"'":
            q, j, buf = c, i + 1, []
            while j < n and text[j] != q:
                if text[j] == "\\" and j + 1 < n:
                    buf.append(text[j:j + 2])
                    j += 2
                    continue
                buf.append(text[j])
                j += 1
            lit = "".join(buf)
            if depth == 0 and not "".join(cur).strip():
                cur, is_str = [js_unescape(lit)], True
            else:
                cur.append(q + lit + q)
                is_str = False
            i = j + 1
            continue
        if c in "([{":
            depth += 1
        elif c in ")]}":
            if depth == 0:
                if cur or args:
                    args.append(cur[0] if is_str else "".join(cur).strip())
                return args, i + 1
            depth -= 1
        elif c == "," and depth == 0:
            args.append(cur[0] if is_str else "".join(cur).strip())
            cur, is_str = [], False
            i += 1
            continue
        if is_str and not c.isspace():
            # Something like "a" + "b": keep it raw.
            cur, is_str = ['"' + cur[0] + '"'], False
        cur.append(c)
        i += 1
    if cur:  # text ended mid-call; keep what we have
        args.append(cur[0] if is_str else "".join(cur).strip())
    return args, n


def find_constructs(text):
    """Return a list of (class_name, [args]) for every `new X(...)` in text."""
    out = []
    for m in _NEW_RE.finditer(text):
        name = m.group(1)
        if name in _IGNORED:
            continue
        args, _ = _parse_args(text, m.end())
        out.append((name, args))
    return out


def as_int(value):
    """Parse a counter value; returns None if it isn't a plain integer."""
    if value is None:
        return None
    v = str(value).strip()
    if re.fullmatch(r"\d{1,20}", v):
        return int(v)
    return None


_MAC_RE = re.compile(r"^[0-9a-fA-F]{2}([:-][0-9a-fA-F]{2}){5}$")
_IPV4_RE = re.compile(r"^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$")


def looks_like_mac(s):
    return bool(_MAC_RE.match(str(s).strip()))


def looks_like_ipv4(s):
    m = _IPV4_RE.match(str(s).strip())
    return bool(m) and all(int(g) <= 255 for g in m.groups())
