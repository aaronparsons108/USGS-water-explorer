"""Explorer views, parameterized by dataset slug: filter page, JSON results,
and PNG/CSV downloads."""

from __future__ import annotations

import json

from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from datasets.models import Dataset

from .core import figures
from .core.service import assemble, data_mode
from .forms import FilterForm

META_LABELS = {
    "site_no": "Site #",
    "site_export_id": "ID",
    "station_nm": "Station",
    "location_type": "Region",
    "huc2": "HUC2",
    "huc2_region_name": "HUC2 region",
    "dec_lat_va": "Lat",
    "dec_long_va": "Lon",
}


def _get_dataset(slug: str | None) -> Dataset:
    if slug:
        return get_object_or_404(Dataset, slug=slug)
    demo = Dataset.objects.filter(is_demo=True).first()
    if demo is None:
        from datasets.management.commands.seed_demo import seed_demo_dataset

        demo = seed_demo_dataset()
    return demo


def _labels(schema: dict) -> dict:
    return {**META_LABELS, **schema["labels"]}


def _columns(schema: dict, has_export_id: bool) -> list[dict]:
    labels = _labels(schema)
    cols = list(schema["columns"])
    if has_export_id:
        cols = cols[:1] + ["site_export_id"] + cols[1:]
    return [{"key": c, "label": labels.get(c, c)} for c in cols]


def _configure_figures(schema: dict) -> None:
    figures.set_schema(_labels(schema), schema["medians"] + schema["mis"])


def index(request, slug: str | None = None):
    if slug is None:
        ds = _get_dataset(None)
        return redirect("explorer:index", slug=ds.slug)
    ds = _get_dataset(slug)
    schema = ds.metric_schema()
    form = FilterForm(ds)
    range_rows = [
        {"label": schema["labels"].get(c, c), "min": form[f"{c}__min"], "max": form[f"{c}__max"]}
        for c in form.range_metrics
    ]
    count_rows = [
        {"label": schema["labels"].get(c, c), "min": form[f"{c}__min"]} for c in form.count_cols
    ]
    return render(
        request,
        "explorer/index.html",
        {
            "ds": ds,
            "form": form,
            "mode": data_mode(ds),
            "range_rows": range_rows,
            "count_rows": count_rows,
        },
    )


def results(request, slug: str):
    ds = _get_dataset(slug)
    form = FilterForm(ds, request.GET)
    if not form.is_valid():
        return JsonResponse({"errors": form.errors}, status=400)

    table, info = assemble(ds, **form.service_kwargs())
    schema = ds.metric_schema()
    _configure_figures(schema)
    fk = form.figure_kwargs()

    map_fig = figures.map_figure(table, color_col=fk["map_color"])
    scatter_fig = figures.scatter_figure(
        table, fk["scatter_x"], fk["scatter_y"],
        log_x=fk["log_x"], log_y=fk["log_y"], color_col=fk["scatter_color"],
    )

    rows = json.loads(table.to_json(orient="records"))
    return JsonResponse(
        {
            "info": info,
            "columns": _columns(schema, "site_export_id" in table.columns),
            "rows": rows,
            "map": json.loads(map_fig.to_json()),
            "scatter": json.loads(scatter_fig.to_json()),
            "query": request.GET.urlencode(),
        }
    )


def download_png(request, slug: str, kind: str):
    ds = _get_dataset(slug)
    form = FilterForm(ds, request.GET)
    if not form.is_valid():
        return JsonResponse({"errors": form.errors}, status=400)

    table, _ = assemble(ds, **form.service_kwargs())
    _configure_figures(ds.metric_schema())
    fk = form.figure_kwargs()
    if kind == "map":
        fig = figures.map_figure(table, color_col=fk["map_color"])
        fname = f"{ds.slug}_map.png"
    elif kind == "scatter":
        fig = figures.scatter_figure(
            table, fk["scatter_x"], fk["scatter_y"],
            log_x=fk["log_x"], log_y=fk["log_y"], color_col=fk["scatter_color"],
        )
        fname = f"{ds.slug}_scatter.png"
    else:
        return JsonResponse({"error": f"unknown figure '{kind}'"}, status=404)

    try:
        png = figures.to_png(fig)
    except Exception as e:  # kaleido / chromium not available
        return JsonResponse(
            {"error": f"PNG export failed ({e}). Is kaleido installed?"}, status=500
        )

    resp = HttpResponse(png, content_type="image/png")
    resp["Content-Disposition"] = f'attachment; filename="{fname}"'
    return resp


def download_csv(request, slug: str):
    ds = _get_dataset(slug)
    form = FilterForm(ds, request.GET)
    if not form.is_valid():
        return JsonResponse({"errors": form.errors}, status=400)
    table, _ = assemble(ds, **form.service_kwargs())
    resp = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = f'attachment; filename="{ds.slug}_sites_filtered.csv"'
    table.to_csv(resp, index=False)
    return resp
