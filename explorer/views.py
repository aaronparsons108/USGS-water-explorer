"""Views: the filter page, the JSON results endpoint, and PNG downloads."""

from __future__ import annotations

import json

from django.http import HttpResponse, JsonResponse
from django.shortcuts import render

from .core import figures
from .core.service import OUTPUT_COLUMNS, METRIC_LABELS, data_mode, assemble
from .forms import FilterForm, RANGE_METRICS, COUNT_COLS

# Friendly column headers for the results table.
DISPLAY_LABELS = {
    "site_no": "Site #",
    "site_export_id": "ID",
    "station_nm": "Station",
    "location_type": "Region",
    "huc2": "HUC2",
    "huc2_region_name": "HUC2 region",
    "dec_lat_va": "Lat",
    "dec_long_va": "Lon",
    **METRIC_LABELS,
}


def _columns() -> list[dict]:
    return [{"key": c, "label": DISPLAY_LABELS.get(c, c)} for c in OUTPUT_COLUMNS]


def index(request):
    form = FilterForm()
    range_rows = [
        {"label": METRIC_LABELS.get(c, c), "min": form[f"{c}__min"], "max": form[f"{c}__max"]}
        for c in RANGE_METRICS
    ]
    count_rows = [
        {"label": METRIC_LABELS.get(c, c), "min": form[f"{c}__min"]} for c in COUNT_COLS
    ]
    return render(
        request,
        "explorer/index.html",
        {
            "form": form,
            "mode": data_mode(),
            "columns": _columns(),
            "range_rows": range_rows,
            "count_rows": count_rows,
        },
    )


def results(request):
    """Validate the filter form, assemble the table, return JSON + figure specs."""
    form = FilterForm(request.GET)  # bound even when empty; all fields optional
    if not form.is_valid():
        return JsonResponse({"errors": form.errors}, status=400)

    table, info = assemble(**form.service_kwargs())
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
            "columns": _columns(),
            "rows": rows,
            "map": json.loads(map_fig.to_json()),
            "scatter": json.loads(scatter_fig.to_json()),
            "query": request.GET.urlencode(),
        }
    )


def download_png(request, kind: str):
    """Render the current map or scatter as a downloadable PNG (kaleido)."""
    form = FilterForm(request.GET)  # bound even when empty; all fields optional
    if not form.is_valid():
        return JsonResponse({"errors": form.errors}, status=400)

    table, _ = assemble(**form.service_kwargs())
    fk = form.figure_kwargs()
    if kind == "map":
        fig = figures.map_figure(table, color_col=fk["map_color"])
        fname = "nitro_map.png"
    elif kind == "scatter":
        fig = figures.scatter_figure(
            table, fk["scatter_x"], fk["scatter_y"],
            log_x=fk["log_x"], log_y=fk["log_y"], color_col=fk["scatter_color"],
        )
        fname = "nitro_scatter.png"
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


def download_csv(request):
    """Download the current filtered table as CSV."""
    form = FilterForm(request.GET)  # bound even when empty; all fields optional
    if not form.is_valid():
        return JsonResponse({"errors": form.errors}, status=400)
    table, _ = assemble(**form.service_kwargs())
    resp = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = 'attachment; filename="nitro_sites_filtered.csv"'
    table.to_csv(resp, index=False)
    return resp
