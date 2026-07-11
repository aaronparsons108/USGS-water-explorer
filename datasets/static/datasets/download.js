"use strict";

/* Step 3: run the download+build job, then show the unit report and explore link. */

const B = JSON.parse(document.getElementById("bootstrap").textContent);

const els = {
  btn: document.getElementById("download-btn"),
  msg: document.getElementById("job-msg"),
  wrap: document.getElementById("progress-wrap"),
  bar: document.getElementById("progress-bar"),
  log: document.getElementById("job-log"),
  unitPanel: document.getElementById("unit-panel"),
  unitBody: document.querySelector("#unit-table tbody"),
  readyPanel: document.getElementById("ready-panel"),
  exploreLink: document.getElementById("explore-link"),
};

document.getElementById("scope-line").textContent =
  `${B.n_selected} selected sites × ${B.n_codes} parameter codes (${B.codes.join(", ")}), ${B.start} → ${B.end}. ` +
  `Sites are fetched in small batches — large extractions can take a while.`;

function renderUnitReport(report) {
  if (!report || !report.length) return;
  els.unitBody.innerHTML = report
    .map((r) => `<tr><td>${r.group} · ${r.group_label || ""}</td><td>${r.code}</td>
        <td class="action-${r.action}">${r.action}</td><td>${r.detail || ""}</td></tr>`)
    .join("");
  els.unitPanel.hidden = false;
}

function markReady() {
  els.exploreLink.href = `/explorer/${B.slug}/`;
  els.readyPanel.hidden = false;
  els.btn.textContent = "Re-download";
  els.btn.disabled = false;
}

function attachPolling() {
  els.wrap.hidden = false;
  els.log.hidden = false;
  els.btn.disabled = true;
  pollJob({
    datasetId: B.id,
    kind: "download",
    onTick: (job) => renderJobProgress(job, els.bar, els.msg, els.log),
    onDone: async (job) => {
      renderJobProgress(job, els.bar, els.msg, els.log);
      // unit report lives on the dataset; easiest refresh is a reload
      window.location.reload();
    },
    onError: (job) => {
      renderJobProgress(job, els.bar, els.msg, els.log);
      showError(job.message || "Download failed — check the log, then retry.");
      els.btn.disabled = false;
      els.btn.textContent = "Retry download";
    },
  });
}

els.btn.onclick = async () => {
  clearError();
  try {
    await postJSON(`/datasets/${B.id}/download/start/`);
    attachPolling();
  } catch (e) {
    showError(e.message);
  }
};

/* On load: resume, or show results for a ready dataset. */
if (B.status === "downloading") {
  attachPolling();
} else if (B.status === "ready") {
  renderUnitReport(B.unit_report);
  markReady();
}
