import {
  loadJSON, fmtPrice, fmtPct, fmtNum, signClass, esc, corrColor,
  makeTableSortable, sparkline, baseChartOptions,
} from "./common.js";

const [meta, items, events, analytics, sparks, mayors, effects] = await Promise.all([
  loadJSON("meta.json"),
  loadJSON("items.json"),
  loadJSON("events.json"),
  loadJSON("analytics.json"),
  loadJSON("sparks.json"),
  loadJSON("mayors.json"),
  loadJSON("mayor_effects.json"),
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
  const focus = activeFocus();
  const agg = focus.aggregate || {};
  const shown = items.filter(matchesMayor);
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
      v: (analytics.alerts || []).filter((a) => visibleIds().has(a.item_id)).length,
      s: `|Z30| ≥ ${analytics.z_threshold}`,
    },
    {
      k: "Tracked items",
      v: shown.length,
      s: activeMayor === "all"
        ? `phase: ${meta.phase}`
        : `mayor: ${mayorLabel(activeMayor)} · ${items.length} total`,
    },
    {
      k: `${focus.mayor || "focus"} vol ratio`,
      v: agg.median_vol_ratio === null || agg.median_vol_ratio === undefined
        ? "—"
        : agg.median_vol_ratio.toFixed(2) + "x",
      s: `${focus.mayor || "focus"} items · ${agg.n_mayor_terms || 0} terms as mayor, ${agg.n_minister_terms || 0} as minister`,
    },
    {
      k: "Election day-1 effect",
      v: agg.median_day1_pct === null || agg.median_day1_pct === undefined
        ? "—"
        : fmtPct(agg.median_day1_pct),
      s: `median 24h move on inauguration (${focus.mayor || "focus"})`,
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

let activeMayor = location.hash.slice(1) || "all";
let activeGroup = "all";
let effectsRole = "mayor";

function mayorLabel(id) {
  return id.charAt(0).toUpperCase() + id.slice(1);
}

function itemMayors(item) {
  return item.mayors || [];
}

function matchesMayor(item) {
  if (activeMayor === "all") return true;
  const ms = itemMayors(item);
  if (activeMayor === "other") return ms.length === 0;
  return ms.includes(activeMayor);
}

function visibleIds() {
  return new Set(items.filter(matchesMayor).map((i) => i.id));
}

function activeFocus() {
  const byMayor = analytics.focus_by_mayor || {};
  if (activeMayor !== "all" && activeMayor !== "other" && byMayor[activeMayor]) {
    return byMayor[activeMayor];
  }
  return analytics.focus || {};
}

function renderItems() {
  const filtered = items
    .filter(matchesMayor)
    .filter((i) => activeGroup === "all" || i.group === activeGroup);
  const tbody = document.querySelector("#items-table tbody");
  tbody.innerHTML = filtered.map(rowHtml).join("");
  tbody.querySelectorAll("tr").forEach((tr) => {
    const item = items.find((i) => i.id === tr.dataset.id);
    const values = sparks[item.id] || [];
    sparkline(tr.querySelector("canvas"), values, trendColor(item.change_7d));
  });
}

function mayorDef(id) {
  return mayors.find((m) => m.id === id) || null;
}

function renderTabs() {
  const other = items.filter((i) => !itemMayors(i).length).length;
  const tabs = [
    { id: "all", name: "All", n: items.length },
    ...mayors.map((m) => ({ id: m.id, name: m.name, n: m.items.length, phase: m.phase })),
  ];
  if (other) tabs.push({ id: "other", name: "Other", n: other });
  if (!tabs.some((t) => t.id === activeMayor)) activeMayor = "all";
  const el = document.getElementById("mayor-tabs");
  el.innerHTML = tabs
    .map((t) => {
      const n = t.n > 0 ? `<span class="n">${t.n}</span>` : `<span class="n soon">soon</span>`;
      return `<a class="tab ${t.id === activeMayor ? "active" : ""}" href="#${esc(t.id)}" data-mayor="${esc(t.id)}">${esc(t.name)}${n}</a>`;
    })
    .join("");
  el.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", (ev) => {
      ev.preventDefault();
      applyMayor(tab.dataset.mayor);
      history.replaceState(null, "", tab.dataset.mayor === "all" ? location.pathname : "#" + tab.dataset.mayor);
    });
  });
}

function renderPlaceholder() {
  const el = document.getElementById("ph-title");
  const body = document.getElementById("ph-body");
  if (activeMayor === "other") {
    el.textContent = "Other items";
    body.innerHTML = "No unassigned items.";
    return;
  }
  const m = mayorDef(activeMayor);
  const name = m ? m.name : activeMayor;
  const phase = m && m.phase ? `Phase ${m.phase}` : "";
  const tagline = (m && m.tagline) || "";
  el.innerHTML = `${esc(name)} <span class="badge mayor">${esc(phase || "blueprint")}</span>`;
  body.innerHTML = [
    tagline ? `<p>${esc(tagline)}.</p>` : "",
    `<p>No items tracked for ${esc(name)} yet — this page is a placeholder blueprint.</p>`,
    `<p class="muted">When ${esc(name)}'s watchlist items are added, this tab will populate with the same sections the Aatrox page uses: summary cards, watchlist, z-alerts, mayor-focus analysis and cross-item correlations.</p>`,
  ].join("");
}

function intervalPx(mid, iv) {
  if (!iv || iv.pred_px === null || iv.pred_px === undefined) return "—";
  return fmtPrice(iv.pred_px);
}

function renderMayorEffects() {
  const sec = document.getElementById("mayor-effects");
  const def = effects.mayors ? effects.mayors[activeMayor] : null;
  if (!def) {
    sec.hidden = true;
    return;
  }
  sec.hidden = false;
  const intervals = effects.intervals || [];
  document.getElementById("effects-title").textContent = `${def.name} — inauguration effect`;
  document.getElementById("effects-hint").textContent =
    "static historical medians over intervals around inauguration (not a live forecast)";

  const roleEl = document.getElementById("effects-role");
  const roleData = (def.roles || {})[effectsRole] || { n_terms: 0, by_interval: {}, items: [] };
  const roleLabel = { mayor: "As mayor", minister: "As minister" };
  roleEl.innerHTML = ["mayor", "minister"]
    .map((r) => {
      const n = ((def.roles || {})[r] || {}).n_terms || 0;
      return `<button class="role-btn ${r === effectsRole ? "active" : ""}" data-role="${r}">${roleLabel[r]} <span class="n">${n}</span></button>`;
    })
    .join("");
  roleEl.querySelectorAll(".role-btn").forEach((b) => {
    b.addEventListener("click", () => {
      effectsRole = b.dataset.role;
      renderMayorEffects();
    });
  });

  const cardsEl = document.getElementById("effects-cards");
  if (!def.items.length) {
    cardsEl.innerHTML = "";
    document.querySelector("#effects-table thead").innerHTML = "";
    document.querySelector("#effects-table tbody").innerHTML =
      `<tr><td class="muted">No items tagged for ${esc(def.name)} yet — the inauguration predictor fills in once its watchlist items are curated.</td></tr>`;
    return;
  }

  cardsEl.innerHTML = intervals
    .map((iv) => {
      const s = roleData.by_interval[iv.id];
      const val = s ? fmtPct(s.median) : "—";
      const sub = s
        ? `${s.n_items} items · ${(s.pos_rate * 100).toFixed(0)}% rose · ${roleData.n_terms} terms`
        : `${roleData.n_terms} terms · insufficient data`;
      return `<div class="card"><div class="k">${esc(iv.label)}</div><div class="v ${s ? signClass(s.median) : ""}">${val}</div><div class="s">${esc(sub)}</div></div>`;
    })
    .join("");

  const head = `<tr><th class="l">Item</th><th>Mid</th>${intervals
    .map((iv) => `<th>${esc(iv.label)}</th><th>px</th>`)
    .join("")}</tr>`;
  document.querySelector("#effects-table thead").innerHTML = head;
  document.querySelector("#effects-table tbody").innerHTML = roleData.items
    .map((rec) => {
      const cells = intervals
        .map((iv) => {
          const s = rec.intervals[iv.id];
          const pct = s ? fmtPct(s.median) : "—";
          return `<td class="mono ${s ? signClass(s.median) : ""}">${pct}<span class="muted"> n${s ? s.n : 0}</span></td>` +
            `<td class="mono">${intervalPx(rec.mid, s)}</td>`;
        })
        .join("");
      return `<tr><td class="l"><a href="item.html?id=${encodeURIComponent(rec.item_id)}">${esc(rec.label)}</a></td>` +
        `<td class="mono">${fmtPrice(rec.mid)}</td>${cells}</tr>`;
    })
    .join("");
}

function renderPills() {
  const pool = items.filter(matchesMayor);
  const groups = ["all", ...new Set(pool.map((i) => i.group))];
  if (!groups.includes(activeGroup)) activeGroup = "all";
  const el = document.getElementById("group-pills");
  el.innerHTML = groups
    .map((g) => `<span class="pill ${g === activeGroup ? "active" : ""}" data-group="${esc(g)}">${esc(g)}</span>`)
    .join("");
  el.querySelectorAll(".pill").forEach((pill) => {
    pill.addEventListener("click", () => {
      activeGroup = pill.dataset.group;
      renderPills();
      renderItems();
    });
  });
}

function applyMayor(mayor) {
  const valid = mayor === "all" || mayor === "other" || mayorDef(mayor) || items.some((i) => itemMayors(i).includes(mayor));
  activeMayor = valid ? mayor : "all";
  activeGroup = "all";
  renderTabs();
  const isRealMayor = activeMayor !== "all" && activeMayor !== "other" && (effects.mayors && effects.mayors[activeMayor]);
  document.getElementById("mayor-effects").hidden = !(isRealMayor);
  if (isRealMayor) {
    effectsRole = "mayor";
    renderMayorEffects();
  }
  const hasItems = items.some(matchesMayor);
  document.getElementById("dashboard").hidden = !hasItems;
  document.getElementById("mayor-placeholder").hidden = hasItems;
  if (!hasItems) {
    renderPlaceholder();
    return;
  }
  renderSummary();
  renderPills();
  renderItems();
  renderAlerts();
  renderFocus();
  renderCorrelations();
}

function renderAlerts() {
  const ids = visibleIds();
  const cur = (analytics.alerts || []).filter((a) => ids.has(a.item_id));
  document.getElementById("alerts-current").innerHTML = cur.length
    ? `<table><thead><tr><th class="l">Item</th><th>Z</th><th>Mid</th><th>Time</th></tr></thead><tbody>${
        cur.map((a) => `<tr><td class="l"><a href="item.html?id=${a.item_id}">${esc(labels[a.item_id] || a.item_id)}</a>
          <span class="badge ${a.direction === "up" ? "ok" : "alert"}">${a.direction}</span></td>
          <td class="mono">${a.z.toFixed(2)}</td><td class="mono">${fmtPrice(a.mid)}</td><td class="mono muted">${a.t}</td></tr>`).join("")
      }</tbody></table>`
    : "No items currently beyond the z-threshold.";
  const hist = (analytics.alert_history || []).filter((a) => ids.has(a.item_id));
  document.querySelector("#alerts-history tbody").innerHTML = hist
    .map((a) => `<tr><td class="l"><a href="item.html?id=${a.item_id}">${esc(labels[a.item_id] || a.item_id)}</a></td>
      <td class="mono muted">${a.t}</td><td class="mono ${a.direction === "up" ? "pos" : "neg"}">${a.z.toFixed(2)}</td>
      <td class="mono">${fmtPrice(a.mid)}</td></tr>`)
    .join("");
}

function renderFocus() {
  const focus = activeFocus();
  const ids = visibleIds();
  document.getElementById("focus-hint").textContent =
    `mayor "${focus.mayor || "—"}" periods across the full calendar (weight ${events.minister_weight} when minister)`;
  const per = (focus.per_item || []).filter((p) => ids.has(p.item_id)).sort((a, b) => b.vol_ratio - a.vol_ratio);
  document.querySelector("#focus-table tbody").innerHTML = per
    .map((p) => `<tr><td class="l"><a href="item.html?id=${p.item_id}">${esc(p.label)}</a></td>
      <td class="mono ${p.vol_ratio > 1 ? "pos" : "neg"}">${p.vol_ratio.toFixed(2)}x</td>
      <td class="mono">${(p.abs_ret_active * 100).toFixed(2)}%</td>
      <td class="mono">${(p.abs_ret_base * 100).toFixed(2)}%</td>
      <td class="mono ${signClass(p.mean_ret_active)}">${fmtPct(p.mean_ret_active)}</td></tr>`)
    .join("");
  const day1 = (focus.day1_effects || []).filter((e) => ids.has(e.item_id)).sort((a, b) => (b.start || "").localeCompare(a.start || ""));
  document.querySelector("#day1-table tbody").innerHTML = day1
    .map((e) => `<tr><td class="mono muted">${e.start}</td><td class="mono">${e.year ?? "—"}</td>
      <td class="l">${esc(labels[e.item_id] || e.item_id)}</td>
      <td class="mono ${signClass(e.pct_24h)}">${fmtPct(e.pct_24h)}</td></tr>`)
    .join("");
}

function renderCorrelations() {
  const corr = analytics.correlations || {};
  const vis = visibleIds();
  document.querySelector("#pairs-table tbody").innerHTML = (corr.top_pairs || [])
    .filter((p) => vis.has(p.a) && vis.has(p.b))
    .map((p) => `<tr><td class="l"><a href="item.html?id=${p.a}">${esc(labels[p.a] || p.a)}</a></td>
      <td class="l"><a href="item.html?id=${p.b}">${esc(labels[p.b] || p.b)}</a></td>
      <td class="mono ${corrColor(p.corr) ? signClass(p.corr) : ""}">${p.corr.toFixed(3)}</td></tr>`)
    .join("");
  const sub = (corr.items || []).map((id, i) => [id, i]).filter(([id]) => vis.has(id));
  let html = "<thead><tr><th></th>" + sub.map(([id]) => `<th>${esc(labels[id] || id)}</th>`).join("") + "</tr></thead><tbody>";
  sub.forEach(([a, ai]) => {
    html += `<tr><th class="l">${esc(labels[a] || a)}</th>`;
    sub.forEach(([b, bi]) => {
      const v = corr.matrix[ai][bi];
      const diag = ai === bi;
      const txt = diag ? "1" : v === null ? "" : v.toFixed(2);
      html += `<td class="${diag ? "diag" : ""}" style="background:${diag ? "" : corrColor(v)}" title="${esc(labels[a])} × ${esc(labels[b])}: ${v}">${txt}</td>`;
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
applyMayor(activeMayor);
renderFooter();
["#items-table", "#alerts-history", "#focus-table", "#day1-table", "#pairs-table"].forEach((sel) => {
  const t = document.querySelector(sel);
  if (t) makeTableSortable(t);
});
