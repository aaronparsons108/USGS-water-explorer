"""Thread-based background jobs (no celery). The Job row is the source of truth:
the worker thread updates progress/message/log; wizard pages poll a JSON endpoint.
"""

from __future__ import annotations

import threading
import traceback

from django.db import close_old_connections
from django.utils import timezone

from . import builder, nwis_client
from .models import Dataset, Job


def dataset_has_running_job(dataset: Dataset) -> bool:
    return dataset.jobs.filter(status__in=[Job.STATUS_PENDING, Job.STATUS_RUNNING]).exists()


def start_job(dataset: Dataset, kind: str) -> Job:
    """Create a Job row and launch its worker thread. Caller checks for dupes."""
    job = Job.objects.create(dataset=dataset, kind=kind)
    t = threading.Thread(target=_run, args=(job.id,), daemon=True, name=f"job-{job.id}")
    t.start()
    return job


def _run(job_id: int) -> None:
    close_old_connections()
    job = Job.objects.get(id=job_id)
    dataset = job.dataset
    lines: list[str] = []

    def progress(frac: float, message: str) -> None:
        Job.objects.filter(id=job_id).update(
            status=Job.STATUS_RUNNING, progress=min(max(frac, 0.0), 1.0), message=message[:300]
        )

    def log(line: str) -> None:
        lines.append(line)
        Job.objects.filter(id=job_id).update(log="\n".join(lines[-400:]))

    Job.objects.filter(id=job_id).update(status=Job.STATUS_RUNNING)
    try:
        if job.kind == Job.KIND_DISCOVER:
            Dataset.objects.filter(id=dataset.id).update(status=Dataset.STATUS_DISCOVERING)
            res = nwis_client.discover_sites(dataset, progress=progress, log=log)
            Dataset.objects.filter(id=dataset.id).update(
                status=Dataset.STATUS_SITES_READY, error_message=""
            )
            msg = (
                f"Found {res['qualifying']} qualifying sites "
                f"({res['candidates']} candidates"
                + (f", {len(res['failed_states'])} states failed" if res["failed_states"] else "")
                + ")"
            )
        elif job.kind == Job.KIND_DOWNLOAD:
            Dataset.objects.filter(id=dataset.id).update(status=Dataset.STATUS_DOWNLOADING)
            res = nwis_client.download_dv(dataset, progress=progress, log=log)
            progress(0.99, "Building daily tables…")
            dataset.refresh_from_db()
            counts = builder.build_daily_tables(dataset, progress=None, log=log)
            # invalidate explorer caches for this dataset
            from explorer.core import cache as explorer_cache

            explorer_cache.clear_memo()
            Dataset.objects.filter(id=dataset.id).update(
                status=Dataset.STATUS_READY, error_message=""
            )
            built = ", ".join(f"{k}: {v['rows']} rows" for k, v in counts.items())
            msg = f"Downloaded {res['ok']} sites ({res['empty']} empty, {len(res['failed'])} failed). {built}"
        else:  # pragma: no cover
            raise ValueError(f"unknown job kind {job.kind}")

        Job.objects.filter(id=job_id).update(
            status=Job.STATUS_DONE, progress=1.0, message=msg[:300], finished_at=timezone.now()
        )
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        lines.append(traceback.format_exc(limit=6))
        Job.objects.filter(id=job_id).update(
            status=Job.STATUS_ERROR,
            message=err[:300],
            log="\n".join(lines[-400:]),
            finished_at=timezone.now(),
        )
        Dataset.objects.filter(id=dataset.id).update(
            status=Dataset.STATUS_ERROR, error_message=err[:500]
        )
    finally:
        close_old_connections()
