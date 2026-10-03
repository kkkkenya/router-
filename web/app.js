"use strict";

// ---------- helpers ----------

const $ = (id) => document.getElementById(id);
const SVG_NS = "http://www.w3.org/2000/svg";
const LIVE_SPAN_SECS = 300;

function svgEl(tag, attrs = {}, parent) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  if (parent) parent.appendChild(el);
  return el;
}

function el(tag, text, cls) {
  const e = document.createElement(tag);
  if (text != null) e.textContent = text;
  if (cls) e.className = cls;
  return e;
}

function fmtBytes(b) {
  const GB = 1e9;
  if (b == null || isNaN(b)) return "–";
  if (b < GB) return `${Math.round(b / 1e6)} MB`;
  if (b < 100 * GB) return `${(b / GB).toFixed(1)} GB`;
  if (b < 1000 * GB) return `${Math.round(b / GB)} GB`;
  return `${(b / 1e12).toFixed(2)} TB`;
}

function fmtRate(bps) {
  if (bps == null) return ["–", ""];
  if (bps < 1e6) return [(bps / 1e3).toFixed(0), "kbit/s"];
  return [(bps / 1e6).toFixed(bps < 1e7 ? 1 : 0), "Mbit/s"];
}

function niceMax(v) {
  if (v <= 0) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= v) return m * p;
  return 10 * p;
}

const dateFmt = new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short" });
const dayFmt = new Intl.DateTimeFormat(undefined, { weekday: "short", day: "numeric" });
const timeFmt = new Intl.DateTimeFormat(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
const parseDay = (iso) => { const [y, m, d] = iso.split("-").map(Number); return new Date(y, m - 1, d); };

async function api(path, body) {
  const opts = body === undefined ? {} : {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Router-Dash": "1" },
    body: JSON.stringify(body),
  };
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

const ICONS = {
  good: '<svg class="icon" viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="9" fill="var(--good)"/><path d="M6 10.2l2.6 2.6L14 7.4" stroke="#fff" stroke-width="2" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg>',
  warning: '<svg class="icon" viewBox="0 0 20 20" aria-hidden="true"><path d="M10 2l9 16H1z" fill="var(--warning)"/><path d="M10 8v4.5" stroke="#0b0b0b" stroke-width="2" stroke-linecap="round"/><circle cx="10" cy="15.2" r="1.1" fill="#0b0b0b"/></svg>',
  critical: '<svg class="icon" viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="9" fill="var(--critical)"/><path d="M10 5.5v5.5" stroke="#fff" stroke-width="2" stroke-linecap="round"/><circle cx="10" cy="14.3" r="1.2" fill="#fff"/></svg>',
  info: '<svg class="icon" viewBox="0 0 20 20" aria-hidden="true"><circle cx="10" cy="10" r="9" fill="var(--accent)"/><path d="M10 9v5.5" stroke="#fff" stroke-width="2" stroke-linecap="round"/><circle cx="10" cy="6" r="1.2" fill="#fff"/></svg>',
};

// ---------- tooltip ----------

const tip = $("tooltip");
function showTip(x, y, title, rows) {
  tip.replaceChildren();
  tip.appendChild(el("div", title, "t-title"));
  for (const r of rows) {
    const row = el("div", null, "t-row");
    if (r.color) {
      const k = el("span", null, r.swatch ? "swatch" : "linekey");
      k.style.background = r.color;
      row.appendChild(k);
    }
    row.appendChild(el("strong", r.value));
    row.appendChild(el("span", r.label));
    tip.appendChild(row);
  }
  tip.style.display = "block";
  const w = tip.offsetWidth, h = tip.offsetHeight;
  const left = x + 14 + w > window.innerWidth ? x - w - 14 : x + 14;
  const top = Math.max(8, Math.min(y - h / 2, window.innerHeight - h - 8));
  tip.style.left = `${left}px`;
  tip.style.top = `${top}px`;
}
const hideTip = () => { tip.style.display = "none"; };

// ---------- live line chart ----------

function drawLive(container, points, now) {
  container.replaceChildren();
  const W = container.clientWidth || 600, H = 210;
  const m = { l: 48, r: 112, t: 22, b: 24 };
  const iw = W - m.l - m.r, ih = H - m.t - m.b;
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, height: H, tabindex: 0,
    role: "img", "aria-label": "Download and upload speed over the last five minutes" }, container);

  const pts = points.filter((p) => p.t >= now - LIVE_SPAN_SECS);
  if (pts.length < 2) {
    const t = svgEl("text", { x: W / 2, y: H / 2, "text-anchor": "middle", class: "label-text" }, svg);
    t.textContent = "Collecting readings…";
    return;
  }
  const yMax = niceMax(Math.max(...pts.map((p) => Math.max(p.down_bps, p.up_bps))) * 1.1);
  const unit = yMax >= 2e6 ? 1e6 : 1e3, unitLabel = unit === 1e6 ? "Mbit/s" : "kbit/s";
  const x = (t) => m.l + ((t - (now - LIVE_SPAN_SECS)) / LIVE_SPAN_SECS) * iw;
  const y = (v) => m.t + ih - (v / yMax) * ih;

  for (let i = 0; i <= 4; i++) {
    const v = (yMax / 4) * i, yy = y(v);
    svgEl("line", { x1: m.l, x2: m.l + iw, y1: yy, y2: yy, stroke: i ? "var(--grid)" : "var(--axis)", "stroke-width": 1 }, svg);
    const t = svgEl("text", { x: m.l - 8, y: yy + 4, "text-anchor": "end", class: "axis-text" }, svg);
    t.textContent = +(v / unit).toFixed(1);
  }
  const unitText = svgEl("text", { x: m.l - 8, y: 10, "text-anchor": "end", class: "axis-text" }, svg);
  unitText.textContent = unitLabel;
  for (const s of [0, 60, 120, 180, 240, 300]) {
    const t = svgEl("text", { x: x(now - LIVE_SPAN_SECS + s), y: H - 6, "text-anchor": "middle", class: "axis-text" }, svg);
    t.textContent = s === 300 ? "now" : `-${(300 - s) / 60}m`;
  }

  const path = (key) => pts.map((p, i) => `${i ? "L" : "M"}${x(p.t).toFixed(1)},${y(p[key]).toFixed(1)}`).join("");
  const downPath = path("down_bps");
  svgEl("path", { d: `${downPath}L${x(pts.at(-1).t)},${y(0)}L${x(pts[0].t)},${y(0)}Z`, fill: "var(--wash)" }, svg);
  for (const [key, color] of [["up_bps", "var(--up)"], ["down_bps", "var(--down)"]]) {
    svgEl("path", { d: path(key), fill: "none", stroke: color, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }, svg);
  }

  // End dots and direct labels (nudged apart only if they'd overlap).
  const last = pts.at(-1);
  let yd = y(last.down_bps), yu = y(last.up_bps);
  let ld = yd, lu = yu;
  if (Math.abs(ld - lu) < 14) { if (ld <= lu) { ld -= 7; lu += 7; } else { ld += 7; lu -= 7; } }
  for (const [yy, ly, color, label, v] of [[yd, ld, "var(--down)", "Down", last.down_bps], [yu, lu, "var(--up)", "Up", last.up_bps]]) {
    svgEl("circle", { cx: x(last.t), cy: yy, r: 4, fill: color, stroke: "var(--surface)", "stroke-width": 2 }, svg);
    const t = svgEl("text", { x: x(last.t) + 10, y: ly + 4, class: "label-text" }, svg);
    const [n, u] = fmtRate(v);
    t.textContent = `${label} ${n} ${u}`;
  }

  // Crosshair + tooltip.
  const cross = svgEl("line", { y1: m.t, y2: m.t + ih, stroke: "var(--axis)", "stroke-width": 1, visibility: "hidden" }, svg);
  const hit = svgEl("rect", { x: m.l, y: m.t, width: iw, height: ih, fill: "transparent" }, svg);
  let idx = pts.length - 1;
  const show = (i, cx, cy) => {
    idx = Math.max(0, Math.min(pts.length - 1, i));
    const p = pts[idx];
    cross.setAttribute("x1", x(p.t)); cross.setAttribute("x2", x(p.t));
    cross.setAttribute("visibility", "visible");
    const [dn, du] = fmtRate(p.down_bps), [un, uu] = fmtRate(p.up_bps);
    showTip(cx, cy, timeFmt.format(new Date(p.t * 1000)), [
      { color: "var(--down)", value: `${dn} ${du}`, label: "Download" },
      { color: "var(--up)", value: `${un} ${uu}`, label: "Upload" },
    ]);
  };
  const nearest = (clientX) => {
    const r = svg.getBoundingClientRect();
    const px = ((clientX - r.left) / r.width) * W;
    let best = 0;
    pts.forEach((p, i) => { if (Math.abs(x(p.t) - px) < Math.abs(x(pts[best].t) - px)) best = i; });
    return best;
  };
  hit.addEventListener("pointermove", (e) => show(nearest(e.clientX), e.clientX, e.clientY));
  hit.addEventListener("pointerleave", () => { cross.setAttribute("visibility", "hidden"); hideTip(); });
  svg.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    const r = svg.getBoundingClientRect();
    show(idx + (e.key === "ArrowLeft" ? -1 : 1), r.left + (x(pts[idx].t) / W) * r.width, r.top + r.height / 2);
  });
  svg.addEventListener("blur", () => { cross.setAttribute("visibility", "hidden"); hideTip(); });
}

// ---------- daily stacked columns ----------

function roundedTop(x, y, w, h, r) {
  r = Math.min(r, h, w / 2);
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
}

function drawDaily(container, usage) {
  container.replaceChildren();
  const days = usage.days;
  const W = container.clientWidth || 600, H = 240;
  const m = { l: 48, r: 12, t: 16, b: 26 };
  const iw = W - m.l - m.r, ih = H - m.t - m.b;
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, height: H, role: "img",
    "aria-label": "Data used per day this billing cycle, download and upload" }, container);

  const pace = usage.even_pace_bytes;
  const yMax = niceMax(Math.max(pace * 1.15, ...days.map((d) => d.down + d.up)));
  const y = (v) => m.t + ih - (v / yMax) * ih;
  const band = iw / days.length;
  const bw = Math.max(3, Math.min(24, band - 2));
  const todayIso = new Date().toLocaleDateString("sv-SE");

  for (let i = 0; i <= 4; i++) {
    const v = (yMax / 4) * i, yy = y(v);
    svgEl("line", { x1: m.l, x2: m.l + iw, y1: yy, y2: yy, stroke: i ? "var(--grid)" : "var(--axis)", "stroke-width": 1 }, svg);
    const t = svgEl("text", { x: m.l - 8, y: yy + 4, "text-anchor": "end", class: "axis-text" }, svg);
    t.textContent = i === 0 ? "0" : fmtBytes(v);
  }

  const labelEvery = Math.ceil(days.length / Math.max(1, Math.floor(iw / 38)));
  days.forEach((d, i) => {
    const cx = m.l + band * i + band / 2, bx = cx - bw / 2;
    const g = svgEl("g", { tabindex: 0, role: "img",
      "aria-label": `${dateFmt.format(parseDay(d.date))}: ${fmtBytes(d.down + d.up)}` }, svg);
    const future = d.date > todayIso;
    if (!future && d.down + d.up > 0) {
      const hd = (d.down / yMax) * ih, hu = (d.up / yMax) * ih;
      const gap = hu >= 1 && hd >= 1 ? 2 : 0;
      const yDown = m.t + ih - hd;
      // Download sits on the baseline; upload stacks on top with a 2px surface gap.
      if (hu >= 1) {
        svgEl("path", { d: roundedTop(bx, yDown - gap - hu, bw, hu, 4), fill: "var(--up)" }, g);
        svgEl("rect", { x: bx, y: yDown, width: bw, height: hd, fill: "var(--down)" }, g);
      } else {
        svgEl("path", { d: roundedTop(bx, yDown, bw, hd, 4), fill: "var(--down)" }, g);
      }
    }
    if (d.date === todayIso) {
      const t = svgEl("text", { x: cx, y: H - 6, "text-anchor": "middle", class: "label-strong" }, svg);
      t.textContent = "Today";
    } else if (i % labelEvery === 0 && !(Math.abs(days.findIndex((x) => x.date === todayIso) - i) < labelEvery)) {
      const t = svgEl("text", { x: cx, y: H - 6, "text-anchor": "middle", class: "axis-text" }, svg);
      t.textContent = parseDay(d.date).getDate();
    }
    const hit = svgEl("rect", { x: m.l + band * i, y: m.t, width: band, height: ih, fill: "transparent" }, g);
    const showIt = (cx2, cy2) => showTip(cx2, cy2, dateFmt.format(parseDay(d.date)) + (future ? " (upcoming)" : ""), future ? [] : [
      { value: fmtBytes(d.down + d.up), label: "total" },
      { color: "var(--down)", swatch: true, value: fmtBytes(d.down), label: "Download" },
      { color: "var(--up)", swatch: true, value: fmtBytes(d.up), label: "Upload" },
    ]);
    hit.addEventListener("pointermove", (e) => showIt(e.clientX, e.clientY));
    hit.addEventListener("pointerleave", hideTip);
    g.addEventListener("focus", () => { const r = hit.getBoundingClientRect(); showIt(r.right, r.top + r.height / 2); });
    g.addEventListener("blur", hideTip);
  });

  // Even-pace reference line, labelled once at the right end.
  const py = y(pace);
  svgEl("line", { x1: m.l, x2: m.l + iw, y1: py, y2: py, stroke: "var(--ink-2)", "stroke-width": 1.5, "pointer-events": "none" }, svg);
  const pt = svgEl("text", { x: m.l + iw, y: py - 6, "text-anchor": "end", class: "label-text", "pointer-events": "none" }, svg);
  pt.textContent = `Even pace ${fmtBytes(pace)}/day`;

  // Table view.
  const table = $("daily-table");
  table.replaceChildren();
  const head = table.createTHead().insertRow();
  for (const [t, cls] of [["Date", ""], ["Download", "num"], ["Upload", "num"], ["Total", "num"]]) {
    const th = el("th", t, cls); head.appendChild(th);
  }
  const body = table.createTBody();
  days.filter((d) => d.date <= todayIso).reverse().forEach((d) => {
    const r = body.insertRow();
    r.appendChild(el("td", dateFmt.format(parseDay(d.date))));
    for (const v of [d.down, d.up, d.down + d.up]) r.appendChild(el("td", fmtBytes(v), "num"));
  });
}

// ---------- heatmap ----------

const HEAT_STEPS = 6;

function drawHeat(container, heatmap) {
  container.replaceChildren();
  const W = container.clientWidth || 600;
  const m = { l: 58, r: 4, t: 4, b: 22 };
  const cw = (W - m.l - m.r) / 24, ch = Math.max(12, Math.min(20, cw * 0.8));
  const H = m.t + ch * heatmap.length + m.b;
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, height: H, role: "img",
    "aria-label": "Data used by hour of day over the last 14 days" }, container);
  const all = heatmap.flatMap((r) => r.hours).filter((v) => v > 0).sort((a, b) => a - b);
  // Quantile buckets so one huge update doesn't wash every other hour out.
  const cuts = [];
  for (let i = 1; i < HEAT_STEPS; i++) cuts.push(all[Math.floor((all.length * i) / HEAT_STEPS)] ?? Infinity);
  const step = (v) => (v <= 0 ? 0 : 1 + cuts.filter((c) => v > c).length);

  heatmap.forEach((row, ri) => {
    const yy = m.t + ri * ch;
    const lbl = svgEl("text", { x: m.l - 8, y: yy + ch / 2 + 4, "text-anchor": "end", class: "axis-text" }, svg);
    lbl.textContent = dayFmt.format(parseDay(row.date));
    row.hours.forEach((v, h) => {
      const r = svgEl("rect", { x: m.l + h * cw + 1, y: yy + 1, width: Math.max(1, cw - 2), height: ch - 2, rx: 2,
        fill: `var(--heat-${step(v)})` }, svg);
      r.addEventListener("pointermove", (e) => showTip(e.clientX, e.clientY,
        `${dayFmt.format(parseDay(row.date))}, ${String(h).padStart(2, "0")}:00–${String(h + 1).padStart(2, "0")}:00`,
        [{ value: fmtBytes(v), label: "used" }]));
      r.addEventListener("pointerleave", hideTip);
    });
  });
  for (const h of [0, 6, 12, 18, 23]) {
    const t = svgEl("text", { x: m.l + h * cw + cw / 2, y: H - 6, "text-anchor": "middle", class: "axis-text" }, svg);
    t.textContent = h === 0 ? "midnight" : h === 12 ? "noon" : `${String(h).padStart(2, "0")}:00`;
  }

  const legend = $("heat-legend");
  legend.replaceChildren(el("span", "Less"));
  for (let i = 0; i <= HEAT_STEPS; i++) {
    const c = el("span", null, "cell"); c.style.background = `var(--heat-${i})`; legend.appendChild(c);
  }
  legend.appendChild(el("span", "More"));
}

// ---------- page state ----------

let status = null, usage = null, live = { points: [], now: 0 }, devices = [];

function renderStatus() {
  const dot = $("conn-dot"), txt = $("conn-text");
  if (status.demo) { dot.className = "dot ok"; txt.textContent = "Demo mode: simulated router"; }
  else if (status.error && status.error !== "not_configured") { dot.className = "dot err"; txt.textContent = `${status.router_host}: ${status.error}`; }
  else { dot.className = "dot ok"; txt.textContent = `Connected to ${status.router_host}`; }
  $("logout-btn").hidden = status.demo;
}

function banner(kind, html) {
  const b = el("div", null, `banner ${kind}`);
  b.innerHTML = ICONS[kind === "critical" ? "critical" : kind === "warning" ? "warning" : "info"];
  const span = el("div"); span.innerHTML = html; b.appendChild(span);
  return b;
}

function renderBanners() {
  const box = $("banners");
  box.replaceChildren();
  if (status && !status.counters_configured) {
    box.appendChild(banner("info", "<strong>Usage tracking isn't set up yet.</strong> Stop the dashboard and run <code>python -m routerdash probe</code> once, so it can find where your router keeps its traffic counters. Devices still show below."));
  }
  if (usage) {
    const pct = usage.used_bytes / usage.cap_bytes;
    if (pct >= 1) box.appendChild(banner("critical", "<strong>You've gone past the fair-usage cap.</strong> Safaricom may slow your line until the bundle renews."));
    else if (pct >= 0.85) box.appendChild(banner("warning", `<strong>${Math.round(pct * 100)}% of the cap used.</strong> Pause big downloads and console or PC updates until the bundle renews.`));
  }
}

function renderUsage() {
  if (!usage) return;
  const u = usage, cap = u.cap_bytes, pct = u.used_bytes / cap;
  $("cycle-dates").textContent = `${dateFmt.format(parseDay(u.cycle_start))} – ${dateFmt.format(parseDay(u.cycle_end))}`;
  $("used-hero").textContent = fmtBytes(u.used_bytes);
  $("used-of").textContent = `of ${fmtBytes(cap)} (${(pct * 100).toFixed(pct < 0.1 ? 1 : 0)}%)`;
  const fill = $("meter-fill");
  fill.style.width = `${Math.min(100, pct * 100)}%`;
  const projPct = u.projected_bytes / cap;
  fill.className = "meter-fill" + (pct >= 1 ? " critical" : projPct > 1 ? " warning" : "");
  $("meter").setAttribute("aria-valuenow", Math.round(pct * 100));
  const elapsedFrac = 1 - u.days_left / u.days_total;
  $("meter-pace").style.left = `calc(${Math.min(100, elapsedFrac * 100)}% - 1px)`;
  $("meter-pace-label").textContent = `even pace today: ${fmtBytes(cap * elapsedFrac)}`;
  $("meter-cap").textContent = fmtBytes(cap);

  const sl = $("status-line");
  const end = dateFmt.format(parseDay(u.cycle_end));
  let kind, msg;
  if (pct >= 1) { kind = "critical"; msg = `<strong>Over the cap</strong> by ${fmtBytes(u.used_bytes - cap)}. Renews ${end}.`; }
  else if (projPct > 1) { kind = "warning"; msg = `<strong>On course to go over.</strong> At this rate you'll reach ${fmtBytes(u.projected_bytes)} by ${end}. Keep to ${fmtBytes(u.daily_budget_bytes)} a day to stay under.`; }
  else { kind = "good"; msg = `<strong>On track.</strong> At this rate you'll reach about ${fmtBytes(u.projected_bytes)} by ${end}.`; }
  sl.innerHTML = ICONS[kind];
  const s = el("div"); s.innerHTML = msg; sl.appendChild(s);

  $("t-today").textContent = fmtBytes(u.today_bytes);
  $("t-today-hint").textContent = u.today_bytes > u.daily_budget_bytes ? "above today's budget" : "within today's budget";
  $("t-budget").textContent = `${fmtBytes(u.daily_budget_bytes)}`;
  const elapsedDays = Math.max(u.days_total - u.days_left, 1 / 24);
  $("t-avg").textContent = fmtBytes(u.used_bytes / elapsedDays);
  $("t-avg-hint").textContent = `even pace is ${fmtBytes(u.even_pace_bytes)}`;
  $("t-days").textContent = u.days_left >= 1 ? Math.floor(u.days_left) : "<1";
  $("t-days-hint").textContent = `renews ${end}`;
  $("daily-note").textContent = u.adjustment_bytes ? `includes ${fmtBytes(Math.abs(u.adjustment_bytes))} ${u.adjustment_bytes > 0 ? "added" : "removed"} to match Safaricom's figure (not shown per day)` : "";

  drawDaily($("daily-chart"), u);
  drawHeat($("heat-chart"), u.heatmap);
  renderBanners();
}

function renderLive() {
  const last = live.points.at(-1);
  for (const [id, key] of [["live-down", "down_bps"], ["live-up", "up_bps"]]) {
    const box = $(id);
    const [n, unit] = fmtRate(last ? last[key] : null);
    box.replaceChildren(document.createTextNode(n + " "), el("span", unit, "u"));
  }
  drawLive($("live-chart"), live.points, live.now);
}

function renderDevices() {
  const q = $("dev-search").value.trim().toLowerCase();
  const body = $("dev-body");
  body.replaceChildren();
  const list = devices.filter((d) => !q || `${d.name} ${d.ip} ${d.mac}`.toLowerCase().includes(q));
  $("dev-count").textContent = `${devices.filter((d) => d.online).length} online`;
  if (!list.length) {
    const r = body.insertRow(); const c = el("td", devices.length ? "No matches" : "No devices found yet"); c.colSpan = 4; c.style.color = "var(--muted)"; r.appendChild(c);
    return;
  }
  for (const d of list) {
    const r = body.insertRow();
    const n = el("td"); n.appendChild(el("div", d.name)); n.appendChild(el("div", d.mac, "mono")); r.appendChild(n);
    r.appendChild(el("td", d.ip, "mono"));
    r.appendChild(el("td", d.connection || "–"));
    const s = el("td"); s.appendChild(el("span", d.online ? "Online" : "Offline", d.online ? "pill on" : "pill")); r.appendChild(s);
  }
}

// ---------- polling ----------

const timers = [];
function every(ms, fn) { fn(); timers.push(setInterval(fn, ms)); }
function stopPolling() { timers.splice(0).forEach(clearInterval); }

async function refreshStatus() {
  try {
    status = await api("/api/status");
  } catch { return; }
  if (!status.logged_in) return showLogin();
  renderStatus();
  renderBanners();
}

async function refreshUsage() {
  const charts = ["daily-chart", "heat-chart"].map($);
  charts.forEach((c) => c.classList.add("loading"));
  try { usage = await api("/api/usage"); renderUsage(); } catch {}
  charts.forEach((c) => c.classList.remove("loading"));
}

async function refreshLive() {
  try { live = await api("/api/live"); renderLive(); } catch {}
}

async function refreshDevices() {
  try { devices = (await api("/api/devices")).devices; renderDevices(); } catch {}
}

function showDashboard() {
  $("login-view").hidden = true;
  $("dash-view").hidden = false;
  stopPolling();
  every(5000, refreshStatus);
  every(Math.max(2, status?.poll_seconds || 5) * 1000, refreshLive);
  every(60000, refreshUsage);
  every(30000, refreshDevices);
  $("set-cap").value = status?.cap_gb ?? "";
  $("set-reset").value = status?.reset_day ?? "";
}

function showLogin() {
  stopPolling();
  $("dash-view").hidden = true;
  $("login-view").hidden = false;
  if (status?.router_host) $("login-host").value = status.router_host;
  if (status?.username) $("login-user").value = status.username;
  $("login-user").value ? $("login-pass").focus() : $("login-user").focus();
}

// ---------- events ----------

$("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = $("login-btn"), msg = $("login-msg");
  btn.disabled = true; btn.textContent = "Logging in…"; msg.textContent = "";
  try {
    await api("/api/login", {
      host: $("login-host").value, username: $("login-user").value,
      password: $("login-pass").value, remember: $("login-remember").checked,
    });
    $("login-pass").value = "";
    status = await api("/api/status");
    showDashboard();
  } catch (err) {
    msg.textContent = err.message;
  } finally {
    btn.disabled = false; btn.textContent = "Log in";
  }
});

$("logout-btn").addEventListener("click", async () => {
  await api("/api/logout", {}).catch(() => {});
  status = await api("/api/status").catch(() => status);
  showLogin();
});

$("settings-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const msg = $("settings-msg");
  try {
    await api("/api/settings", { cap_gb: $("set-cap").value, reset_day: $("set-reset").value });
    msg.className = "msg ok"; msg.textContent = "Saved.";
    refreshUsage();
  } catch (err) { msg.className = "msg err"; msg.textContent = err.message; }
});

$("calib-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const msg = $("settings-msg");
  try {
    await api("/api/calibrate", { used_gb: $("calib-gb").value });
    msg.className = "msg ok"; msg.textContent = "Matched. Counting on from Safaricom's figure.";
    $("calib-gb").value = "";
    refreshUsage();
  } catch (err) { msg.className = "msg err"; msg.textContent = err.message; }
});

$("dev-search").addEventListener("input", renderDevices);

$("login-show").addEventListener("change", (e) => {
  $("login-pass").type = e.target.checked ? "text" : "password";
});

function applyTheme(t) {
  if (t) document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme;
}
try { applyTheme(localStorage.getItem("theme")); } catch {}
$("theme-btn").addEventListener("click", () => {
  const dark = document.documentElement.dataset.theme
    ? document.documentElement.dataset.theme === "dark"
    : matchMedia("(prefers-color-scheme: dark)").matches;
  const next = dark ? "light" : "dark";
  applyTheme(next);
  try { localStorage.setItem("theme", next); } catch {}
});

let resizeT;
window.addEventListener("resize", () => {
  clearTimeout(resizeT);
  resizeT = setTimeout(() => { if (usage) renderUsage(); renderLive(); }, 150);
});

(async function start() {
  try { status = await api("/api/status"); } catch {
    document.body.textContent = "Can't reach the dashboard server. Is `python -m routerdash` still running?";
    return;
  }
  status.logged_in ? showDashboard() : showLogin();
})();
