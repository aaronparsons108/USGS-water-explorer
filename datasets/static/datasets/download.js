"use strict";

/* Step 3: run the download and build job, then show the unit report. */

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
  `${B.n_selected} selected sites across ${B.n_codes} parameter codes ` +
  `(${B.codes.join(", ")}), ${B.start} to ${B.end}. Sites are fetched in small ` +
  `batches, so a large extraction can take a while.`;

function esc(s) {
  return String(s === null || s === undefined ? "" : s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function renderUnitReport(report) {
  if (!report || !report.length) return;
  els.unitBody.innerHTML = report
    .map(
      (r) => `<tr>
        <td>${esc(r.group)} ${esc(r.group_label)}</td>
        <td>${esc(r.code)}</td>
        <td class="action-${esc(r.action)}">${esc(r.action)}</td>
        <td>${esc(r.detail)}</td>
      </tr>`
    )
    .join("");
  els.unitPanel.hidden = false;
}

function markReady() {
  els.exploreLink.href = `/explorer/${B.slug}/`;
  els.readyPanel.hidden = false;
  els.btn.textContent = "Download again";
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
    onDone: (job) => {
      renderJobProgress(job, els.bar, els.msg, els.log);
      // The unit report lives on the dataset row; a reload is the simplest
      // way to pick it up along with the new status.
      window.location.reload();
    },
    onError: (job) => {
      renderJobProgress(job, els.bar, els.msg, els.log);
      showError(job.message || "Download failed. Check the log, then retry.");
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

/* On load: resume a running job, or show the result of a finished one. */
if (B.status === "downloading") {
  attachPolling();
} else if (B.status === "ready") {
  renderUnitReport(B.unit_report);
  markReady();
}
