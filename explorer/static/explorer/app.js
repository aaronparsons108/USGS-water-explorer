"use strict";

const U = window.EXPLORER_URLS;
const form = document.getElementById("filter-form");
const statusEl = document.getElementById("status");
const bannerEl = document.getElementById("banner");

function buildQuery() {
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
  // Make the SCATTER PLOT AREA square (not just the container): give both axes
  // the same paper-domain span inside the square container, and dock the legend
  // in the reserved right strip so it doesn't squeeze the plot.
  const L = data.scatter.layout || {};
  const sq = Object.assign({}, L, {
    autosize: true,
    title: { text: "" }, // long title was clipped; the axes + card header describe it
    // autoexpand:false keeps the paper (and thus the equal-domain plot area) square;
    // symmetric margins leave room for labels/legend in the domain gutters.
    margin: { l: 8, r: 8, t: 8, b: 8, pad: 0, autoexpand: false },
    xaxis: Object.assign({}, L.xaxis, { domain: [0.14, 0.86], automargin: false }),
    yaxis: Object.assign({}, L.yaxis, { domain: [0.14, 0.86], automargin: false }),
    legend: Object.assign({}, L.legend, { x: 0.88, xanchor: "left", y: 0.5, yanchor: "middle" }),
  });
  Plotly.react("scatter-div", data.scatter.data, sq, cfg);
  Plotly.Plots.resize("scatter-div");
}

function updateDownloadLinks(query) {
  document.getElementById("dl-map").href = `${U.mapPng}?${query}`;
  document.getElementById("dl-scatter").href = `${U.scatterPng}?${query}`;
  document.getElementById("dl-csv").href = `${U.csv}?${query}`;
  document.getElementById("dl-research-map").href = `${U.researchMap}?${query}&download=1`;
  document.getElementById("dl-research-scatter").href = `${U.researchScatter}?${query}&download=1`;
}

// --- Publication (research-style matplotlib) tab: load lazily on demand ---
let currentQuery = "";
let pubLoadedQuery = null;

function activePanel() {
  const t = document.querySelector(".tab.active");
  return t ? t.dataset.tab : "interactive";
}

function loadResearchImages() {
  if (pubLoadedQuery === currentQuery) return;
  pubLoadedQuery = currentQuery;
  const map = document.getElementById("research-map-img");
  const sc = document.getElementById("research-scatter-img");
  for (const [img, url] of [[map, U.researchMap], [sc, U.researchScatter]]) {
    img.classList.add("loading");
    img.onload = img.onerror = () => img.classList.remove("loading");
    img.src = `${url}?${currentQuery}`;
  }
}

function maybeLoadResearch() {
  if (activePanel() === "publication") loadResearchImages();
}

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t === tab));
    document.querySelectorAll(".tab-panel").forEach((p) => {
      p.hidden = p.dataset.panel !== tab.dataset.tab;
    });
    if (tab.dataset.tab === "interactive") {
      Plotly.Plots.resize("map-div");
      Plotly.Plots.resize("scatter-div");
    } else {
      loadResearchImages();
    }
  });
});

async function loadResults() {
  const query = buildQuery();
  currentQuery = query;
  pubLoadedQuery = null; // filters changed -> research images are stale
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
    maybeLoadResearch();
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
