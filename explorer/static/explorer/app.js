"use strict";

const U = window.EXPLORER_URLS;
const form = document.getElementById("filter-form");
const statusEl = document.getElementById("status");
const bannerEl = document.getElementById("banner");

function currentQuery() {
  // Serialize the form, dropping empty values so the URL stays clean.
  const fd = new FormData(form);
  const params = new URLSearchParams();
  for (const [k, v] of fd.entries()) {
    if (v !== "" && v !== null) params.append(k, v);
  }
  // Checkboxes that are off are absent from FormData; that's fine for booleans.
  return params.toString();
}

function fmt(v, key) {
  if (v === null || v === undefined || v === "") return "";
  if (typeof v === "number") {
    if (Number.isInteger(v)) return v.toLocaleString();
    const abs = Math.abs(v);
    if (abs !== 0 && (abs < 1e-3 || abs >= 1e5)) return v.toExponential(2);
    return v.toLocaleString(undefined, { maximumFractionDigits: 4 });
  }
  return String(v);
}

function renderBanner(info) {
  const warns = (info.warnings || []);
  if (warns.length === 0) {
    bannerEl.hidden = true;
    bannerEl.innerHTML = "";
    return;
  }
  bannerEl.hidden = false;
  bannerEl.innerHTML = warns.map((w) => `<div>⚠️ ${w}</div>`).join("");
}

function renderTable(columns, rows) {
  const thead = document.querySelector("#results-table thead");
  const tbody = document.querySelector("#results-table tbody");
  thead.innerHTML = "<tr>" + columns.map((c) => `<th>${c.label}</th>`).join("") + "</tr>";
  const frag = rows
    .map((row) => {
      const tds = columns.map((c) => `<td>${fmt(row[c.key], c.key)}</td>`).join("");
      return `<tr>${tds}</tr>`;
    })
    .join("");
  tbody.innerHTML = frag;
  document.getElementById("row-count").textContent = `(${rows.length})`;
}

function renderPlots(data) {
  const cfg = { responsive: true, displaylogo: false };
  Plotly.react("map-div", data.map.data, data.map.layout, cfg);
  Plotly.react("scatter-div", data.scatter.data, data.scatter.layout, cfg);
}

function updateDownloadLinks(query) {
  document.getElementById("dl-map").href = `${U.mapPng}?${query}`;
  document.getElementById("dl-scatter").href = `${U.scatterPng}?${query}`;
  document.getElementById("dl-csv").href = `${U.csv}?${query}`;
}

async function loadResults() {
  const query = currentQuery();
  statusEl.textContent = "Computing…";
  statusEl.hidden = false;
  try {
    const resp = await fetch(`${U.results}?${query}`);
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      statusEl.textContent = "Error: " + (JSON.stringify(err.errors || err) || resp.status);
      return;
    }
    const data = await resp.json();
    renderBanner(data.info);
    renderPlots(data);
    renderTable(data.columns, data.rows);
    updateDownloadLinks(data.query || query);
    const i = data.info;
    statusEl.textContent =
      `${i.n_filtered} of ${i.n_total} sites · mode: ${i.mode}` +
      (i.months ? ` · months: ${i.months.join(",")}` : "");
  } catch (e) {
    statusEl.textContent = "Request failed: " + e;
  }
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  loadResults();
});

document.getElementById("reset-btn").addEventListener("click", () => {
  // Let the native reset clear fields first, then reload.
  setTimeout(loadResults, 0);
});

// Initial load with default (empty) filters.
loadResults();
