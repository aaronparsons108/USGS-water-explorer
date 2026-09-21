"use strict";

/* =============================================================================
   Explorer front end.

   The whole page is one form. Any change to it debounces into a single fetch
   that returns the table, both figures, and a description of what was computed.
   Nothing else talks to the server.

   Responsibilities, in order:
     1. serialize the sidebar and fetch /results
     2. hand both figures to Charts, which owns all Plotly styling
     3. render a sortable results table
     4. mirror the active filters as removable chips
     5. keep per-section filter counts and download links in sync
   ============================================================================= */

const U = window.EXPLORER_URLS;
const form = document.getElementById("filter-form");
const statusEl = document.getElementById("status");
const bannerEl = document.getElementById("banner");
const errorsEl = document.getElementById("form-errors");
const chipsEl = document.getElementById("chips");

const APPLY_DELAY_MS = 350;

let currentQuery = "";
let lastRows = [];
let lastColumns = [];
let sortState = { key: null, dir: 1 };
let inFlight = null;

/* ---------- small helpers -------------------------------------------------- */

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

/* Numbers in the table are formatted for scanning, not for precision: four
   significant-ish digits, thousands separators, exponent only when a plain
   decimal would be unreadable. */
function fmt(v) {
  if (v === null || v === undefined || v === "") return "n/a";
  if (typeof v === "number") {
    if (!Number.isFinite(v)) return "n/a";
    if (Number.isInteger(v)) return v.toLocaleString();
    const abs = Math.abs(v);
    if (abs !== 0 && (abs < 1e-3 || abs >= 1e5)) return v.toExponential(2);
    return v.toLocaleString(undefined, { maximumFractionDigits: 4 });
  }
  return String(v);
}

function buildQuery() {
  const params = new URLSearchParams();
  for (const [k, v] of new FormData(form).entries()) {
    if (v !== "" && v !== null) params.append(k, v);
  }
  return params.toString();
}

function setStatus(text, state) {
  statusEl.textContent = text;
  statusEl.dataset.state = state || "";
}

/* ---------- palette preview ------------------------------------------------ */
/* The gradient bar under the picker mirrors the chosen scale. "Auto" shows two
   halves, because the server then picks viridis for MI and plasma for values. */

(function palettePreview() {
  const select = document.getElementById("id_map_palette");
  const bar = document.getElementById("palette-preview");
  const node = document.getElementById("palette-gradients");
  if (!select || !bar || !node) return;
  const grads = JSON.parse(node.textContent);

  function sync() {
    const v = select.value || "auto";
    if (v === "auto") {
      bar.style.background = `${grads.viridis}, ${grads.plasma}`;
      bar.style.backgroundSize = "50% 100%, 50% 100%";
      bar.style.backgroundPosition = "left center, right center";
      bar.style.backgroundRepeat = "no-repeat, no-repeat";
      bar.title = "Viridis for mutual information, plasma for measured values";
    } else {
      bar.style.background = grads[v] || grads.viridis;
      bar.style.backgroundSize = "100% 100%";
      bar.title = select.options[select.selectedIndex].text;
    }
  }
  select.addEventListener("change", sync);
  sync();
})();

/* ---------- log-axis note -------------------------------------------------- */
/* Log only means something for medians, so say so the moment it stops applying
   rather than letting the checkbox look broken. */

(function logNote() {
  const note = document.getElementById("log-note");
  if (!note) return;
  const ids = ["id_scatter_x", "id_scatter_y"];
  const boxes = ["id_log_x", "id_log_y"];

  function sync() {
    let inert = false;
    ids.forEach((id, i) => {
      const axis = document.getElementById(id);
      const box = document.getElementById(boxes[i]);
      if (!axis || !box) return;
      const applies = String(axis.value).startsWith("median_");
      box.disabled = !applies;
      box.closest("label").classList.toggle("is-disabled", !applies);
      if (box.checked && !applies) inert = true;
    });
    note.hidden = !inert;
  }
  ids.concat(boxes).forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.addEventListener("change", sync);
  });
  sync();
})();

/* ---------- colour-scaling note -------------------------------------------- */
/* Log needs strictly positive values, so it is a no-op for MI and normalized
   MI. Say so the moment the combination stops meaning anything, rather than
   letting the control look broken. */

(function colorScaleNote() {
  const note = document.getElementById("scale-note");
  const scale = document.getElementById("id_color_scale");
  const mapColor = document.getElementById("id_map_color");
  const scatterColor = document.getElementById("id_scatter_color");
  if (!note || !scale) return;

  const canLog = (el) => !!el && String(el.value).startsWith("median_");

  function sync() {
    const asked = scale.value === "log";
    note.hidden = !(asked && !canLog(mapColor) && !canLog(scatterColor));
  }
  [scale, mapColor, scatterColor].forEach((el) => {
    if (el) el.addEventListener("change", sync);
  });
  sync();
})();

/* ---------- per-section filter counts -------------------------------------- */
/* Each collapsed section shows how many of its controls are currently doing
   something, so nothing hides silently behind a closed disclosure. */

const SECTION_FIELDS = {
  time: (name) => ["start_date", "end_date", "season", "month", "min_paired_days"].includes(name),
  location: (name) => ["regions", "huc2", "site_query"].includes(name),
  values: (name) => name.startsWith("median_"),
  mi: (name) => name.startsWith("mi_"),
  nmi: (name) => name.startsWith("nmi_"),
  counts: (name) => name.startsWith("n_g") || name.startsWith("n_paired_"),
};

function updateSectionCounts() {
  const active = {};
  for (const [k, v] of new FormData(form).entries()) {
    if (v === "" || v === null) continue;
    if (k === "min_paired_days" && String(v) === "30") continue;
    active[k] = (active[k] || 0) + 1;
  }
  document.querySelectorAll("[data-count-for]").forEach((el) => {
    const test = SECTION_FIELDS[el.dataset.countFor];
    if (!test) return;
    let n = 0;
    Object.keys(active).forEach((name) => {
      if (test(name)) n += active[name];
    });
    el.textContent = n;
    el.hidden = n === 0;
  });
}

/* ---------- rendering ------------------------------------------------------ */

function renderBanner(info) {
  const warns = info.warnings || [];
  bannerEl.hidden = warns.length === 0;
  bannerEl.innerHTML = warns.map((w) => `<div>${escapeHtml(w)}</div>`).join("");
}

function renderErrors(errors) {
  if (!errors) {
    errorsEl.hidden = true;
    errorsEl.innerHTML = "";
    return;
  }
  const items = [];
  Object.keys(errors).forEach((field) => {
    (errors[field] || []).forEach((msg) => items.push(escapeHtml(msg)));
  });
  errorsEl.hidden = items.length === 0;
  errorsEl.innerHTML = items.map((m) => `<div>${m}</div>`).join("");
}

function renderChips(chips) {
  if (!chips || !chips.length) {
    chipsEl.hidden = true;
    chipsEl.innerHTML = "";
    return;
  }
  chipsEl.hidden = false;
  chipsEl.innerHTML =
    chips
      .map(
        (c) =>
          `<button type="button" class="chip chip-removable" data-fields="${escapeHtml(
            c.fields.join("|")
          )}" title="Remove this filter">${escapeHtml(c.label)}<span aria-hidden="true">&times;</span></button>`
      )
      .join("") +
    `<button type="button" class="chip chip-clear" id="chip-clear-all">Clear all</button>`;
}

/* Removing a chip clears exactly the controls that produced it. A field named
   "regions:Midwest" means one checkbox inside a multi-value group. */
function clearFields(spec) {
  spec.split("|").forEach((field) => {
    if (field.includes(":")) {
      const [name, value] = field.split(":");
      form.querySelectorAll(`[name="${name}"]`).forEach((el) => {
        if (el.value === value) el.checked = false;
      });
      return;
    }
    const el = form.querySelector(`[name="${field}"]`);
    if (!el) return;
    if (el.type === "checkbox") el.checked = false;
    else if (field === "min_paired_days") el.value = "30";
    else el.value = "";
  });
}

chipsEl.addEventListener("click", (e) => {
  if (e.target.closest("#chip-clear-all")) {
    resetForm();
    return;
  }
  const chip = e.target.closest(".chip-removable");
  if (!chip) return;
  clearFields(chip.dataset.fields);
  scheduleLoad(0);
});

function sortRows(rows) {
  if (!sortState.key) return rows;
  const key = sortState.key;
  const dir = sortState.dir;
  return rows.slice().sort((a, b) => {
    const x = a[key];
    const y = b[key];
    const xMissing = x === null || x === undefined || x === "";
    const yMissing = y === null || y === undefined || y === "";
    // Missing values always sink, whichever way the column is sorted, so a
    // descending sort never opens with a block of blanks.
    if (xMissing && yMissing) return 0;
    if (xMissing) return 1;
    if (yMissing) return -1;
    if (typeof x === "number" && typeof y === "number") return (x - y) * dir;
    return String(x).localeCompare(String(y), undefined, { numeric: true }) * dir;
  });
}

function renderTable() {
  const thead = document.querySelector("#results-table thead");
  const tbody = document.querySelector("#results-table tbody");

  thead.innerHTML =
    "<tr>" +
    lastColumns
      .map((c) => {
        const active = sortState.key === c.key;
        const arrow = active ? (sortState.dir === 1 ? " ↑" : " ↓") : "";
        return `<th scope="col" class="${c.numeric ? "num" : "txt"}${
          active ? " sorted" : ""
        }" data-key="${escapeHtml(c.key)}" aria-sort="${
          active ? (sortState.dir === 1 ? "ascending" : "descending") : "none"
        }"><button type="button" class="th-btn">${escapeHtml(c.label)}${arrow}</button></th>`;
      })
      .join("") +
    "</tr>";

  if (!lastRows.length) {
    tbody.innerHTML = `<tr><td class="empty-cell" colspan="${lastColumns.length}">
      No sites match the current filters. Try widening the date range, clearing a
      region, or lowering a minimum observation count.</td></tr>`;
  } else {
    tbody.innerHTML = sortRows(lastRows)
      .map(
        (row) =>
          "<tr>" +
          lastColumns
            .map(
              (c) =>
                `<td class="${c.numeric ? "num" : "txt"}">${escapeHtml(fmt(row[c.key]))}</td>`
            )
            .join("") +
          "</tr>"
      )
      .join("");
  }
  document.getElementById("row-count").textContent = `(${lastRows.length.toLocaleString()})`;
}

document.querySelector("#results-table thead").addEventListener("click", (e) => {
  const th = e.target.closest("th[data-key]");
  if (!th) return;
  const key = th.dataset.key;
  sortState = { key, dir: sortState.key === key ? -sortState.dir : 1 };
  renderTable();
});

function updateDownloadLinks(query) {
  document.getElementById("dl-map").href = `${U.mapPng}?${query}`;
  document.getElementById("dl-scatter").href = `${U.scatterPng}?${query}`;
  document.getElementById("dl-csv").href = `${U.csv}?${query}`;
}

/* The figures no longer draw their own descriptive titles (that is what made
   the title collide with the legend), so the card header carries the
   description and the site count instead. */
function figureCaption(figure) {
  const layout = (figure && figure.layout) || {};
  // A figure that draws its own title (the map) must not have that same text
  // repeated in the card header; only an untitled figure needs the caption.
  const drawsItsOwn = !!(layout.title && layout.title.text);
  if (drawsItsOwn) return "";
  return (layout.meta && layout.meta.caption) || "";
}

function updateCaptions(info, data) {
  const shown = `${info.n_filtered.toLocaleString()} of ${info.n_total.toLocaleString()} sites`;
  const map = figureCaption(data.map);
  const sc = figureCaption(data.scatter);
  document.getElementById("map-caption").textContent = map ? `${map}  ::  ${shown}` : shown;
  document.getElementById("scatter-caption").textContent = sc ? `${sc}  ::  ${shown}` : shown;
}

/* ---------- fetch loop ----------------------------------------------------- */

/* Returns an error message if either figure failed to draw, else "". */
function drawCharts(data) {
  let message = "";
  [["map-div", data.map], ["scatter-div", data.scatter]].forEach(([divId, figure]) => {
    try {
      Charts.render(divId, figure);
    } catch (e) {
      message = message || String((e && e.message) || e);
      const el = document.getElementById(divId);
      if (el) {
        el.innerHTML =
          `<p class="plot-error">This figure could not be drawn.<br><code>${escapeHtml(
            String((e && e.message) || e)
          )}</code></p>`;
      }
      if (window.console) console.error(`Chart ${divId} failed:`, e);
    }
  });
  return message;
}

async function loadResults() {
  const query = buildQuery();
  currentQuery = query;
  updateSectionCounts();

  setStatus("Computing", "loading");
  Charts.setLoading("map-div", true);
  Charts.setLoading("scatter-div", true);

  // Only the newest request may write to the page; an older one that lands
  // late would otherwise overwrite fresher results.
  const token = {};
  inFlight = token;

  try {
    const resp = await fetch(`${U.results}?${query}`);
    if (inFlight !== token) return;

    if (!resp.ok) {
      const payload = await resp.json().catch(() => ({}));
      renderErrors(payload.errors || { form: ["Request failed."] });
      setStatus("Check the highlighted filters", "error");
      return;
    }

    const data = await resp.json();
    if (inFlight !== token) return;

    renderErrors(null);
    renderBanner(data.info);
    renderChips(data.info.active_filters);

    // The table is the source of truth and must survive a charting problem.
    // Drawing the figures inside their own guard means a Plotly failure costs
    // you the picture, not the numbers.
    const chartError = drawCharts(data);

    lastColumns = data.columns;
    lastRows = data.rows;
    renderTable();

    updateDownloadLinks(data.query || query);
    updateCaptions(data.info, data);

    if (chartError) {
      setStatus(`Charts could not be drawn: ${chartError}`, "error");
      return;
    }

    const parts = [
      `${data.info.n_filtered.toLocaleString()} of ${data.info.n_total.toLocaleString()} sites`,
      data.info.mode_label,
    ];
    if (data.info.months) parts.push(`months ${data.info.months.join(", ")}`);
    if (data.info.min_paired_days) {
      parts.push(`MI needs ${data.info.min_paired_days}+ paired days`);
    }
    setStatus(parts.join("  ::  "), "ok");
  } catch (e) {
    if (inFlight !== token) return;
    setStatus(`Request failed: ${e}`, "error");
  } finally {
    if (inFlight === token) {
      Charts.setLoading("map-div", false);
      Charts.setLoading("scatter-div", false);
    }
  }
}

let applyTimer = null;
function scheduleLoad(delay) {
  clearTimeout(applyTimer);
  applyTimer = setTimeout(loadResults, delay === undefined ? APPLY_DELAY_MS : delay);
}

/* Typing debounces; picking from a select or ticking a checkbox applies at
   once, because those are deliberate single actions. */
form.addEventListener("input", (e) => {
  if (e.target.type === "text" || e.target.type === "number" || e.target.type === "search") {
    scheduleLoad();
  }
});
form.addEventListener("change", (e) => {
  if (e.target.type === "text" || e.target.type === "number" || e.target.type === "search") return;
  scheduleLoad(0);
});
form.addEventListener("submit", (e) => {
  e.preventDefault();
  scheduleLoad(0);
});

function resetForm() {
  form.reset();
  // A native reset restores initial values without firing change events.
  setTimeout(() => {
    document.getElementById("id_map_palette").dispatchEvent(new Event("change"));
    sortState = { key: null, dir: 1 };
    loadResults();
  }, 0);
}

document.getElementById("reset-btn").addEventListener("click", resetForm);

document.querySelectorAll("[data-clear-group]").forEach((btn) => {
  btn.addEventListener("click", () => {
    form
      .querySelectorAll(`[name="${btn.dataset.clearGroup}"]`)
      .forEach((el) => (el.checked = false));
    scheduleLoad(0);
  });
});

loadResults();
