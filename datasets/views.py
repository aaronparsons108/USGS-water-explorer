"""Wizard views: dataset list -> setup (groups) -> sites (discover/select) ->
download (fetch + build) -> hand off to the explorer."""

from __future__ import annotations

import datetime as dt
import json
import shutil

from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from . import catalog, jobs
from .models import CandidateSite, Dataset, Job, ParameterGroup

MAX_GROUPS = 5
MIN_GROUPS = 2


def _dataset_card(ds: Dataset) -> dict:
    return {
        "id": ds.id,
        "slug": ds.slug,
        "name": ds.name,
        "status": ds.status,
        "status_label": ds.get_status_display(),
        "is_demo": ds.is_demo,
        "groups": [
            {"position": g.position, "label": g.label, "n_codes": len(g.pmcodes)}
            for g in ds.groups_ordered()
        ],
        "n_sites": ds.sites.count(),
        "n_selected": ds.sites.filter(selected=True).count(),
        "created": ds.created_at.strftime("%Y-%m-%d"),
        "error": ds.error_message,
    }


def list_view(request):
    # Lazily ensure the demo dataset exists so a fresh clone shows an example.
    if not Dataset.objects.filter(is_demo=True).exists():
        try:
            from .management.commands.seed_demo import seed_demo_dataset

            seed_demo_dataset()
        except Exception:
            pass
    cards = [_dataset_card(d) for d in Dataset.objects.all()]
    return render(request, "datasets/list.html", {"cards": cards})


@require_POST
def create_view(request):
    today = dt.date.today()
    ds = Dataset.objects.create(
        name=f"New extraction {today.isoformat()}",
        start_date=dt.date(2008, 1, 1),
        end_date=today,
        states=[],
        services=["dv"],
    )
    # start with the standard 3 empty groups
    for pos in (1, 2, 3):
        ParameterGroup.objects.create(dataset=ds, position=pos, label=f"Group {pos}", pmcodes=[])
    return redirect("datasets:setup", pk=ds.id)


def setup_view(request, pk: int):
    ds = get_object_or_404(Dataset, pk=pk)
    bootstrap = {
        "id": ds.id,
        "name": ds.name,
        "is_demo": ds.is_demo,
        "start_date": ds.start_date.isoformat(),
        "end_date": ds.end_date.isoformat(),
        "states": ds.states,
        "services": ds.services,
        "exclude_wells": ds.exclude_wells,
        "min_count_per_series": ds.min_count_per_series,
        "groups": [
            {"position": g.position, "label": g.label, "pmcodes": g.pmcodes}
            for g in ds.groups_ordered()
        ],
        "example_groups": catalog.EXAMPLE_GROUPS,
        "all_states": catalog.ALL_STATES,
        "conus_states": catalog.CONUS_STATES,
        "services_choices": catalog.SERVICE_CHOICES,
        "max_groups": MAX_GROUPS,
        "min_groups": MIN_GROUPS,
    }
    return render(
        request, "datasets/setup.html", {"ds": ds, "bootstrap": bootstrap}
    )


@require_POST
def setup_save(request, pk: int):
    ds = get_object_or_404(Dataset, pk=pk)
    if ds.is_demo:
        return JsonResponse({"error": "The demo dataset is read-only."}, status=400)
    if jobs.dataset_has_running_job(ds):
        return JsonResponse({"error": "A job is running for this dataset."}, status=409)
    try:
        data = json.loads(request.body)
        name = str(data["name"]).strip()
        start = dt.date.fromisoformat(data["start_date"])
        end = dt.date.fromisoformat(data["end_date"])
        states = [str(s).upper() for s in data.get("states", [])]
        services = [str(s).lower() for s in data.get("services", [])]
        groups = data["groups"]
    except (KeyError, ValueError, TypeError) as e:
        return JsonResponse({"error": f"Bad payload: {e}"}, status=400)

    if not name:
        return JsonResponse({"error": "Name is required."}, status=400)
    if end <= start:
        return JsonResponse({"error": "End date must be after start date."}, status=400)
    if not services:
        return JsonResponse({"error": "Pick at least one data service."}, status=400)
    if not (MIN_GROUPS <= len(groups) <= MAX_GROUPS):
        return JsonResponse(
            {"error": f"Need between {MIN_GROUPS} and {MAX_GROUPS} groups."}, status=400
        )
    for i, g in enumerate(groups, start=1):
        if not str(g.get("label", "")).strip():
            return JsonResponse({"error": f"Group {i} needs a label."}, status=400)
        if not g.get("pmcodes"):
            return JsonResponse(
                {"error": f"Group {i} ({g.get('label')}) needs at least one parameter code."},
                status=400,
            )

    ds.name = name
    ds.start_date, ds.end_date = start, end
    ds.states, ds.services = states, services
    ds.exclude_wells = bool(data.get("exclude_wells", True))
    ds.min_count_per_series = max(1, int(data.get("min_count_per_series") or 1))
    ds.status = Dataset.STATUS_DRAFT
    ds.error_message = ""
    ds.save()
    ds.groups.all().delete()
    for i, g in enumerate(groups, start=1):
        ParameterGroup.objects.create(
            dataset=ds,
            position=i,
            label=str(g["label"]).strip()[:80],
            pmcodes=[
                {
                    "code": str(p["code"]).zfill(5),
                    "name": str(p.get("name") or "")[:120],
                    "unit": str(p.get("unit") or "")[:40],
                }
                for p in g["pmcodes"]
            ],
        )
    return JsonResponse({"ok": True})


@require_GET
def pmcode_search(request):
    q = request.GET.get("q", "")
    try:
        return JsonResponse({"results": catalog.search_pmcodes(q)})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


def sites_view(request, pk: int):
    ds = get_object_or_404(Dataset, pk=pk)
    groups = [{"position": g.position, "label": g.label} for g in ds.groups_ordered()]
    bootstrap = {
        "id": ds.id,
        "status": ds.status,
        "is_demo": ds.is_demo,
        "groups": groups,
        "n_sites": ds.sites.count(),
    }
    return render(
        request, "datasets/sites.html", {"ds": ds, "bootstrap": bootstrap}
    )


@require_POST
def discover_start(request, pk: int):
    ds = get_object_or_404(Dataset, pk=pk)
    if ds.is_demo:
        return JsonResponse({"error": "The demo dataset is read-only."}, status=400)
    if not ds.groups.exists():
        return JsonResponse({"error": "Configure parameter groups first."}, status=400)
    if jobs.dataset_has_running_job(ds):
        return JsonResponse({"error": "A job is already running."}, status=409)
    job = jobs.start_job(ds, Job.KIND_DISCOVER)
    return JsonResponse({"ok": True, "job_id": job.id})


@require_GET
def job_status(request, pk: int):
    ds = get_object_or_404(Dataset, pk=pk)
    kind = request.GET.get("kind")
    qs = ds.jobs.all()
    if kind:
        qs = qs.filter(kind=kind)
    job = qs.first()
    ds.refresh_from_db()
    if job is None:
        return JsonResponse({"job": None, "dataset_status": ds.status})
    return JsonResponse(
        {
            "job": {
                "id": job.id,
                "kind": job.kind,
                "status": job.status,
                "progress": job.progress,
                "message": job.message,
                "log_tail": "\n".join(job.log.splitlines()[-12:]),
            },
            "dataset_status": ds.status,
        }
    )


@require_GET
def sites_data(request, pk: int):
    ds = get_object_or_404(Dataset, pk=pk)
    groups = ds.groups_ordered()
    rows = []
    for s in ds.sites.all():
        rows.append(
            {
                "site_no": s.site_no,
                "station_nm": s.station_nm,
                "state": s.state_cd,
                "lat": s.dec_lat_va,
                "lon": s.dec_long_va,
                "huc2": s.huc2,
                "coverage": {str(g.position): s.group_coverage.get(str(g.position), []) for g in groups},
                "begin": s.begin_date,
                "end": s.end_date,
                "count": s.total_count,
                "selected": s.selected,
            }
        )
    return JsonResponse(
        {"groups": [{"position": g.position, "label": g.label} for g in groups], "sites": rows}
    )


@require_POST
def sites_save(request, pk: int):
    ds = get_object_or_404(Dataset, pk=pk)
    if ds.is_demo:
        return JsonResponse({"error": "The demo dataset is read-only."}, status=400)
    try:
        selected = set(json.loads(request.body)["selected"])
    except (KeyError, ValueError, TypeError) as e:
        return JsonResponse({"error": f"Bad payload: {e}"}, status=400)
    if not selected:
        return JsonResponse({"error": "Select at least one site."}, status=400)
    ds.sites.update(selected=False)
    n = ds.sites.filter(site_no__in=list(selected)).update(selected=True)
    return JsonResponse({"ok": True, "n_selected": n})


def download_view(request, pk: int):
    ds = get_object_or_404(Dataset, pk=pk)
    bootstrap = {
        "id": ds.id,
        "slug": ds.slug,
        "status": ds.status,
        "is_demo": ds.is_demo,
        "n_selected": ds.sites.filter(selected=True).count(),
        "n_codes": len(ds.all_pmcodes()),
        "codes": ds.all_pmcodes(),
        "start": ds.start_date.isoformat(),
        "end": ds.end_date.isoformat(),
        "unit_report": ds.unit_report,
    }
    return render(
        request, "datasets/download.html", {"ds": ds, "bootstrap": bootstrap}
    )


@require_POST
def download_start(request, pk: int):
    ds = get_object_or_404(Dataset, pk=pk)
    if ds.is_demo:
        return JsonResponse({"error": "The demo dataset is read-only."}, status=400)
    if not ds.sites.filter(selected=True).exists():
        return JsonResponse({"error": "No sites selected — run discovery first."}, status=400)
    if jobs.dataset_has_running_job(ds):
        return JsonResponse({"error": "A job is already running."}, status=409)
    job = jobs.start_job(ds, Job.KIND_DOWNLOAD)
    return JsonResponse({"ok": True, "job_id": job.id})


@require_POST
def delete_view(request, pk: int):
    ds = get_object_or_404(Dataset, pk=pk)
    if ds.is_demo:
        return JsonResponse({"error": "The demo dataset cannot be deleted."}, status=400)
    if jobs.dataset_has_running_job(ds):
        return JsonResponse({"error": "A job is running for this dataset."}, status=409)
    store = ds.store_dir
    ds.delete()
    shutil.rmtree(store, ignore_errors=True)
    return redirect("datasets:list")
