"use strict";

/* =============================================================================
   Step 2: run the discovery job, then review candidate sites.

   The filter bar narrows what is shown; the selection buttons act on exactly
   what is shown. That pairing is the point: on a CONUS run this table holds
   hundreds of rows, and picking a working set one slice at a time (this basin,
   these long records) is far more workable than scrolling and ticking.

   Filtering never changes selection on its own, so a site you selected stays
   selected even after it scrolls out of the current filter.
   ============================================================================= */

const B = JSON.parse(document.getElementById("bootstrap").textContent);
let sites = [];
let groups = B.groups;
let sortState = { key: "site_no", dir: 1 };

const els = {
  btn: document.getElementById("discover-btn"),
  msg: document.getElementById("job-msg"),
  wrap: document.getElementById("progress-wrap"),
  bar: document.getElementById("progress-bar"),
  log: document.getElementById("job-log"),
  panel: document.getElementById("results-panel"),
  summary: document.getElementById("sites-summary"),
  thead: document.querySelector("#sites-table thead"),
  tbody: document.querySelector("#sites-table tbody"),
};

const filters = {
  search: document.getElementById("f-search"),
  state: document.getElementById("f-state"),
  huc2: document.getElementById("f-huc2"),
  mincount: document.getElementById("f-mincount"),
  begin: document.getElementById("f-begin"),
  end: document.getElementById("f-end"),
  selectedOnly: document.getElementById("f-selected-only"),
};

/* ---------- discovery job -------------------------------------------------- */

function attachPolling() {
  els.wrap.hidden = false;
  els.log.hidden = false;
  els.btn.disabled = true;
  pollJob({
    datasetId: B.id,
    kind: "discover",
    onTick: (job) => renderJobProgress(job, els.bar, els.msg, els.log),
    onDone: (job) => {
      renderJobProgress(job, els.bar, els.msg, els.log);
      els.btn.disabled = false;
      els.btn.textContent = "Re-run discovery";
      if (job.message && job.message.includes("WARNING")) showError(job.message);
      loadSites();
    },
    onError: (job) => {
      renderJobProgress(job, els.bar, els.msg, els.log);
      showError(job.message || "Discovery failed. Check the log, then retry.");
      els.btn.disabled = false;
      els.btn.textContent = "Retry discovery";
    },
  });
}

els.btn.onclick = async () => {
  clearError();
  try {
    await postJSON(`/datasets/${B.id}/discover/`);
    attachPolling();
  } catch (e) {
    showError(e.message);
  }
};

/* ---------- filtering ------------------------------------------------------ */

function visibleSites() {
  const q = (filters.search.value || "").trim().toLowerCase();
  const state = filters.state.value;
  const huc2 = filters.huc2.value;
  const minCount = parseInt(filters.mincount.value, 10);
  const begin = filters.begin.value;
  const end = filters.end.value;
  const selectedOnly = filters.selectedOnly.checked;

  return sites.filter((s) => {
    if (selectedOnly && !s.selected) return false;
    if (state && s.state !== state) return false;
    if (huc2 && s.huc2 !== huc2) return false;
    if (Number.isFinite(minCount) && (s.count || 0) < minCount) return false;
    // "Data starts on or before X" keeps records that already existed at X.
    if (begin && (!s.begin || s.begin > begin)) return false;
    // "Data ends on or after X" keeps records still running at X.
    if (end && (!s.end || s.end < end)) return false;
    if (q) {
      const hay = `${s.site_no} ${s.station_nm || ""} ${s.state || ""}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
}

function populateFilterOptions() {
  const states = [...new Set(sites.map((s) => s.state).filter(Boolean))].sort();
  const hucs = [...new Set(sites.map((s) => s.huc2).filter(Boolean))].sort();
  fillSelect(filters.state, states, "Any state");
  fillSelect(filters.huc2, hucs, "Any basin");
}

function fillSelect(select, values, placeholder) {
  const keep = select.value;
  select.innerHTML =
    `<option value="">${placeholder}</option>` +
    values.map((v) => `<option value="${v}">${v}</option>`).join("");
  if (values.includes(keep)) select.value = keep;
}

Object.values(filters).forEach((el) => {
  el.addEventListener(el.tagName === "SELECT" || el.type === "checkbox" ? "change" : "input", render);
});

document.getElementById("f-clear").onclick = () => {
  filters.search.value = "";
  filters.state.value = "";
  filters.huc2.value = "";
  filters.mincount.value = "";
  filters.begin.value = "";
  filters.end.value = "";
  filters.selectedOnly.checked = false;
  render();
};

/* ---------- table ---------------------------------------------------------- */

function covCell(s, pos) {
  const codes = s.coverage[String(pos)] || [];
  if (!codes.length) return '<span class="cov-no">no</span>';
  const shown = codes[0] === "*" ? "" : codes.join(", ");
  return `<span class="cov-yes">yes</span> <span class="cov-codes">${shown}</span>`;
}

function sortSites(rows) {
  const { key, dir } = sortState;
  return rows.slice().sort((a, b) => {
    const x = a[key];
    const y = b[key];
    if (x === y) return 0;
    if (x === null || x === undefined || x === "") return 1;
    if (y === null || y === undefined || y === "") return -1;
    if (typeof x === "number" && typeof y === "number") return (x - y) * dir;
    return String(x).localeCompare(String(y), undefined, { numeric: true }) * dir;
  });
}

const COLUMNS = [
  { key: "site_no", label: "Site #" },
  { key: "station_nm", label: "Station" },
  { key: "state", label: "State" },
  { key: "huc2", label: "HUC2" },
  { key: "begin", label: "From" },
  { key: "end", label: "To" },
  { key: "count", label: "Observations", numeric: true },
];

function renderTable(shown) {
  // Header order: identity columns, then one coverage column per parameter
  // group, then the record extent and observation count.
  const gcols = groups.map((g) => `<th>${escapeAttr(g.label)}</th>`).join("");
  const beforeGroups = COLUMNS.slice(0, 4);
  const afterGroups = COLUMNS.slice(4);
  const th = (c) => {
    const active = sortState.key === c.key;
    const arrow = active ? (sortState.dir === 1 ? " ↑" : " ↓") : "";
    return `<th class="${c.numeric ? "num" : ""}${active ? " sorted" : ""}" data-key="${c.key}"><button type="button" class="th-btn">${c.label}${arrow}</button></th>`;
  };
  els.thead.innerHTML =
    `<tr><th><input type="checkbox" id="head-check" title="Select or clear everything shown"></th>` +
    beforeGroups.map(th).join("") +
    gcols +
    afterGroups.map(th).join("") +
    `</tr>`;

  if (!shown.length) {
    els.tbody.innerHTML = `<tr><td class="empty-cell" colspan="${COLUMNS.length + groups.length + 1}">
      No sites match these filters.</td></tr>`;
  } else {
    els.tbody.innerHTML = sortSites(shown)
      .map((s) => {
        const cov = groups.map((g) => `<td>${covCell(s, g.position)}</td>`).join("");
        return `<tr>
          <td><input type="checkbox" class="row-check" data-site="${escapeAttr(s.site_no)}" ${s.selected ? "checked" : ""}></td>
          <td>${escapeAttr(s.site_no)}</td>
          <td>${escapeAttr(s.station_nm || "")}</td>
          <td>${escapeAttr(s.state || "")}</td>
          <td>${escapeAttr(s.huc2 || "")}</td>
          ${cov}
          <td>${escapeAttr(s.begin || "")}</td>
          <td>${escapeAttr(s.end || "")}</td>
          <td class="num">${(s.count || 0).toLocaleString()}</td>
        </tr>`;
      })
      .join("");
  }

  const head2 = document.getElementById("head-check");
  if (head2) {
    const allShown = shown.length > 0 && shown.every((s) => s.selected);
    head2.checked = allShown;
    head2.indeterminate = !allShown && shown.some((s) => s.selected);
    head2.onchange = () => setShown(head2.checked);
  }
}

function escapeAttr(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

els.thead.addEventListener("click", (e) => {
  const th = e.target.closest("th[data-key]");
  if (!th) return;
  const key = th.dataset.key;
  sortState = { key, dir: sortState.key === key ? -sortState.dir : 1 };
  render();
});

/* ---------- map ------------------------------------------------------------ */

function renderMap(shown) {
  const shownIds = new Set(shown.map((s) => s.site_no));
  const withCoords = sites.filter((s) => s.lat != null && s.lon != null);
  const p = window.Charts ? Charts.palette() : { muted: "#8a93a0" };

  // Three states, so the map answers "what did my filter do?" at a glance:
  // selected and shown, shown but unselected, filtered out entirely.
  const buckets = [
    { name: "Selected", color: "#1f6feb", size: 8, test: (s) => shownIds.has(s.site_no) && s.selected },
    { name: "Not selected", color: "#c2c9d1", size: 7, test: (s) => shownIds.has(s.site_no) && !s.selected },
    { name: "Filtered out", color: "rgba(150,158,168,0.28)", size: 5, test: (s) => !shownIds.has(s.site_no) },
  ];

  const traces = buckets
    .map((b) => {
      const sel = withCoords.filter(b.test);
      return {
        type: "scattergeo",
        name: `${b.name} (${sel.length})`,
        lat: sel.map((s) => s.lat),
        lon: sel.map((s) => s.lon),
        text: sel.map((s) => `${s.site_no} ${s.station_nm || ""}`),
        hoverinfo: "text",
        marker: { size: b.size, color: b.color, line: { width: 0.5, color: "rgba(0,0,0,0.5)" } },
      };
    })
    .filter((t) => t.lat.length);

  const layout = {
    geo: { scope: "usa", showland: true, showlakes: true, showsubunits: true, showframe: false },
    margin: { l: 0, r: 0, t: 8, b: 0 },
    height: 320,
    font: { family: "Inter, system-ui, sans-serif", size: 12 },
    legend: { orientation: "h", y: 1.04, x: 0, font: { color: p.muted } },
    paper_bgcolor: "rgba(0,0,0,0)",
  };

  if (window.Charts) {
    Charts.render("sites-map", { data: traces, layout });
  } else {
    Plotly.react("sites-map", traces, layout, { responsive: true, displaylogo: false });
  }
}

/* ---------- selection ------------------------------------------------------ */

function setShown(checked) {
  const ids = new Set(visibleSites().map((s) => s.site_no));
  sites.forEach((s) => {
    if (ids.has(s.site_no)) s.selected = checked;
  });
  render();
}

document.getElementById("sel-all").onclick = () => setShown(true);
document.getElementById("sel-none").onclick = () => setShown(false);
document.getElementById("sel-only").onclick = () => {
  const ids = new Set(visibleSites().map((s) => s.site_no));
  sites.forEach((s) => (s.selected = ids.has(s.site_no)));
  render();
};

els.tbody.addEventListener("change", (e) => {
  if (!e.target.classList.contains("row-check")) return;
  const s = sites.find((x) => x.site_no === e.target.dataset.site);
  if (s) s.selected = e.target.checked;
  render();
});

document.getElementById("continue-btn").onclick = async () => {
  clearError();
  const selected = sites.filter((s) => s.selected).map((s) => s.site_no);
  if (!selected.length) {
    showError("Select at least one site before continuing.");
    return;
  }
  try {
    await postJSON(`/datasets/${B.id}/sites/save/`, { selected });
    window.location.href = `/datasets/${B.id}/download/`;
  } catch (e) {
    showError(e.message);
  }
};

/* ---------- render loop ---------------------------------------------------- */

function render() {
  const shown = visibleSites();
  const nSelected = sites.filter((s) => s.selected).length;
  const nSelectedShown = shown.filter((s) => s.selected).length;

  els.summary.innerHTML =
    `Showing <strong>${shown.length.toLocaleString()}</strong> of ` +
    `${sites.length.toLocaleString()} qualifying sites &middot; ` +
    `<strong>${nSelected.toLocaleString()}</strong> selected overall ` +
    `(${nSelectedShown.toLocaleString()} of those are shown)`;

  renderTable(shown);
  renderMap(shown);
}

async function loadSites() {
  const data = await getJSON(`/datasets/${B.id}/sites/data/`);
  groups = data.groups;
  sites = data.sites;
  if (sites.length) {
    els.panel.hidden = false;
    populateFilterOptions();
    render();
  }
}

document.addEventListener("themechange", () => {
  if (sites.length) renderMap(visibleSites());
});

/* On load: resume a running job, or show whatever was already discovered. */
if (B.status === "discovering") {
  attachPolling();
} else if (B.n_sites > 0) {
  els.btn.textContent = "Re-run discovery";
  loadSites();
}
