import {
  loadJSON, fmtPrice, fmtPct, fmtNum, signClass, esc, baseChartOptions, makeTableSortable,
} from "./common.js";

const params = new URLSearchParams(location.search);
const itemId = params.get("id");

const [meta, items, events, analytics] = await Promise.all([
  loadJSON("meta.json"),
  loadJSON("items.json"),
  loadJSON("events.json"),
  loadJSON("analytics.json"),
]);

const item = items.find((i) => i.id === itemId);
const labels = Object.fromEntries(items.map((i) => [i.id, i.label]));

if (!item) {
  document.getElementById("item-title").textContent = "Unknown item";
  document.getElementById("item-sub").textContent = `No watchlist entry for "${itemId}".`;
} else {
  const series = await loadJSON(`series/${item.id}.json`);
  renderAll(series);
}

function tLabel(s) {
  return s.slice(0, 16).replace("T", " ");
}

function renderHeader() {
  document.title = `${item.label} — Bazaar Analysis`;
  document.getElementById("item-title").innerHTML =
    `${esc(item.label)} <span class="badge">${esc(item.group)}</span> <span class="badge">${esc(item.sector)}</span>` +
    (item.alert ? ' <span class="badge alert">z-alert</span>' : "");
  const mayors = (item.mayors || []).join(", ") || "—";
  document.getElementById("item-sub").textContent =
    `fetched ${item.t} · relevant mayors: ${mayors} · last data point is ${item.stale_h === null ? "—" : item.stale_h + "h"} old`;
}

function renderCards() {
  const cards = [
    { k: "Mid price", v: fmtPrice(item.mid), s: `buy ${fmtPrice(item.instabuy)} / sell ${fmtPrice(item.instasell)}` },
    { k: "24h change", v: fmtPct(item.change_24h), s: `7d ${fmtPct(item.change_7d)}`, cls: signClass(item.change_24h) },
    { k: "Z-30d", v: item.z_30d === null ? "—" : item.z_30d.toFixed(2), s: `7d z ${item.z_7d === null ? "—" : item.z_7d.toFixed(2)}` },
    { k: "Spread", v: item.spread === null ? "—" : (item.spread * 100).toFixed(2) + "%", s: "instabuy vs instasell" },
    { k: "Liquidity", v: fmtNum(item.liquidity), s: "weekly buy+sell volume" },
  ];
  document.getElementById("item-cards").innerHTML = cards
    .map((c) => `<div class="card"><div class="k">${esc(c.k)}</div><div class="v ${c.cls || ""}">${esc(c.v)}</div><div class="s">${esc(c.s)}</div></div>`)
    .join("");
}

function forecastBlock() {
  if (item.pred_px_h6 === null || item.pred_px_h6 === undefined) {
    document.getElementById("forecast").innerHTML = '<span class="muted">No model for this item yet.</span>';
    return;
  }
  const rows = [
    ["6h", item.pred_pct_h6, item.pred_px_h6, item.skill_h6, item.dir_acc_h6],
    ["24h", item.pred_pct_h24, item.pred_px_h24, item.skill_h24, item.dir_acc_h24],
  ];
  document.getElementById("forecast").innerHTML = `<table><thead>
    <tr><th>Horizon</th><th>Δ</th><th>Target price</th><th>Skill vs naive</th><th>Dir. acc</th></tr></thead><tbody>${
    rows.map(([h, pct, px, skill, dir]) => `<tr>
      <td class="l">${h}</td>
      <td class="mono ${signClass(pct)}">${fmtPct(pct)}</td>
      <td class="mono">${fmtPrice(px)}</td>
      <td class="mono">${skill === null || skill === undefined ? "—" : (skill * 100).toFixed(1) + "%"}</td>
      <td class="mono">${dir === null || dir === undefined ? "—" : (dir * 100).toFixed(1) + "%"}</td>
    </tr>`).join("")
  }</tbody></table>
  <div class="s muted" style="margin-top:8px">XGBoost on 2h features (lags, rolling z-scores, volume, mayor/minister dummies). Skill = 1 − MAE/MAE(naive).</div>`;
}

function momentumBlock() {
  const kv = [
    ["Trend 24h", fmtPct(item.trend_24h)],
    ["Acceleration", fmtPct(item.accel_24h)],
    ["From 7d high", fmtPct(item.pct_from_7d_high)],
    ["From 7d low", fmtPct(item.pct_from_7d_low)],
    ["Corr with Booster Cookie (7d)", item.corr_ref_7d === null ? "—" : item.corr_ref_7d.toFixed(3)],
  ];
  document.getElementById("momentum").innerHTML =
    `<div class="kv">${kv.map(([k, v]) => `<div class="k">${esc(k)}</div><div class="mono ${signClass(parseFloat(v))}">${esc(v)}</div>`).join("")}</div>`;
}

function baseOpts(extra = {}) {
  const opts = baseChartOptions();
  opts.scales.y.ticks.callback = (v) => fmtPrice(v);
  return Object.assign(opts, extra);
}

function renderPriceChart(series) {
  const ctx = document.getElementById("price-chart");
  new Chart(ctx, {
    type: "line",
    data: {
      labels: series.t.map(tLabel),
      datasets: [
        { label: "mid", data: series.mid, borderColor: "#5b8cff", borderWidth: 1.6, pointRadius: 0, spanGaps: true },
        { label: "instabuy", data: series.ib, borderColor: "rgba(53,208,127,.7)", borderWidth: 1, pointRadius: 0, spanGaps: true },
        { label: "instasell", data: series.is, borderColor: "rgba(255,95,109,.7)", borderWidth: 1, pointRadius: 0, spanGaps: true },
        { label: "MA 7d", data: series.ma7, borderColor: "#ffb454", borderWidth: 1.4, pointRadius: 0, spanGaps: true },
        { label: "MA 30d", data: series.ma30, borderColor: "#b18cff", borderWidth: 1.4, pointRadius: 0, spanGaps: true },
      ],
    },
    options: baseOpts(),
  });
}

function renderZChart(series) {
  new Chart(document.getElementById("z-chart"), {
    type: "line",
    data: {
      labels: series.t.map(tLabel),
      datasets: [
        { label: "z (30d)", data: series.z, borderColor: "#5b8cff", borderWidth: 1.4, pointRadius: 0, spanGaps: true },
        { label: "+3σ", data: series.z.map(() => 3), borderColor: "rgba(255,95,109,.5)", borderWidth: 1, pointRadius: 0, borderDash: [5, 4] },
        { label: "−3σ", data: series.z.map(() => -3), borderColor: "rgba(255,95,109,.5)", borderWidth: 1, pointRadius: 0, borderDash: [5, 4] },
      ],
    },
    options: baseOpts(),
  });
}

function renderVolChart(series) {
  new Chart(document.getElementById("vol-chart"), {
    type: "line",
    data: {
      labels: series.t.map(tLabel),
      datasets: [
        { label: "sell volume", data: series.sv, borderColor: "#35d07f", borderWidth: 1.3, pointRadius: 0, spanGaps: true },
        { label: "buy volume", data: series.bv, borderColor: "#ff5f6d", borderWidth: 1.3, pointRadius: 0, spanGaps: true },
      ],
    },
    options: baseOpts(),
  });
}

function renderNeighbors() {
  const corr = analytics.correlations || {};
  const mine = (corr.neighbors || {})[item.id] || [];
  document.querySelector("#neighbors-table tbody").innerHTML = mine.length
    ? mine.map((n) => `<tr><td class="l"><a href="item.html?id=${n.item}">${esc(labels[n.item] || n.item)}</a></td>
        <td class="mono ${signClass(n.corr)}">${n.corr.toFixed(3)}</td></tr>`).join("")
    : '<tr><td class="l muted" colspan="2">not enough data</td></tr>';
}

function renderFocus() {
  const focus = analytics.focus || {};
  const mine = (focus.per_item || []).find((p) => p.item_id === item.id);
  const box = document.getElementById("focus-box");
  if (!mine) {
    box.innerHTML = '<span class="muted">not enough labeled history</span>';
    return;
  }
  const effects = (focus.day1_effects || []).filter((e) => e.item_id === item.id);
  const day1 = effects.length ? (effects.reduce((s, e) => s + e.pct_24h, 0) / effects.length) : null;
  box.innerHTML = `<div class="kv">
    <div class="k">Mayor</div><div>${esc((focus.mayor || "").toUpperCase())}</div>
    <div class="k">Volatility ratio</div><div class="mono ${mine.vol_ratio > 1 ? "pos" : "neg"}">${mine.vol_ratio.toFixed(2)}x (active vs baseline)</div>
    <div class="k">Mean |24h ret| active</div><div class="mono">${(mine.abs_ret_active * 100).toFixed(2)}%</div>
    <div class="k">Mean |24h ret| baseline</div><div class="mono">${(mine.abs_ret_base * 100).toFixed(2)}%</div>
    <div class="k">Mean 24h ret active</div><div class="mono ${signClass(mine.mean_ret_active)}">${fmtPct(mine.mean_ret_active)}</div>
    <div class="k">First-24h after inauguration</div><div class="mono ${signClass(day1)}">${day1 === null ? "—" : fmtPct(day1)} <span class="muted">(${effects.length} terms)</span></div>
  </div>`;
}

function renderTerms() {
  const terms = events.terms || [];
  const focusMayors = new Set(item.mayors || []);
  const day1 = Object.fromEntries(
    ((analytics.focus || {}).day1_effects || [])
      .filter((e) => e.item_id === item.id)
      .map((e) => [e.start, e.pct_24h])
  );
  const inFocus = (t) =>
    focusMayors.size === 0 || focusMayors.has(t.mayor) || focusMayors.has(t.minister) || t.mayor === null;
  const list = terms.filter(inFocus).slice().reverse();
  document.getElementById("terms-hint").textContent =
    focusMayors.size ? `showing terms involving: ${[...focusMayors].join(", ")}` : "showing all terms";
  document.querySelector("#terms-table tbody").innerHTML = list
    .map((t) => {
      const isCurrent = events.current && t.start === events.current.start;
      const d1 = day1[t.start];
      const mayor = t.mayor_name || (t.mayor === null ? "— unlabeled span —" : t.mayor);
      return `<tr class="${isCurrent ? "alert-row" : ""}">
        <td class="mono muted">${esc(t.start)}</td>
        <td class="mono muted">${t.end ? esc(t.end) : "…"}</td>
        <td class="l">${esc(mayor)}${isCurrent ? ' <span class="badge mayor">current</span>' : ""}</td>
        <td class="l">${esc(t.minister_name || "—")}</td>
        <td class="mono">${t.year ?? "—"}</td>
        <td class="muted">${esc(t.source || "")}</td>
        <td class="mono ${signClass(d1)}">${d1 === undefined ? "—" : fmtPct(d1)}</td>
      </tr>`;
    })
    .join("");
}

function renderAll(series) {
  renderHeader();
  renderCards();
  forecastBlock();
  momentumBlock();
  renderPriceChart(series);
  renderZChart(series);
  renderVolChart(series);
  renderNeighbors();
  renderFocus();
  renderTerms();
  makeTableSortable(document.querySelector("#neighbors-table"));
  makeTableSortable(document.querySelector("#terms-table"));
  document.getElementById("site-footer").innerHTML =
    `Generated ${esc(meta.generated_at)} · sources: ${(meta.attributions || []).map((a) => `<a href="${a.url}" target="_blank" rel="noopener">${esc(a.name)}</a>`).join(" · ")}<br>` +
    `Prices from Hypixel bazaar snapshots (live 2h collection) and Coflnet history (backfill). Not financial advice.`;
}
