"use strict";

/* Step 1: dataset setup — groups builder with parameter-code picker. */

const B = JSON.parse(document.getElementById("bootstrap").textContent);
let groups = B.groups.map((g) => ({ label: g.label, pmcodes: [...g.pmcodes] }));
while (groups.length < B.min_groups) groups.push({ label: `Group ${groups.length + 1}`, pmcodes: [] });

/* --- basic fields --- */
document.getElementById("ds-name").value = B.name;
document.getElementById("ds-start").value = B.start_date;
document.getElementById("ds-end").value = B.end_date;
document.getElementById("ds-mincount").value = B.min_count_per_series;
document.getElementById("ds-wells").checked = B.exclude_wells;

/* --- services --- */
const servicesDiv = document.getElementById("services");
for (const [code, label] of B.services_choices) {
  const l = document.createElement("label");
  l.innerHTML = `<input type="checkbox" value="${code}" ${B.services.includes(code) ? "checked" : ""}> ${label}`;
  servicesDiv.appendChild(l);
}

/* --- states --- */
const statesDiv = document.getElementById("states");
for (const st of B.all_states) {
  const l = document.createElement("label");
  l.innerHTML = `<input type="checkbox" value="${st}" ${B.states.includes(st) ? "checked" : ""}> ${st}`;
  statesDiv.appendChild(l);
}
function stateBoxes() { return [...statesDiv.querySelectorAll("input")]; }
function updateStatesCount() {
  const n = stateBoxes().filter((b) => b.checked).length;
  document.getElementById("states-count").textContent =
    n === 0 ? "none selected — pick at least one" : `${n} selected`;
}
statesDiv.addEventListener("change", updateStatesCount);
document.getElementById("states-conus").onclick = () => {
  stateBoxes().forEach((b) => (b.checked = B.conus_states.includes(b.value)));
  updateStatesCount();
};
document.getElementById("states-none").onclick = () => {
  stateBoxes().forEach((b) => (b.checked = false));
  updateStatesCount();
};
updateStatesCount();

/* --- groups builder --- */
const groupsDiv = document.getElementById("groups");

function chipHTML(p, gi, pi) {
  const unit = p.unit ? `<span class="unit">${p.unit}</span>` : "";
  return `<span class="chip"><strong>${p.code}</strong> ${p.name || ""} ${unit}
    <button type="button" data-g="${gi}" data-p="${pi}" title="remove">×</button></span>`;
}

function renderGroups() {
  groupsDiv.innerHTML = "";
  groups.forEach((g, gi) => {
    const box = document.createElement("div");
    box.className = "group-box";
    box.innerHTML = `
      <div class="group-head">
        <strong>Group ${gi + 1}</strong>
        <input type="text" value="${g.label.replace(/"/g, "&quot;")}" data-g="${gi}" class="g-label" placeholder="Label (e.g. Nitrate/Nitrite)">
        ${groups.length > B.min_groups ? `<button type="button" class="btn danger g-remove" data-g="${gi}">Remove</button>` : ""}
      </div>
      <div class="g-chips">${g.pmcodes.map((p, pi) => chipHTML(p, gi, pi)).join("") || '<span class="note">No parameter codes yet.</span>'}</div>
      <div class="pm-search">
        <input type="text" class="pm-input" data-g="${gi}" placeholder="Search parameter codes (e.g. 00060 or nitrate)…" autocomplete="off">
        <div class="pm-results" hidden></div>
      </div>`;
    groupsDiv.appendChild(box);
  });
}

groupsDiv.addEventListener("input", (e) => {
  if (e.target.classList.contains("g-label")) {
    groups[+e.target.dataset.g].label = e.target.value;
  }
  if (e.target.classList.contains("pm-input")) {
    searchPmcodes(e.target);
  }
});

groupsDiv.addEventListener("click", (e) => {
  const chipBtn = e.target.closest(".chip button");
  if (chipBtn) {
    groups[+chipBtn.dataset.g].pmcodes.splice(+chipBtn.dataset.p, 1);
    renderGroups();
    return;
  }
  const rm = e.target.closest(".g-remove");
  if (rm) {
    groups.splice(+rm.dataset.g, 1);
    renderGroups();
  }
});

let searchTimer = null;
function searchPmcodes(input) {
  clearTimeout(searchTimer);
  const resultsDiv = input.parentElement.querySelector(".pm-results");
  const q = input.value.trim();
  if (q.length < 2) { resultsDiv.hidden = true; return; }
  searchTimer = setTimeout(async () => {
    try {
      const data = await getJSON(`/datasets/pmcode-search/?q=${encodeURIComponent(q)}`);
      const gi = +input.dataset.g;
      const have = new Set(groups[gi].pmcodes.map((p) => p.code));
      resultsDiv.innerHTML = data.results
        .filter((r) => !have.has(r.code))
        .map((r) => `<div data-code="${r.code}" data-name="${(r.name || "").replace(/"/g, "&quot;")}" data-unit="${(r.unit || "").replace(/"/g, "&quot;")}">
              <span class="code">${r.code}</span> ${r.name} <span class="unit">(${r.unit || "no unit"})</span><br>
              <span class="unit">${r.description || ""}</span></div>`)
        .join("") || '<div class="note" style="padding:8px;">No matches.</div>';
      resultsDiv.hidden = false;
      resultsDiv.onclick = (ev) => {
        const d = ev.target.closest("div[data-code]");
        if (!d) return;
        groups[gi].pmcodes.push({ code: d.dataset.code, name: d.dataset.name, unit: d.dataset.unit });
        renderGroups();
      };
    } catch (err) {
      resultsDiv.innerHTML = `<div class="note" style="padding:8px;">Search failed: ${err.message}</div>`;
      resultsDiv.hidden = false;
    }
  }, 250);
}

document.addEventListener("click", (e) => {
  if (!e.target.closest(".pm-search")) {
    document.querySelectorAll(".pm-results").forEach((d) => (d.hidden = true));
  }
});

document.getElementById("add-group").onclick = () => {
  if (groups.length >= B.max_groups) { showError(`Maximum ${B.max_groups} groups.`); return; }
  clearError();
  groups.push({ label: `Group ${groups.length + 1}`, pmcodes: [] });
  renderGroups();
};

document.getElementById("load-example").onclick = async () => {
  clearError();
  const filled = [];
  for (const eg of B.example_groups) {
    // resolve names/units through the search endpoint (exact code lookups)
    const pmcodes = [];
    for (const code of eg.codes) {
      try {
        const data = await getJSON(`/datasets/pmcode-search/?q=${code}`);
        const hit = data.results.find((r) => r.code === code.padStart(5, "0"));
        pmcodes.push(hit || { code, name: "", unit: "" });
      } catch { pmcodes.push({ code, name: "", unit: "" }); }
    }
    filled.push({ label: eg.label, pmcodes });
  }
  groups = filled;
  renderGroups();
};

renderGroups();

/* --- save --- */
document.getElementById("save-btn").onclick = async () => {
  clearError();
  const states = stateBoxes().filter((b) => b.checked).map((b) => b.value);
  if (states.length === 0) { showError("Pick at least one state (or All CONUS)."); return; }
  const services = [...servicesDiv.querySelectorAll("input")].filter((b) => b.checked).map((b) => b.value);
  const payload = {
    name: document.getElementById("ds-name").value,
    start_date: document.getElementById("ds-start").value,
    end_date: document.getElementById("ds-end").value,
    min_count_per_series: +document.getElementById("ds-mincount").value || 1,
    exclude_wells: document.getElementById("ds-wells").checked,
    states, services, groups,
  };
  const btn = document.getElementById("save-btn");
  btn.disabled = true;
  try {
    await postJSON(`/datasets/${B.id}/setup/save/`, payload);
    window.location.href = `/datasets/${B.id}/sites/`;
  } catch (e) {
    showError(e.message);
    btn.disabled = false;
  }
};
