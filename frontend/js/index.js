import {
  loadJSON, fmtPrice, fmtPct, fmtNum, signClass, esc, corrColor,
  makeTableSortable, sparkline, baseChartOptions,
} from "./common.js";

const [meta, items, events, analytics, sparks] = await Promise.all([
  loadJSON("meta.json"),
  loadJSON("items.json"),
  loadJSON("events.json"),
  loadJSON("analytics.json"),
  loadJSON("sparks.json"),
]);

const labels = Object.fromEntries(items.map((i) => [i.id, i.label]));

function trendColor(v) {
  if (v === null || v === undefined) return "#8b93a7";
  return v > 0 ? "#35d07f" : "#ff5f6d";
}

function renderHeader() {
  document.getElementById("generated-at").textContent = meta.generated_at.replace("T", " ").replace("Z", " UTC");
  const badge = document.getElementById("phase-badge");
  badge.textContent = meta.phase_label || meta.phase;
}

function renderSummary() {
  const t = events.current || {};
  const focus = analytics.focus || {};
  const agg = focus.aggregate || {};
  const cards = [
    {
      k: "Sitting mayor",
      v: t.mayor || "—",
      s: t.minister ? `minister: ${t.minister}` : "no minister",
    },
    {
      k: "SkyBlock year",
      v: t.year ?? "—",
      s: t.end ? `term ends ${t.end} (${t.days_left}d)` : "in office",
    },
    {
      k: "Alerts",
      v: (analytics.alerts || []).length,
      s: `|Z30| ≥ ${analytics.z_threshold}`,
    },
    {
      k: "Tracked items",
      v: items.length,
      s: `phase: ${meta.phase}`,
    },
    {
      k: `${focus.mayor || "focus"} vol ratio`,
      v: agg.median_vol_ratio_slayer === null || agg.median_vol_ratio_slayer === undefined
        ? "—"
        : agg.median_vol_ratio_slayer.toFixed(2) + "x",
      s: `slayer items · ${agg.n_mayor_terms || 0} terms as mayor, ${agg.n_minister_terms || 0} as minister`,
    },
    {
      k: "Election day-1 effect",
      v: agg.median_day1_pct_slayer === null || agg.median_day1_pct_slayer === undefined
        ? "—"
        : fmtPct(agg.median_day1_pct_slayer),
      s: "median 24h move on inauguration (slayer)",
    },
  ];
  document.getElementById("summary-cards").innerHTML = cards
    .map(
      (c) => `<div class="card"><div class="k">${esc(c.k)}</div><div class="v">${esc(c.v)}</div><div class="s">${esc(c.s)}</div></div>`
    )
    .join("");
}

function rowHtml(item) {
  return `<tr data-id="${item.id}" class="clickable ${item.alert ? "alert-row" : ""}">
    <td class="l"><a href="item.html?id=${encodeURIComponent(item.id)}">${esc(item.label)}</a>
      ${item.alert ? '<span class="badge alert">alert</span>' : ""}</td>
    <td><canvas class="spark" width="90" height="26"></canvas></td>
    <td class="mono">${fmtPrice(item.mid)}</td>
    <td class="mono ${signClass(item.change_24h)}">${fmtPct(item.change_24h)}</td>
    <td class="mono ${signClass(item.change_7d)}">${fmtPct(item.change_7d)}</td>
    <td class="mono">${item.z_30d === null || item.z_30d === undefined ? "—" : item.z_30d.toFixed(2)}</td>
    <td class="mono">${item.spread === null || item.spread === undefined ? "—" : (item.spread * 100).toFixed(1) + "%"}</td>
    <td class="mono">${fmtNum(item.liquidity)}</td>
    <td class="mono ${signClass(item.pred_pct_h6)}">${fmtPrice(item.pred_px_h6)}</td>
    <td class="mono ${signClass(item.pred_pct_h24)}">${fmtPrice(item.pred_px_h24)}</td>
    <td class="mono">${item.skill_h6 === null || item.skill_h6 === undefined ? "—" : (item.skill_h6 * 100).toFixed(0) + "%"}</td>
  </tr>`;
}

function renderItems(group = "all") {
  const filtered = group === "all" ? items : items.filter((i) => i.group === group);
  const tbody = document.querySelector("#items-table tbody");
  tbody.innerHTML = filtered.map(rowHtml).join("");
  tbody.querySelectorAll("tr").forEach((tr) => {
    const item = items.find((i) => i.id === tr.dataset.id);
    const values = sparks[item.id] || [];
    sparkline(tr.querySelector("canvas"), values, trendColor(item.change_7d));
  });
}

function renderPills() {
  const groups = ["all", ...new Set(items.map((i) => i.group))];
  const el = document.getElementById("group-pills");
  el.innerHTML = groups
    .map((g) => `<span class="pill ${g === "all" ? "active" : ""}" data-group="${g}">${g}</span>`)
    .join("");
  el.querySelectorAll(".pill").forEach((pill) => {
    pill.addEventListener("click", () => {
      el.querySelectorAll(".pill").forEach((p) => p.classList.remove("active"));
      pill.classList.add("active");
      renderItems(pill.dataset.group);
    });
  });
}

function renderAlerts() {
  const cur = analytics.alerts || [];
  document.getElementById("alerts-current").innerHTML = cur.length
    ? `<table><thead><tr><th class="l">Item</th><th>Z</th><th>Mid</th><th>Time</th></tr></thead><tbody>${
        cur.map((a) => `<tr><td class="l"><a href="item.html?id=${a.item_id}">${esc(labels[a.item_id] || a.item_id)}</a>
          <span class="badge ${a.direction === "up" ? "ok" : "alert"}">${a.direction}</span></td>
          <td class="mono">${a.z.toFixed(2)}</td><td class="mono">${fmtPrice(a.mid)}</td><td class="mono muted">${a.t}</td></tr>`).join("")
      }</tbody></table>`
    : "No items currently beyond the z-threshold.";
  const hist = analytics.alert_history || [];
  document.querySelector("#alerts-history tbody").innerHTML = hist
    .map((a) => `<tr><td class="l"><a href="item.html?id=${a.item_id}">${esc(labels[a.item_id] || a.item_id)}</a></td>
      <td class="mono muted">${a.t}</td><td class="mono ${a.direction === "up" ? "pos" : "neg"}">${a.z.toFixed(2)}</td>
      <td class="mono">${fmtPrice(a.mid)}</td></tr>`)
    .join("");
}

function renderFocus() {
  const focus = analytics.focus || {};
  document.getElementById("focus-hint").textContent =
    `mayor "${focus.mayor}" periods across the full calendar (weight ${events.minister_weight} when minister)`;
  const per = (focus.per_item || []).slice().sort((a, b) => b.vol_ratio - a.vol_ratio);
  document.querySelector("#focus-table tbody").innerHTML = per
    .map((p) => `<tr><td class="l"><a href="item.html?id=${p.item_id}">${esc(p.label)}</a></td>
      <td class="mono ${p.vol_ratio > 1 ? "pos" : "neg"}">${p.vol_ratio.toFixed(2)}x</td>
      <td class="mono">${(p.abs_ret_active * 100).toFixed(2)}%</td>
      <td class="mono">${(p.abs_ret_base * 100).toFixed(2)}%</td>
      <td class="mono ${signClass(p.mean_ret_active)}">${fmtPct(p.mean_ret_active)}</td></tr>`)
    .join("");
  const day1 = (focus.day1_effects || []).slice().sort((a, b) => (b.start || "").localeCompare(a.start || ""));
  document.querySelector("#day1-table tbody").innerHTML = day1
    .map((e) => `<tr><td class="mono muted">${e.start}</td><td class="mono">${e.year ?? "—"}</td>
      <td class="l">${esc(labels[e.item_id] || e.item_id)}</td>
      <td class="mono ${signClass(e.pct_24h)}">${fmtPct(e.pct_24h)}</td></tr>`)
    .join("");
}

function renderCorrelations() {
  const corr = analytics.correlations || {};
  document.querySelector("#pairs-table tbody").innerHTML = (corr.top_pairs || [])
    .map((p) => `<tr><td class="l"><a href="item.html?id=${p.a}">${esc(labels[p.a] || p.a)}</a></td>
      <td class="l"><a href="item.html?id=${p.b}">${esc(labels[p.b] || p.b)}</a></td>
      <td class="mono ${corrColor(p.corr) ? signClass(p.corr) : ""}">${p.corr.toFixed(3)}</td></tr>`)
    .join("");
  const ids = corr.items || [];
  let html = "<thead><tr><th></th>" + ids.map((i) => `<th>${esc(labels[i] || i)}</th>`).join("") + "</tr></thead><tbody>";
  ids.forEach((a, ri) => {
    html += `<tr><th class="l">${esc(labels[a] || a)}</th>`;
    ids.forEach((b, ci) => {
      const v = corr.matrix[ri][ci];
      const txt = ri === ci ? "1" : v === null ? "" : v.toFixed(2);
      html += `<td class="${ri === ci ? "diag" : ""}" style="background:${ri === ci ? "" : corrColor(v)}" title="${esc(labels[a])} × ${esc(labels[b])}: ${v}">${txt}</td>`;
    });
    html += "</tr>";
  });
  document.getElementById("heat-table").innerHTML = html + "</tbody>";
}

function renderFooter() {
  document.getElementById("site-footer").innerHTML =
    `Generated ${esc(meta.generated_at)} · grid ${meta.grid_seconds / 3600}h · horizons ${meta.horizons.join(", ")}<br>` +
    `Sources: ${(meta.attributions || []).map((a) => `<a href="${a.url}" target="_blank" rel="noopener">${esc(a.name)}</a>`).join(" · ")}<br>` +
    `Not affiliated with Hypixel or Mojang. Prices are market snapshots; forecasts are statistical estimates, not financial advice.`;
}

renderHeader();
renderSummary();
renderPills();
renderItems();
renderAlerts();
renderFocus();
renderCorrelations();
renderFooter();
["#items-table", "#alerts-history", "#focus-table", "#day1-table", "#pairs-table"].forEach((sel) => {
  const t = document.querySelector(sel);
  if (t) makeTableSortable(t);
});
