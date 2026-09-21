"""Thread-based background jobs, no external queue.

The Job row is the source of truth: the worker thread updates
progress/message/log, and the wizard pages poll a JSON endpoint. Only one job
may run per dataset at a time, which is enforced by claiming the dataset inside
a transaction rather than by checking and hoping.
"""

from __future__ import annotations

import datetime as dt
import threading
import traceback

from django.db import close_old_connections, transaction
from django.utils import timezone

from . import builder, nwis_client
from .models import Dataset, Job

# Jobs run in daemon threads, so a server restart orphans them mid-run. Any
# "running" job older than this is dead; expire it rather than blocking the
# dataset forever. A full CONUS run finishes well inside an hour.
STALE_JOB_AGE = dt.timedelta(hours=3)


def _expire_stale(dataset: Dataset) -> None:
    """Mark orphaned jobs as failed and release the dataset."""
    cutoff = timezone.now() - STALE_JOB_AGE
    stale = dataset.jobs.filter(
        status__in=[Job.STATUS_PENDING, Job.STATUS_RUNNING], created_at__lt=cutoff
    )
    if not stale.exists():
        return
    stale.update(
        status=Job.STATUS_ERROR,
        message="Job died, most likely a server restart mid-run. Run it again.",
        finished_at=timezone.now(),
    )
    if dataset.status in (Dataset.STATUS_DISCOVERING, Dataset.STATUS_DOWNLOADING):
        Dataset.objects.filter(id=dataset.id).update(status=Dataset.STATUS_DRAFT)


def dataset_has_running_job(dataset: Dataset) -> bool:
    """Is a live job attached to this dataset right now?"""
    _expire_stale(dataset)
    cutoff = timezone.now() - STALE_JOB_AGE
    return dataset.jobs.filter(
        status__in=[Job.STATUS_PENDING, Job.STATUS_RUNNING], created_at__gte=cutoff
    ).exists()


def start_job(dataset: Dataset, kind: str) -> Job | None:
    """Claim the dataset and launch a worker thread, or return None if busy.

    The check and the claim happen in one transaction, so two rapid clicks (or
    two browser tabs) cannot both start a job and race each other into the same
    site table.
    """
    _expire_stale(dataset)
    cutoff = timezone.now() - STALE_JOB_AGE
    with transaction.atomic():
        locked = Dataset.objects.select_for_update().filter(id=dataset.id).first()
        if locked is None:
            return None
        busy = locked.jobs.filter(
            status__in=[Job.STATUS_PENDING, Job.STATUS_RUNNING], created_at__gte=cutoff
        ).exists()
        if busy:
            return None
        job = Job.objects.create(dataset=locked, kind=kind)

    t = threading.Thread(target=_run, args=(job.id,), daemon=True, name=f"job-{job.id}")
    t.start()
    return job


def _run(job_id: int) -> None:
    close_old_connections()
    job = Job.objects.get(id=job_id)
    dataset = job.dataset
    lines: list[str] = []

    def progress(frac: float, message: str) -> None:
        # Scoped to the running state so a job already marked failed (by the
        # stale sweeper, say) is not resurrected by its own dying thread.
        Job.objects.filter(
            id=job_id, status__in=[Job.STATUS_PENDING, Job.STATUS_RUNNING]
        ).update(
            status=Job.STATUS_RUNNING,
            progress=min(max(frac, 0.0), 1.0),
            message=message[:300],
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
                f"({res['candidates']} candidates)"
            )
            if res["failed_states"]:
                msg += (
                    f". WARNING: {len(res['failed_states'])} states failed even "
                    f"after retries ({', '.join(res['failed_states'])}), so these "
                    "results are incomplete. Run discovery again."
                )
        elif job.kind == Job.KIND_DOWNLOAD:
            Dataset.objects.filter(id=dataset.id).update(status=Dataset.STATUS_DOWNLOADING)
            res = nwis_client.download_dv(dataset, progress=progress, log=log)
            dataset.refresh_from_db()
            counts = builder.build_daily_tables(dataset, progress=progress, log=log)

            # The explorer memoizes daily tables per dataset; new Parquet files
            # must not be shadowed by the previous ones.
            from explorer.core import cache as explorer_cache

            explorer_cache.clear_memo()
            Dataset.objects.filter(id=dataset.id).update(
                status=Dataset.STATUS_READY, error_message=""
            )
            built = ", ".join(f"{k}: {v['rows']} rows" for k, v in counts.items())
            msg = (
                f"Downloaded {res['ok']} sites ({res['empty']} empty, "
                f"{len(res['failed'])} failed). {built}"
            )
        else:  # pragma: no cover
            raise ValueError(f"Unknown job kind {job.kind}")

        Job.objects.filter(id=job_id).update(
            status=Job.STATUS_DONE,
            progress=1.0,
            message=msg[:300],
            finished_at=timezone.now(),
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
