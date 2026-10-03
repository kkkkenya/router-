# Router dashboard

A bandwidth dashboard for the Huawei fibre router that Safaricom Home Fibre installs
(EG8145V5, HG8145V5, HG8245H and similar, usually at `192.168.100.1`).

It's built around the **1.5 TB monthly fair-usage cap**:

- **Cap tracker**: how much of the 1.5 TB you've used this cycle, where you'd be at an
  even pace, and a projection for the end of the cycle ("on course to go over")
- **Safe daily budget**: how many GB a day you can use and still finish under the cap
- **Live speed**: download/upload in real time
- **Daily usage**: data used per day, against the even-pace line
- **When data gets used**: an hour-by-hour heatmap that shows when the heavy use happens
- **Devices**: everything connected, with IP, MAC, Wi-Fi/LAN and online status
- **Calibrate**: type in the figure Safaricom shows you, and tracking counts on from there

Everything runs on your own computer. Your router password never leaves your network.

## Requirements

Python 3.8 or newer. No extra packages.
(Windows: install from python.org and tick "Add Python to PATH".)

## Try it without a router

```
python -m routerdash --demo
```

Opens the dashboard with a simulated router and six weeks of made-up history.

## Set it up on your router

Run these from this folder, on a computer connected to your home Wi-Fi.

**1. Find your traffic counters (one time).** Huawei firmware versions keep their byte
counters in different places, so the app works out where yours are:

```
python -m routerdash probe
```

Log in with your router's admin username and password (on the sticker under the box).
When asked, start a YouTube video in 1080p on any device. The probe reads the router's
status pages twice, 20 seconds apart, and finds the numbers that went up. Say yes to
save what it found.

If it finds nothing, or the speeds look wrong afterwards, paste the probe's output into
a GitHub issue or to Claude. It contains only page names and numbers, not your Wi-Fi
name, password or device names.

**2. Start the dashboard:**

```
python -m routerdash
```

On Windows you can double-click `start.bat` instead. It opens http://localhost:8765 in
your browser. Log in, then check that the live speed roughly matches a speed test at
fast.com.

**3. Match Safaricom's number.** Under Settings, enter the usage so far shown in the My
Safaricom app, and the day your bundle renews.

## Keep it running

The app counts data by reading the router's counters. If it's closed, it catches up
the next time it starts, **unless the router restarted in between**, because a restart
resets the counters. For the most accurate numbers:

- Leave it running on a computer that stays on, such as an old laptop or a Raspberry Pi.
- Tick **Remember me** when logging in, so it logs back in on its own after a restart.
  This saves the password in `config.json` in plain text, so keep that file private.
- `python -m routerdash --lan` lets phones on your Wi-Fi open the dashboard at
  `http://<that computer's IP>:8765`. Anyone on your Wi-Fi can then see it.

Numbers are in decimal units (1 TB = 1000 GB), and won't match Safaricom's meter to the
byte. Re-calibrate now and then.

## What uses up 1.5 TB

Usually a few things add up: 4K streaming (Netflix and YouTube 4K use about 7 GB an
hour each), console and PC game updates (often 50–150 GB each), cloud photo and video
backups, and phones re-downloading apps. The heatmap shows *when* the big use happens,
which usually tells you *what* it is. Setting streaming apps to 1080p roughly halves
what they use.

## Limits

- This router doesn't report data use per device, so the dashboard can't show which
  device used what. The heatmap plus the device list is the best substitute.
- Speed limits and blocking devices aren't built in yet. Those change router settings,
  and the code needs checking against your exact firmware first.
- If the probe could only find LAN/Wi-Fi port counters (not the internet/WAN one), traffic
  between your own devices, like casting to a TV from a phone, gets counted as well.
- Logging in here may sign you out of the router's own web page. Huawei allows one
  admin session at a time.

## Development

```
python -m unittest
```

The tests include a fake Huawei router that imitates the login handshake.

| File | What it does |
|---|---|
| `routerdash/huawei_ont.py` | Logs in to the router and reads its pages |
| `routerdash/parse.py` | Pulls data out of the JavaScript in Huawei's pages |
| `routerdash/probe.py` | Finds which numbers are traffic counters |
| `routerdash/store.py` | Hourly usage history (SQLite), billing-cycle maths |
| `routerdash/tracker.py` | Background polling |
| `routerdash/server.py` | Local web server and JSON API |
| `web/` | The dashboard (plain HTML/CSS/JS, no internet needed) |
