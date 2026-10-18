const DATA = "data";

export async function loadJSON(name) {
  const res = await fetch(`${DATA}/${name}`);
  if (!res.ok) throw new Error(`failed to load ${name}: ${res.status}`);
  return res.json();
}

export function fmtPrice(v) {
  if (v === null || v === undefined) return "—";
  const a = Math.abs(v);
  if (a >= 1e9) return (v / 1e9).toFixed(2) + "b";
  if (a >= 1e6) return (v / 1e6).toFixed(2) + "m";
  if (a >= 1e3) return (v / 1e3).toFixed(2) + "k";
  if (a >= 1) return v.toFixed(1);
  return v.toFixed(2);
}

export function fmtPct(v, digits = 2) {
  if (v === null || v === undefined) return "—";
  const p = v * 100;
  const s = p >= 0 ? "+" : "";
  return `${s}${p.toFixed(digits)}%`;
}

export function fmtNum(v, digits = 0) {
  if (v === null || v === undefined) return "—";
  return v.toLocaleString(undefined, { maximumFractionDigits: digits });
}

export function signClass(v) {
  if (v === null || v === undefined) return "muted";
  return v > 0 ? "pos" : v < 0 ? "neg" : "muted";
}

export function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

export function corrColor(v) {
  if (v === null || v === undefined) return "transparent";
  const a = Math.min(Math.abs(v), 1);
  const alpha = (0.08 + a * 0.55).toFixed(3);
  return v >= 0 ? `rgba(53, 208, 127, ${alpha})` : `rgba(255, 95, 109, ${alpha})`;
}

export function baseChartOptions() {
  return {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: "index", intersect: false },
    animation: false,
    plugins: {
      legend: { labels: { color: "#8b93a7", boxWidth: 12, font: { size: 11 } } },
      tooltip: {
        backgroundColor: "#1c2130",
        borderColor: "#242a38",
        borderWidth: 1,
        titleColor: "#e7eaf2",
        bodyColor: "#e7eaf2",
      },
    },
    scales: {
      x: {
        ticks: { color: "#8b93a7", maxTicksLimit: 8, maxRotation: 0, font: { size: 10 } },
        grid: { color: "rgba(36, 42, 56, .5)" },
      },
      y: {
        ticks: { color: "#8b93a7", font: { size: 10 } },
        grid: { color: "rgba(36, 42, 56, .5)" },
      },
    },
  };
}

export function makeTableSortable(table) {
  const ths = table.querySelectorAll("th");
  ths.forEach((th, idx) => {
    th.addEventListener("click", () => {
      const tbody = table.querySelector("tbody");
      const rows = Array.from(tbody.querySelectorAll("tr"));
      const dir = th.dataset.dir === "asc" ? -1 : 1;
      ths.forEach((t) => delete t.dataset.dir);
      th.dataset.dir = dir === 1 ? "asc" : "desc";
      const val = (tr) => {
        const td = tr.children[idx];
        const raw = td.dataset.sort !== undefined ? td.dataset.sort : td.textContent;
        const num = parseFloat(String(raw).replace(/,/g, "").replace(/[%]/g, ""));
        return Number.isNaN(num) ? String(raw).toLowerCase() : num;
      };
      rows.sort((a, b) => {
        const va = val(a);
        const vb = val(b);
        if (va < vb) return -1 * dir;
        if (va > vb) return 1 * dir;
        return 0;
      });
      rows.forEach((r) => tbody.appendChild(r));
    });
  });
}

export function sparkline(el, values, color) {
  if (!values || values.length < 2) return;
  new Chart(el, {
    type: "line",
    data: {
      labels: values.map((_, i) => i),
      datasets: [{ data: values, borderColor: color, borderWidth: 1.5, pointRadius: 0, tension: 0.25 }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      plugins: { legend: { display: false }, tooltip: { enabled: false } },
      scales: { x: { display: false }, y: { display: false } },
    },
  });
}

export function monthSpan(times) {
  if (!times.length) return "—";
  return `${times[0].slice(0, 10)} → ${times[times.length - 1].slice(0, 10)}`;
}
