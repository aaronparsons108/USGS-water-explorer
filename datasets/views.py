"""Wizard views.

Dataset list, then setup (parameter groups and scope), then site discovery and
selection, then download and build, then hand off to the explorer.

Every write endpoint validates the whole payload before it mutates anything.
An earlier version deleted a dataset's parameter groups and then parsed the
replacement, so one malformed request destroyed the user's configuration.
"""

from __future__ import annotations

import datetime as dt
import json
import shutil

from django.db import transaction
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from . import catalog, jobs
from .models import Dataset, Job, ParameterGroup

MAX_GROUPS = 5
MIN_GROUPS = 2
MAX_CODES_PER_GROUP = 40


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
            for g in ds.groups.all()
        ],
        "n_sites": ds.n_sites,
        "n_selected": ds.n_selected,
        "created": ds.created_at.strftime("%Y-%m-%d"),
        "error": ds.error_message,
    }


def list_view(request):
    # Lazily ensure the demo exists so a fresh clone has something to open.
    # Seeding needs the parameter catalog, which needs either the committed
    # snapshot or network access; if neither is there, say so instead of
    # showing an unexplained empty page.
    seed_error = ""
    if not Dataset.objects.filter(is_demo=True).exists():
        try:
            from .management.commands.seed_demo import seed_demo_dataset

            seed_demo_dataset()
        except Exception as e:
            seed_error = (
                f"The bundled demo dataset could not be built ({type(e).__name__}: "
                f"{e}). The parameter-code catalog is needed to seed it: place a "
                "snapshot at data/pmcode_catalog.csv, or run "
                "`python manage.py seed_demo` once with network access."
            )

    datasets = (
        Dataset.objects.all()
        .prefetch_related("groups")
        .annotate(
            n_sites=Count("sites", distinct=True),
            n_selected=Count("sites", filter=Q(sites__selected=True), distinct=True),
        )
    )
    cards = [_dataset_card(d) for d in datasets]
    return render(request, "datasets/list.html", {"cards": cards, "seed_error": seed_error})


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
    for pos in (1, 2, 3):
        ParameterGroup.objects.create(
            dataset=ds, position=pos, label=f"Group {pos}", pmcodes=[]
        )
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
            {
                "position": g.position,
                "label": g.label,
                "pmcodes": g.pmcodes,
                "require_canonical": g.require_canonical,
            }
            for g in ds.groups_ordered()
        ],
        "example_groups": catalog.EXAMPLE_GROUPS,
        "all_states": catalog.ALL_STATES,
        "conus_states": catalog.CONUS_STATES,
        "services_choices": catalog.SERVICE_CHOICES,
        "max_groups": MAX_GROUPS,
        "min_groups": MIN_GROUPS,
    }
    return render(request, "datasets/setup.html", {"ds": ds, "bootstrap": bootstrap})


def _parse_setup_payload(data) -> tuple[dict, str]:
    """Validate the whole setup payload up front.

    Returns ``(clean, "")`` or ``({}, message)``. Nothing is written until this
    returns cleanly, so a bad request cannot leave a half-configured dataset.
    """
    try:
        name = str(data["name"]).strip()
        start = dt.date.fromisoformat(str(data["start_date"]))
        end = dt.date.fromisoformat(str(data["end_date"]))
        states = [str(s).upper() for s in data.get("states", [])]
        services = [str(s).lower() for s in data.get("services", [])]
        raw_groups = data["groups"]
    except (KeyError, ValueError, TypeError) as e:
        return {}, f"Bad payload: {e}"

    try:
        min_count = max(1, int(data.get("min_count_per_series") or 1))
    except (TypeError, ValueError):
        return {}, "Minimum observations per series must be a whole number."

    if not name:
        return {}, "Name is required."
    if end <= start:
        return {}, "End date must be after start date."
    if not states:
        return {}, "Pick at least one state."
    if not services:
        return {}, "Pick at least one data service."
    known_services = {code for code, _ in catalog.SERVICE_CHOICES}
    unknown = sorted(set(services) - known_services)
    if unknown:
        return {}, f"Unknown data service: {', '.join(unknown)}."
    if not isinstance(raw_groups, list):
        return {}, "Groups must be a list."
    if not (MIN_GROUPS <= len(raw_groups) <= MAX_GROUPS):
        return {}, f"Pick between {MIN_GROUPS} and {MAX_GROUPS} parameter groups."

    groups = []
    for i, g in enumerate(raw_groups, start=1):
        if not isinstance(g, dict):
            return {}, f"Group {i} is malformed."
        label = str(g.get("label", "")).strip()
        if not label:
            return {}, f"Group {i} needs a label."
        pmcodes = g.get("pmcodes")
        if not isinstance(pmcodes, list) or not pmcodes:
            return {}, f"Group {i} ({label}) needs at least one parameter code."
        if len(pmcodes) > MAX_CODES_PER_GROUP:
            return {}, f"Group {i} ({label}) has more than {MAX_CODES_PER_GROUP} codes."
        clean_codes = []
        for p in pmcodes:
            if not isinstance(p, dict) or not str(p.get("code", "")).strip():
                return {}, f"Group {i} ({label}) has a malformed parameter code entry."
            clean_codes.append(
                {
                    "code": str(p["code"]).strip().zfill(5),
                    "name": str(p.get("name") or "")[:120],
                    "unit": str(p.get("unit") or "")[:40],
                }
            )
        groups.append(
            {
                "label": label[:80],
                "require_canonical": bool(g.get("require_canonical")),
                "pmcodes": clean_codes,
            }
        )

    return {
        "name": name[:120],
        "start": start,
        "end": end,
        "states": states,
        "services": services,
        "min_count": min_count,
        "exclude_wells": bool(data.get("exclude_wells", True)),
        "groups": groups,
    }, ""


@require_POST
def setup_save(request, pk: int):
    ds = get_object_or_404(Dataset, pk=pk)
    if ds.is_demo:
        return JsonResponse({"error": "The demo dataset is read-only."}, status=400)
    if jobs.dataset_has_running_job(ds):
        return JsonResponse({"error": "A job is running for this dataset."}, status=409)

    try:
        payload = json.loads(request.body)
    except ValueError as e:
        return JsonResponse({"error": f"Bad payload: {e}"}, status=400)

    clean, error = _parse_setup_payload(payload)
    if error:
        return JsonResponse({"error": error}, status=400)

    with transaction.atomic():
        ds.name = clean["name"]
        ds.start_date, ds.end_date = clean["start"], clean["end"]
        ds.states, ds.services = clean["states"], clean["services"]
        ds.exclude_wells = clean["exclude_wells"]
        ds.min_count_per_series = clean["min_count"]
        ds.status = Dataset.STATUS_DRAFT
        ds.error_message = ""
        ds.save()
        ds.groups.all().delete()
        for i, g in enumerate(clean["groups"], start=1):
            ParameterGroup.objects.create(dataset=ds, position=i, **g)
    return JsonResponse({"ok": True})


@require_GET
def pmcode_search(request):
    q = request.GET.get("q", "")
    try:
        return JsonResponse({"results": catalog.search_pmcodes(q)})
    except Exception as e:
        return JsonResponse(
            {
                "error": (
                    f"Parameter-code catalog unavailable ({type(e).__name__}: {e}). "
                    "It is fetched from USGS on first use, or read from "
                    "data/pmcode_catalog.csv when offline."
                )
            },
            status=503,
        )


def sites_view(request, pk: int):
    ds = get_object_or_404(Dataset, pk=pk)
    bootstrap = {
        "id": ds.id,
        "status": ds.status,
        "is_demo": ds.is_demo,
        "groups": [{"position": g.position, "label": g.label} for g in ds.groups_ordered()],
        "n_sites": ds.sites.count(),
    }
    return render(request, "datasets/sites.html", {"ds": ds, "bootstrap": bootstrap})


@require_POST
def discover_start(request, pk: int):
    ds = get_object_or_404(Dataset, pk=pk)
    if ds.is_demo:
        return JsonResponse({"error": "The demo dataset is read-only."}, status=400)
    if not ds.groups.exists():
        return JsonResponse({"error": "Configure parameter groups first."}, status=400)
    job = jobs.start_job(ds, Job.KIND_DISCOVER)
    if job is None:
        return JsonResponse({"error": "A job is already running."}, status=409)
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
    rows = [
        {
            "site_no": s.site_no,
            "station_nm": s.station_nm,
            "state": s.state_cd,
            "lat": s.dec_lat_va,
            "lon": s.dec_long_va,
            "huc2": s.huc2,
            "coverage": {
                str(g.position): s.group_coverage.get(str(g.position), []) for g in groups
            },
            "begin": s.begin_date,
            "end": s.end_date,
            "count": s.total_count,
            "selected": s.selected,
        }
        for s in ds.sites.all()
    ]
    return JsonResponse(
        {
            "groups": [{"position": g.position, "label": g.label} for g in groups],
            "sites": rows,
        }
    )


@require_POST
def sites_save(request, pk: int):
    ds = get_object_or_404(Dataset, pk=pk)
    if ds.is_demo:
        return JsonResponse({"error": "The demo dataset is read-only."}, status=400)
    if jobs.dataset_has_running_job(ds):
        return JsonResponse(
            {"error": "A job is running for this dataset; wait for it to finish."},
            status=409,
        )
    try:
        raw = json.loads(request.body)["selected"]
    except (KeyError, ValueError, TypeError) as e:
        return JsonResponse({"error": f"Bad payload: {e}"}, status=400)

    # A bare string would iterate character by character and silently deselect
    # everything, so require an actual list.
    if not isinstance(raw, (list, tuple)):
        return JsonResponse({"error": "'selected' must be a list of site numbers."}, status=400)
    selected = {str(s) for s in raw if str(s).strip()}
    if not selected:
        return JsonResponse({"error": "Select at least one site."}, status=400)

    known = set(ds.sites.values_list("site_no", flat=True))
    unknown = selected - known
    if unknown:
        return JsonResponse(
            {"error": f"{len(unknown)} of those sites are not in this dataset."},
            status=400,
        )

    with transaction.atomic():
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
    return render(request, "datasets/download.html", {"ds": ds, "bootstrap": bootstrap})


@require_POST
def download_start(request, pk: int):
    ds = get_object_or_404(Dataset, pk=pk)
    if ds.is_demo:
        return JsonResponse({"error": "The demo dataset is read-only."}, status=400)
    if not ds.sites.filter(selected=True).exists():
        return JsonResponse(
            {"error": "No sites selected. Run discovery and pick some first."}, status=400
        )
    job = jobs.start_job(ds, Job.KIND_DOWNLOAD)
    if job is None:
        return JsonResponse({"error": "A job is already running."}, status=409)
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
