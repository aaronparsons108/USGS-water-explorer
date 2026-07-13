"use strict";

/* Step 2: run discovery job, then render candidate sites (table + map) with selection. */

const B = JSON.parse(document.getElementById("bootstrap").textContent);
let sites = [];
let groups = B.groups;

const els = {
  btn: document.getElementById("discover-btn"),
  msg: document.getElementById("job-msg"),
  wrap: document.getElementById("progress-wrap"),
  bar: document.getElementById("progress-bar"),
  log: document.getElementById("job-log"),
  panel: document.getElementById("results-panel"),
  summary: document.getElementById("sites-summary"),
  filter: document.getElementById("site-filter"),
};

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
      if (job.message && job.message.includes("WARNING")) {
        showError(job.message);
      }
      loadSites();
    },
    onError: (job) => {
      renderJobProgress(job, els.bar, els.msg, els.log);
      showError(job.message || "Discovery failed — check the log, then retry.");
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

function covCell(s, pos) {
  const codes = s.coverage[String(pos)] || [];
  if (!codes.length) return "";
  const shown = codes[0] === "*" ? "✓" : codes.join(", ");
  return `<span class="cov-yes">✓</span> <span class="cov-codes">${shown === "✓" ? "" : shown}</span>`;
}

function renderTable() {
  const thead = document.querySelector("#sites-table thead");
  const tbody = document.querySelector("#sites-table tbody");
  const gcols = groups.map((g) => `<th>${g.label}</th>`).join("");
  thead.innerHTML = `<tr><th><input type="checkbox" id="head-check"></th>
    <th>Site #</th><th>Station</th><th>State</th>${gcols}<th>From</th><th>To</th><th># obs</th></tr>`;
  const q = (els.filter.value || "").toLowerCase();
  tbody.innerHTML = sites
    .filter((s) => !q || s.site_no.toLowerCase().includes(q) || (s.station_nm || "").toLowerCase().includes(q) || (s.state || "").toLowerCase().includes(q))
    .map((s) => {
      const g = groups.map((gr) => `<td>${covCell(s, gr.position)}</td>`).join("");
      return `<tr>
        <td><input type="checkbox" class="row-check" data-site="${s.site_no}" ${s.selected ? "checked" : ""}></td>
        <td>${s.site_no}</td><td>${s.station_nm || ""}</td><td>${s.state || ""}</td>${g}
        <td>${s.begin || ""}</td><td>${s.end || ""}</td><td>${(s.count || 0).toLocaleString()}</td></tr>`;
    })
    .join("");
  const n = sites.filter((s) => s.selected).length;
  els.summary.textContent = `— ${sites.length} sites qualify; ${n} selected`;
  const head = document.getElementById("head-check");
  if (head) head.onchange = () => { setAll(head.checked); };
}

function renderMap() {
  const sel = sites.filter((s) => s.lat != null && s.lon != null);
  const trace = {
    type: "scattergeo",
    lat: sel.map((s) => s.lat),
    lon: sel.map((s) => s.lon),
    text: sel.map((s) => `${s.site_no} ${s.station_nm || ""}`),
    hoverinfo: "text",
    marker: {
      size: 7,
      color: sel.map((s) => (s.selected ? "#1f6feb" : "#c2c9d1")),
      line: { width: 0.5, color: "black" },
    },
  };
  Plotly.react("sites-map", [trace], {
    geo: { scope: "usa", showland: true, landcolor: "#eef0f2", subunitcolor: "#9aa3ad" },
    margin: { l: 0, r: 0, t: 0, b: 0 },
  }, { responsive: true, displaylogo: false });
}

function setAll(checked) {
  sites.forEach((s) => (s.selected = checked));
  renderTable();
  renderMap();
}

document.getElementById("sel-all").onclick = () => setAll(true);
document.getElementById("sel-none").onclick = () => setAll(false);
els.filter.addEventListener("input", renderTable);

document.addEventListener("change", (e) => {
  if (e.target.classList && e.target.classList.contains("row-check")) {
    const s = sites.find((x) => x.site_no === e.target.dataset.site);
    if (s) s.selected = e.target.checked;
    renderTable();
    renderMap();
  }
});

document.getElementById("continue-btn").onclick = async () => {
  clearError();
  const selected = sites.filter((s) => s.selected).map((s) => s.site_no);
  try {
    await postJSON(`/datasets/${B.id}/sites/save/`, { selected });
    window.location.href = `/datasets/${B.id}/download/`;
  } catch (e) {
    showError(e.message);
  }
};

async function loadSites() {
  const data = await getJSON(`/datasets/${B.id}/sites/data/`);
  groups = data.groups;
  sites = data.sites;
  if (sites.length) {
    els.panel.hidden = false;
    renderTable();
    renderMap();
  }
}

/* On load: resume a running job, or show existing results. */
if (B.status === "discovering") {
  attachPolling();
} else if (B.n_sites > 0) {
  els.btn.textContent = "Re-run discovery";
  loadSites();
}
