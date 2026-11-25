"use strict";

(() => {
  const DATA = "data/";
  const MIN_N = 20; // fewer pathways than this: too few to estimate a median
  const PAGE = 40;
  const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
    "October", "November", "December"];
  const SVGNS = "http://www.w3.org/2000/svg";

  const $ = (selector) => document.querySelector(selector);
  const state = {
    meta: null,
    spec: null,
    specCode: "C_999",
    providers: new Map(),
    detail: null,
    origin: null,
    radius: 50,
    sort: "p18",
    measure: "md",
    showSmall: false,
    limit: PAGE,
    visible: [],
  };

  // ---------- formatting ----------
  const isNum = (value) => typeof value === "number" && Number.isFinite(value);
  const fmtInt = (value) => (isNum(value) ? Math.round(value).toLocaleString("en-GB") : "–");
  const fmtPct = (value) => (isNum(value) ? `${value.toFixed(1)}%` : "–");
  const fmtWeeks = (value) => (isNum(value) ? `${value.toFixed(1)} weeks` : "–");
  const fmtWk = (value) => (isNum(value) ? `${value.toFixed(1)} wks` : "–");
  function fmtBig(value) {
    if (!isNum(value)) return "–";
    if (value >= 1e6) return `${(value / 1e6).toFixed(2)} million`;
    return fmtInt(value);
  }
  function fmtCompact(value) {
    if (!isNum(value)) return "–";
    if (value >= 1e6) return `${(value / 1e6).toFixed(2)}M`;
    if (value >= 1e4) return `${Math.round(value / 1e3)}K`;
    return fmtInt(value);
  }
  function monthName(period, short = false) {
    const [year, month] = period.split("-").map(Number);
    const name = MONTHS[month - 1];
    return `${short ? name.slice(0, 3) : name} ${year}`;
  }
  const last = (array) => (array && array.length ? array[array.length - 1] : null);
  const escapeHtml = (text) => String(text ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;",
  })[c]);

  function el(tag, attrs = {}, parent = null) {
    const node = document.createElementNS(SVGNS, tag);
    for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
    if (parent) parent.appendChild(node);
    return node;
  }
  function linePath(points) {
    let d = "";
    let pen = false;
    for (const point of points) {
      if (!point) { pen = false; continue; }
      d += `${pen ? "L" : "M"}${point[0].toFixed(1)},${point[1].toFixed(1)}`;
      pen = true;
    }
    return d;
  }

  // ---------- tooltip ----------
  const tooltip = $("#tooltip");
  function showTip(html, x, y) {
    tooltip.innerHTML = html;
    tooltip.hidden = false;
    const box = tooltip.getBoundingClientRect();
    let left = x + 14;
    let top = y + 14;
    if (left + box.width > window.innerWidth - 8) left = x - box.width - 14;
    if (top + box.height > window.innerHeight - 8) top = y - box.height - 14;
    tooltip.style.left = `${Math.max(8, left)}px`;
    tooltip.style.top = `${Math.max(8, top)}px`;
  }
  const hideTip = () => { tooltip.hidden = true; };

  // ---------- data ----------
  async function getJSON(path) {
    const response = await fetch(DATA + path, { cache: "no-cache" });
    if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
    return response.json();
  }

  function nationalSeries(code = "C_999") {
    return state.meta.national[code] || state.meta.national.C_999;
  }

  // ---------- intro and tiles ----------
  function renderIntro() {
    const { meta } = state;
    const nat = nationalSeries();
    const latest = monthName(meta.latest);
    $("#data-month").textContent = `NHS England referral-to-treatment data · ${latest}`;
    $("#lede").innerHTML = `At the end of ${latest}, <strong>${fmtBig(last(nat.n))}</strong> pathways were waiting to start ` +
      `consultant-led treatment in England. <strong>${fmtPct(last(nat.p18))}</strong> had waited 18 weeks or less, ` +
      `against a constitutional standard of 92%. Half had waited longer than <strong>${fmtWeeks(last(nat.md))}</strong>.`;
    $("#month-count").textContent = String(meta.periods.length);
    $("#generated").textContent = `Data to ${latest}. Built ${new Date(meta.generated_at).toLocaleDateString("en-GB", {
      day: "numeric", month: "long", year: "numeric" })}.`;
  }

  function sparkline(values, width, height, { stroke = "var(--soft)", dot = "var(--accent)" } = {}) {
    const svg = el("svg", { width, height, viewBox: `0 0 ${width} ${height}`, "aria-hidden": "true" });
    const numbers = values.filter(isNum);
    if (numbers.length < 2) return svg;
    let lo = Math.min(...numbers);
    let hi = Math.max(...numbers);
    if (hi - lo < 1e-9) { lo -= 1; hi += 1; }
    const pad = 5;
    const x = (i) => pad + (i * (width - 2 * pad)) / (values.length - 1);
    const y = (v) => height - pad - ((v - lo) / (hi - lo)) * (height - 2 * pad);
    const points = values.map((v, i) => (isNum(v) ? [x(i), y(v)] : null));
    el("path", { d: linePath(points), fill: "none", style: `stroke:${stroke}`, "stroke-width": 2,
      "stroke-linejoin": "round", "stroke-linecap": "round" }, svg);
    let end = values.length - 1;
    while (end > 0 && !isNum(values[end])) end -= 1;
    if (isNum(values[end])) {
      el("circle", { cx: x(end), cy: y(values[end]), r: 4, style: `fill:${dot};stroke:var(--surface)`,
        "stroke-width": 2 }, svg);
    }
    return svg;
  }

  function renderTiles() {
    const { meta } = state;
    const nat = nationalSeries();
    const index = meta.periods.length - 1;
    const back = Math.max(0, index - 12);
    const since = monthName(meta.periods[back], true);
    const tiles = [
      { label: "Pathways waiting", values: nat.n, value: fmtCompact(last(nat.n)), better: "down",
        delta: (a, b) => `${b >= a ? "+" : "−"}${fmtCompact(Math.abs(b - a))} since ${since}` },
      { label: "Seen within 18 weeks", values: nat.p18, value: fmtPct(last(nat.p18)), better: "up",
        delta: (a, b) => `${b >= a ? "+" : "−"}${Math.abs(b - a).toFixed(1)} points since ${since} · standard 92%` },
      { label: "Median wait so far", values: nat.md, value: fmtWeeks(last(nat.md)), better: "down",
        delta: (a, b) => `${b >= a ? "+" : "−"}${Math.abs(b - a).toFixed(1)} weeks since ${since}` },
      { label: "Waiting over 52 weeks", values: nat.o52, value: fmtCompact(last(nat.o52)), better: "down",
        delta: (a, b) => `${b >= a ? "+" : "−"}${fmtCompact(Math.abs(b - a))} since ${since}` },
    ];
    const host = $("#tiles");
    host.innerHTML = "";
    for (const tile of tiles) {
      const card = document.createElement("div");
      card.className = "tile";
      const a = tile.values[back];
      const b = tile.values[index];
      let deltaText = "";
      let improving = false;
      if (isNum(a) && isNum(b)) {
        deltaText = tile.delta(a, b);
        improving = tile.better === "up" ? b > a : b < a;
      }
      card.innerHTML = `<p class="label">${tile.label}</p><p class="value">${tile.value}</p>` +
        `<p class="delta"${improving ? ' style="color:var(--good-text)"' : ""}>${escapeHtml(deltaText)}</p>`;
      host.appendChild(card);
      const inner = card.clientWidth - 36;
      card.appendChild(sparkline(tile.values, Math.max(80, Math.min(260, inner)), 34));
    }
  }

  // ---------- national chart ----------
  function renderNationalChart() {
    const host = $("#national-chart");
    host.innerHTML = "";
    const { meta } = state;
    const nat = nationalSeries();
    const values = nat.p18;
    const periods = meta.periods;
    const width = Math.max(300, host.clientWidth);
    const narrow = width < 640;
    const height = narrow ? 240 : 300;
    const m = { top: 14, right: narrow ? 14 : 196, bottom: 30, left: 44 };
    const numbers = values.filter(isNum);
    const lo = Math.max(0, Math.floor((Math.min(...numbers) - 8) / 10) * 10);
    const hi = 100;
    const x = (i) => m.left + (i * (width - m.left - m.right)) / Math.max(1, periods.length - 1);
    const y = (v) => m.top + ((hi - v) / (hi - lo)) * (height - m.top - m.bottom);
    const svg = el("svg", { width, height, viewBox: `0 0 ${width} ${height}` }, host);

    for (let tick = lo; tick <= hi; tick += 10) {
      el("line", { x1: m.left, x2: width - m.right, y1: y(tick), y2: y(tick),
        class: tick === lo ? "baseline" : "gridline" }, svg);
      const label = el("text", { x: m.left - 8, y: y(tick) + 4, "text-anchor": "end" }, svg);
      label.textContent = `${tick}%`;
    }
    periods.forEach((period, i) => {
      const month = Number(period.slice(5));
      const show = narrow ? month === 9 : month === 3 || month === 9;
      if (!show) return;
      const label = el("text", { x: x(i), y: height - 8, "text-anchor": "middle" }, svg);
      label.textContent = monthName(period, true);
    });
    for (const target of meta.targets) {
      if (target.value < lo || target.value > hi) continue;
      el("line", { x1: m.left, x2: width - m.right, y1: y(target.value), y2: y(target.value), class: "target" }, svg);
      const label = el("text", {
        x: narrow ? m.left + 4 : width - m.right + 8,
        y: narrow ? y(target.value) - 5 : y(target.value) + 4,
        "text-anchor": "start",
        class: "label-strong halo",
      }, svg);
      label.textContent = `${target.value}% ${target.short || target.label}`;
    }
    const points = values.map((v, i) => (isNum(v) ? [x(i), y(v)] : null));
    el("path", { d: linePath(points), class: "series" }, svg);
    const endIndex = values.length - 1;
    if (isNum(values[endIndex])) {
      el("circle", { cx: x(endIndex), cy: y(values[endIndex]), r: 4.5, class: "dot" }, svg);
      const label = el("text", { x: x(endIndex) - 8, y: y(values[endIndex]) - 10, "text-anchor": "end",
        class: "label-strong halo" }, svg);
      label.textContent = fmtPct(values[endIndex]);
    }

    const cross = el("line", { y1: m.top, y2: height - m.bottom, class: "crosshair", visibility: "hidden" }, svg);
    const marker = el("circle", { r: 5, class: "dot", visibility: "hidden" }, svg);
    const overlay = el("rect", { x: m.left, y: m.top, width: width - m.left - m.right,
      height: height - m.top - m.bottom, fill: "transparent" }, svg);
    overlay.addEventListener("pointermove", (event) => {
      const box = svg.getBoundingClientRect();
      const px = event.clientX - box.left;
      const i = Math.max(0, Math.min(periods.length - 1,
        Math.round(((px - m.left) / (width - m.left - m.right)) * (periods.length - 1))));
      if (!isNum(values[i])) return;
      cross.setAttribute("x1", x(i));
      cross.setAttribute("x2", x(i));
      cross.setAttribute("visibility", "visible");
      marker.setAttribute("cx", x(i));
      marker.setAttribute("cy", y(values[i]));
      marker.setAttribute("visibility", "visible");
      showTip(`<strong>${monthName(periods[i])}</strong>${fmtPct(values[i])} within 18 weeks<br>` +
        `${fmtBig(nat.n[i])} pathways waiting`, event.clientX, event.clientY);
    });
    overlay.addEventListener("pointerleave", () => {
      cross.setAttribute("visibility", "hidden");
      marker.setAttribute("visibility", "hidden");
      hideTip();
    });

    const rows = periods.map((period, i) => `<tr><td>${monthName(period)}</td><td>${fmtPct(values[i])}</td>` +
      `<td>${fmtInt(nat.n[i])}</td><td>${fmtWk(nat.md[i])}</td><td>${fmtInt(nat.o52[i])}</td></tr>`).join("");
    $("#national-table").innerHTML = `<table class="data"><thead><tr><th>Month</th><th>Within 18 weeks</th>` +
      `<th>Waiting</th><th>Median wait</th><th>Over 52 weeks</th></tr></thead><tbody>${rows}</tbody></table>`;
  }

  // ---------- validation ----------
  function renderValidation() {
    const host = $("#validation");
    const results = state.meta.validation || [];
    if (!results.length) {
      host.innerHTML = "<p>No press-notice month falls inside the current data window.</p>";
      return;
    }
    host.innerHTML = results.map((result) => {
      const rows = result.checks.map((check) => `<tr><td>${escapeHtml(check.measure)}</td>` +
        `<td>${fmtNumber(check.published)}</td><td>${fmtNumber(check.computed)}</td>` +
        `<td>${check.ok ? '<span class="check-ok">✓ matches</span>' : '<span class="check-diff">≠ differs</span>'}</td></tr>`)
        .join("");
      return `<p><a href="${escapeHtml(result.source)}">${monthName(result.period)} press notice</a></p>` +
        `<table class="data"><thead><tr><th>Measure</th><th>Published</th><th>WaitLens</th><th></th></tr></thead>` +
        `<tbody>${rows}</tbody></table>`;
    }).join("");
  }
  const fmtNumber = (value) => (isNum(value) ? (Number.isInteger(value) ? fmtInt(value) : value.toFixed(1)) : "–");

  // ---------- specialty and controls ----------
  function populateSpecialties() {
    const select = $("#specialty");
    const specialties = [...state.meta.specialties].sort((a, b) => {
      if (a.code === "C_999") return -1;
      if (b.code === "C_999") return 1;
      return a.label.localeCompare(b.label);
    });
    select.innerHTML = specialties.map((spec) => `<option value="${spec.code}">${escapeHtml(spec.label)}</option>`)
      .join("");
  }

  function readUrl() {
    const params = new URLSearchParams(window.location.search);
    const code = params.get("s");
    if (code && state.meta.specialties.some((spec) => spec.code === code)) state.specCode = code;
    const sort = params.get("sort");
    if (sort && ["p18", "md", "a_md", "n_md"].includes(sort)) state.sort = sort;
  }

  function writeUrl() {
    const params = new URLSearchParams();
    if (state.specCode !== "C_999") params.set("s", state.specCode);
    if (state.sort !== "p18" && state.sort !== "distance") params.set("sort", state.sort);
    const query = params.toString();
    window.history.replaceState(null, "", query ? `?${query}` : window.location.pathname);
  }

  function syncControls() {
    $("#specialty").value = state.specCode;
    const spec = state.meta.specialties.find((item) => item.code === state.specCode);
    $("#specialty-hint").textContent = spec && spec.hint ? spec.hint : "";
    $("#radius").disabled = !state.origin;
    $("#radius").value = String(state.radius);
    const distanceOption = $("#sort").querySelector('option[value="distance"]');
    distanceOption.disabled = !state.origin;
    if (!state.origin && state.sort === "distance") state.sort = "p18";
    $("#sort").value = state.sort;
    for (const button of document.querySelectorAll(".seg")) {
      button.setAttribute("aria-pressed", String(button.dataset.measure === state.measure));
    }
  }

  async function loadSpec() {
    const code = state.specCode;
    $("#results-count").textContent = "Loading…";
    try {
      const spec = await getJSON(`spec/${code}.json`);
      if (code !== state.specCode) return;
      state.spec = spec;
      state.limit = PAGE;
      render();
    } catch (error) {
      $("#results-count").textContent = "Could not load this specialty. Please try again.";
    }
  }

  // ---------- postcode ----------
  async function lookupPostcode(text) {
    const status = $("#postcode-status");
    const compact = text.toUpperCase().replace(/\s+/g, "");
    if (!compact) {
      state.origin = null;
      status.textContent = "Looked up with postcodes.io. Nothing is stored.";
      syncControls();
      render();
      return;
    }
    let url;
    if (/^[A-Z]{1,2}\d[A-Z\d]?\d[A-Z]{2}$/.test(compact)) {
      url = `https://api.postcodes.io/postcodes/${encodeURIComponent(compact)}`;
    } else if (/^[A-Z]{1,2}\d[A-Z\d]?$/.test(compact)) {
      url = `https://api.postcodes.io/outcodes/${encodeURIComponent(compact)}`;
    } else {
      status.textContent = "That does not look like a UK postcode. Try something like LS1 4AP.";
      return;
    }
    status.textContent = "Looking up…";
    try {
      const response = await fetch(url);
      const body = await response.json();
      const result = body && body.result;
      if (!response.ok || !result || !isNum(result.latitude)) throw new Error("not found");
      const label = result.postcode || result.outcode || compact;
      state.origin = { lat: result.latitude, lon: result.longitude, label };
      state.sort = "distance";
      status.textContent = `Showing distances from ${label}.`;
    } catch (error) {
      status.textContent = "We could not find that postcode. Check it and try again.";
    }
    syncControls();
    render();
  }

  function miles(a, b) {
    const rad = Math.PI / 180;
    const dLat = (b.lat - a.lat) * rad;
    const dLon = (b.lon - a.lon) * rad;
    const h = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(dLon / 2) ** 2;
    return 3958.8 * 2 * Math.asin(Math.sqrt(h));
  }

  // ---------- results ----------
  function buildRows() {
    const rows = [];
    for (const row of state.spec.rows) {
      const provider = state.providers.get(row.c) || { code: row.c, name: row.c, area: "", kind: "nhs" };
      const waiting = last(row.w);
      const small = !(isNum(waiting) && waiting >= MIN_N) && !(row.a_n >= MIN_N) && !(row.n_n >= MIN_N);
      let distance = null;
      if (state.origin && isNum(provider.lat) && !provider.multi_site) distance = miles(state.origin, provider);
      rows.push({
        ...row, provider, small, distance,
        md_now: isNum(waiting) && waiting >= MIN_N ? last(row.md) : null,
        p18_now: isNum(waiting) && waiting > 0 ? last(row.p18) : null,
        a_md_ok: row.a_n >= MIN_N ? row.a_md : null,
        n_md_ok: row.n_n >= MIN_N ? row.n_md : null,
      });
    }
    return rows;
  }

  function filterAndSort(rows) {
    let hiddenNoLocation = 0;
    let list = rows.filter((row) => state.showSmall || !row.small);
    if (state.origin && state.radius > 0) {
      list = list.filter((row) => {
        if (row.distance === null) { hiddenNoLocation += 1; return false; }
        return row.distance <= state.radius;
      });
    }
    const asc = (key) => (a, b) => (isNum(a[key]) ? a[key] : Infinity) - (isNum(b[key]) ? b[key] : Infinity);
    const desc = (key) => (a, b) => (isNum(b[key]) ? b[key] : -Infinity) - (isNum(a[key]) ? a[key] : -Infinity);
    const sorters = { distance: asc("distance"), p18: desc("p18_now"), md: asc("md_now"), a_md: asc("a_md_ok"),
      n_md: asc("n_md_ok") };
    list.sort((a, b) => sorters[state.sort](a, b) || a.provider.name.localeCompare(b.provider.name));
    return { list, hiddenNoLocation };
  }

  function render() {
    if (!state.spec) return;
    syncControls();
    writeUrl();
    const spec = state.meta.specialties.find((item) => item.code === state.specCode);
    const rows = buildRows();
    const { list, hiddenNoLocation } = filterAndSort(rows);
    state.visible = list;
    renderStrip(rows, list, spec);

    let summary = `${list.length} provider${list.length === 1 ? "" : "s"}`;
    summary += state.origin && state.radius > 0 ? ` within ${state.radius} miles of ${state.origin.label}` : " in England";
    summary += ` · ${spec ? spec.label.toLowerCase() : ""}`;
    if (hiddenNoLocation) summary += ` · ${hiddenNoLocation} without a single location not shown`;
    $("#results-count").textContent = summary;

    const host = $("#results");
    host.innerHTML = "";
    if (!list.length) {
      host.innerHTML = `<li class="empty">No providers match. Try a larger distance or include very small services.</li>`;
      return;
    }
    for (const row of list.slice(0, state.limit)) host.appendChild(renderRow(row));
    if (list.length > state.limit) {
      const li = document.createElement("li");
      const button = document.createElement("button");
      button.className = "button";
      button.type = "button";
      button.textContent = `Show ${Math.min(PAGE, list.length - state.limit)} more`;
      button.addEventListener("click", () => { state.limit += PAGE; render(); });
      li.appendChild(button);
      host.appendChild(li);
    }
  }

  function renderRow(row) {
    const li = document.createElement("li");
    li.className = "row";
    const provider = row.provider;
    const waiting = last(row.w);
    const kind = provider.kind === "nhs" ? "NHS trust" : "Independent provider";
    const where = [];
    if (provider.area) where.push(`<span>${escapeHtml(provider.area)}</span>`);
    where.push(`<span class="badge">${kind}</span>`);
    if (isNum(row.distance)) where.push(`<span>${row.distance.toFixed(row.distance < 10 ? 1 : 0)} miles</span>`);
    else if (provider.multi_site) where.push("<span>Several sites</span>");
    const firstIndex = row.p18.findIndex(isNum);
    const trend = firstIndex >= 0 && isNum(last(row.p18)) ?
      `${Math.round(row.p18[firstIndex])}% → ${Math.round(last(row.p18))}% within 18 wks` : "Not enough data";
    const p18 = row.p18_now;
    const notEnough = '<span class="na" title="Fewer than 20 pathways">too few</span>';
    li.innerHTML = `
      <div class="row-main">
        <div class="who"><h3>${escapeHtml(provider.name)}</h3><p class="meta">${where.join("")}</p></div>
        <div class="metric">
          <p class="k">Waiting now</p>
          <p class="v">${isNum(p18) ? fmtPct(p18) : '<span class="na">–</span>'}</p>
          <p class="s">within 18 weeks · ${fmtInt(waiting)} waiting</p>
          <div class="meter" aria-hidden="true"><i style="width:${isNum(p18) ? p18 : 0}%"></i><b style="left:92%"></b></div>
        </div>
        <div class="metric">
          <p class="k">Median wait so far</p>
          <p class="v">${isNum(row.md_now) ? fmtWk(row.md_now) : notEnough}</p>
          <p class="s">${fmtInt(last(row.o52))} waiting over 52 weeks</p>
        </div>
        <div class="metric">
          <p class="k">Recently treated</p>
          <p class="v">${isNum(row.a_md_ok) ? fmtWk(row.a_md_ok) : notEnough}</p>
          <p class="s">median for admitted care · outpatient ${isNum(row.n_md_ok) ? fmtWk(row.n_md_ok) : "too few"}</p>
        </div>
        <div class="spark" title="Share within 18 weeks, ${monthName(state.meta.periods[0], true)} to ${monthName(state.meta.latest, true)}"></div>
      </div>
      <button type="button" class="more" aria-expanded="false">All specialties at this provider</button>
      <div class="detail" hidden></div>`;
    const spark = li.querySelector(".spark");
    spark.appendChild(sparkline(row.p18, 128, 36, { stroke: "var(--soft)" }));
    const caption = document.createElement("div");
    caption.textContent = trend;
    spark.appendChild(caption);
    const more = li.querySelector(".more");
    const detail = li.querySelector(".detail");
    more.addEventListener("click", async () => {
      const open = more.getAttribute("aria-expanded") === "true";
      more.setAttribute("aria-expanded", String(!open));
      detail.hidden = open;
      if (!open && !detail.dataset.loaded) {
        detail.textContent = "Loading…";
        try {
          if (!state.detail) state.detail = await getJSON("providers.json");
          detail.innerHTML = providerTable(provider.code);
          detail.dataset.loaded = "1";
        } catch (error) {
          detail.textContent = "Could not load the details.";
        }
      }
    });
    return li;
  }

  function providerTable(code) {
    const labels = new Map(state.meta.specialties.map((spec) => [spec.code, spec.label]));
    const entries = [...(state.detail[code] || [])].sort((a, b) => {
      if (a.s === "C_999") return -1;
      if (b.s === "C_999") return 1;
      return (b.w || 0) - (a.w || 0);
    });
    const rows = entries.map((entry) => {
      const okWaiting = isNum(entry.w) && entry.w >= MIN_N;
      return `<tr><td>${escapeHtml(labels.get(entry.s) || entry.s)}</td><td>${fmtInt(entry.w)}</td>` +
        `<td>${isNum(entry.w) && entry.w > 0 ? fmtPct(entry.p18) : "–"}</td><td>${okWaiting ? fmtWk(entry.md) : "–"}</td>` +
        `<td>${fmtInt(entry.o52)}</td><td>${entry.a_n >= MIN_N ? fmtWk(entry.a_md) : "–"}</td>` +
        `<td>${entry.n_n >= MIN_N ? fmtWk(entry.n_md) : "–"}</td></tr>`;
    }).join("");
    return `<table class="data"><thead><tr><th>Specialty</th><th>Waiting</th><th>Within 18 wks</th>` +
      `<th>Median so far</th><th>Over 52 wks</th><th>Admitted, recent</th><th>Outpatient, recent</th></tr></thead>` +
      `<tbody>${rows}</tbody></table>`;
  }

  // ---------- strip plot ----------
  function renderStrip(allRows, visible, spec) {
    const host = $("#strip-chart");
    host.innerHTML = "";
    const measure = state.measure;
    const key = measure === "md" ? "md_now" : "p18_now";
    const near = new Set(state.origin ? visible.map((row) => row.c) : []);
    const rows = allRows.filter((row) => !row.small && isNum(row[key]) && isNum(last(row.w)) && last(row.w) >= MIN_N);
    const label = spec ? spec.label.toLowerCase() : "";
    $("#strip-title").textContent = measure === "md" ?
      `Median wait so far for ${label}, by provider` : `Share waiting 18 weeks or less for ${label}, by provider`;
    $("#strip-sub").textContent = state.origin ?
      `Each dot is a provider. Blue dots are the ${near.size} providers in your list.` :
      "Each dot is a provider. Add a postcode to highlight the ones near you.";
    if (!rows.length) {
      host.innerHTML = '<p class="hint">Not enough data to compare providers for this specialty.</p>';
      return;
    }
    const width = Math.max(300, host.clientWidth);
    const height = 150;
    const m = { top: 18, right: 16, bottom: 30, left: 16 };
    const values = rows.map((row) => row[key]);
    const lo = measure === "md" ? 0 : Math.max(0, Math.floor(Math.min(...values) / 10) * 10);
    const hi = measure === "md" ? Math.max(10, Math.ceil(Math.max(...values) / 5) * 5) : 100;
    const x = (v) => m.left + ((v - lo) / (hi - lo)) * (width - m.left - m.right);
    const svg = el("svg", { width, height, viewBox: `0 0 ${width} ${height}` }, host);
    const baseY = height - m.bottom;
    el("line", { x1: m.left, x2: width - m.right, y1: baseY, y2: baseY, class: "baseline" }, svg);
    const step = measure === "md" ? (hi > 40 ? 10 : 5) : 10;
    for (let tick = lo; tick <= hi + 1e-9; tick += step) {
      const text = el("text", { x: x(tick), y: height - 10, "text-anchor": "middle" }, svg);
      text.textContent = measure === "md" ? `${tick} wks` : `${tick}%`;
    }
    const nationalValue = last(nationalSeries(state.specCode)[measure === "md" ? "md" : "p18"]);
    if (isNum(nationalValue)) {
      el("line", { x1: x(nationalValue), x2: x(nationalValue), y1: m.top - 6, y2: baseY, class: "target" }, svg);
      const flip = x(nationalValue) > width - 120;
      const text = el("text", { x: x(nationalValue) + (flip ? -4 : 4), y: m.top - 6,
        "text-anchor": flip ? "end" : "start", class: "label-strong halo" }, svg);
      text.textContent = `England ${measure === "md" ? fmtWk(nationalValue) : fmtPct(nationalValue)}`;
    }
    // Beeswarm-lite: stack dots that share a pixel column.
    const radius = 4.5;
    const columns = new Map();
    const placed = rows.map((row) => {
      const cx = x(row[key]);
      const bucket = Math.round(cx / (radius * 2));
      const count = columns.get(bucket) || 0;
      columns.set(bucket, count + 1);
      const offset = Math.ceil(count / 2) * (radius * 2 + 1) * (count % 2 ? -1 : 1);
      return { row, cx, cy: (m.top + baseY) / 2 + 6 + offset };
    });
    placed.sort((a, b) => Number(near.has(a.row.c)) - Number(near.has(b.row.c)));
    for (const dot of placed) {
      el("circle", { cx: dot.cx, cy: Math.max(m.top + radius, Math.min(baseY - radius, dot.cy)), r: radius,
        class: `strip-dot${near.has(dot.row.c) ? " near" : ""}` }, svg);
    }
    svg.addEventListener("pointermove", (event) => {
      const box = svg.getBoundingClientRect();
      const px = event.clientX - box.left;
      const py = event.clientY - box.top;
      let best = null;
      let bestDistance = 14;
      for (const dot of placed) {
        const d = Math.hypot(dot.cx - px, Math.max(m.top + radius, Math.min(baseY - radius, dot.cy)) - py);
        if (d < bestDistance) { best = dot; bestDistance = d; }
      }
      if (!best) { hideTip(); return; }
      const row = best.row;
      showTip(`<strong>${escapeHtml(row.provider.name)}</strong>` +
        `${measure === "md" ? `Median wait so far ${fmtWk(row.md_now)}` : `${fmtPct(row.p18_now)} within 18 weeks`}` +
        `<br>${fmtInt(last(row.w))} waiting${isNum(row.distance) ? ` · ${row.distance.toFixed(0)} miles` : ""}`,
      event.clientX, event.clientY);
    });
    svg.addEventListener("pointerleave", hideTip);
  }

  // ---------- startup ----------
  function bind() {
    $("#specialty").addEventListener("change", (event) => {
      state.specCode = event.target.value;
      syncControls();
      loadSpec();
    });
    $("#controls").addEventListener("submit", (event) => {
      event.preventDefault();
      lookupPostcode($("#postcode").value);
    });
    $("#radius").addEventListener("change", (event) => { state.radius = Number(event.target.value); state.limit = PAGE; render(); });
    $("#sort").addEventListener("change", (event) => { state.sort = event.target.value; render(); });
    $("#show-small").addEventListener("change", (event) => { state.showSmall = event.target.checked; render(); });
    for (const button of document.querySelectorAll(".seg")) {
      button.addEventListener("click", () => { state.measure = button.dataset.measure; render(); });
    }
    let resizeTimer = null;
    window.addEventListener("resize", () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => { renderNationalChart(); render(); }, 150);
    });
  }

  async function init() {
    try {
      state.meta = await getJSON("meta.json");
    } catch (error) {
      $("#lede").textContent = "The data could not be loaded. Please refresh the page in a moment.";
      return;
    }
    for (const provider of state.meta.providers) state.providers.set(provider.code, provider);
    readUrl();
    renderIntro();
    renderTiles();
    renderNationalChart();
    renderValidation();
    populateSpecialties();
    syncControls();
    bind();
    await loadSpec();
  }

  init();
})();
