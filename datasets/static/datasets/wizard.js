"use strict";

/* Shared wizard helpers: CSRF-aware fetch, error surfacing, and job polling. */

function csrfToken() {
  const m = document.querySelector('meta[name="csrf"]');
  return m ? m.content : "";
}

async function postJSON(url, body) {
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
    body: body === undefined ? null : JSON.stringify(body),
  });
  let data = {};
  try {
    data = await resp.json();
  } catch (e) {
    /* non-JSON response, e.g. a redirect */
  }
  if (!resp.ok) throw new Error(data.error || `HTTP ${resp.status}`);
  return data;
}

async function getJSON(url) {
  const resp = await fetch(url);
  const data = await resp.json();
  if (!resp.ok) throw new Error(data.error || `HTTP ${resp.status}`);
  return data;
}

function showError(msg) {
  let box = document.getElementById("error-box");
  if (!box) {
    box = document.createElement("div");
    box.id = "error-box";
    box.className = "error-box";
    document.querySelector(".page").prepend(box);
  }
  box.textContent = msg;
  box.hidden = false;
  box.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function clearError() {
  const box = document.getElementById("error-box");
  if (box) box.hidden = true;
}

/*
 * Poll the dataset job endpoint every two seconds.
 * opts: {datasetId, kind, onTick(job, datasetStatus), onDone(job, status), onError(job)}
 * Returns a stop() function.
 */
function pollJob(opts) {
  let stopped = false;
  async function tick() {
    if (stopped) return;
    try {
      const data = await getJSON(`/datasets/${opts.datasetId}/job/?kind=${opts.kind}`);
      const job = data.job;
      if (opts.onTick) opts.onTick(job, data.dataset_status);
      if (job && job.status === "done") {
        stopped = true;
        if (opts.onDone) opts.onDone(job, data.dataset_status);
        return;
      }
      if (job && job.status === "error") {
        stopped = true;
        if (opts.onError) opts.onError(job);
        return;
      }
    } catch (e) {
      /* transient poll failure: keep going, the next tick usually recovers */
    }
    setTimeout(tick, 2000);
  }
  tick();
  return () => {
    stopped = true;
  };
}

function renderJobProgress(job, barEl, msgEl, logEl) {
  if (!job) return;
  if (barEl) barEl.style.width = `${Math.round((job.progress || 0) * 100)}%`;
  if (msgEl) msgEl.textContent = job.message || "";
  if (logEl && job.log_tail) {
    logEl.textContent = job.log_tail;
    logEl.scrollTop = logEl.scrollHeight;
  }
}
