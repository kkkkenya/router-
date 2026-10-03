import json
import os

DEFAULTS = {
    "router_host": "192.168.100.1",
    "username": "",
    # Only stored if you tick "Remember" when logging in. Plain text, so
    # keep config.json private.
    "password": "",
    "password_mode": "auto",
    # Safaricom Home Fibre fair-usage policy: 1.5 TB per month.
    "cap_gb": 1500,
    # Day of the month your Safaricom bundle renews.
    "reset_day": 1,
    "poll_seconds": 5,
    # Where the byte counters live on your firmware. Filled in by `probe`.
    "counters": [],
    "listen_host": "127.0.0.1",
    "listen_port": 8765,
}


def load(path):
    cfg = dict(DEFAULTS)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            cfg.update(json.load(f))
    return cfg


def save(path, cfg):
    keep = {k: cfg[k] for k in DEFAULTS if k in cfg}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(keep, f, indent=2)
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
