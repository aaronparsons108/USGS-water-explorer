"""Explorer views, parameterized by dataset slug.

Three endpoints back the single-page explorer: the page shell, a JSON results
payload (table + both figures + an explanation of what was computed), and file
downloads (PNG per figure, CSV of the filtered table).
"""

from __future__ import annotations

import json

from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from datasets.models import Dataset

from .core import figures
from .core.palettes import css_gradients
from .core.service import assemble, data_mode
from .forms import GROUP_COUNTS, GROUP_MI, GROUP_NMI, GROUP_VALUES, FilterForm

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

# Columns that read as text rather than measurements; the table left-aligns
# these and right-aligns everything else.
TEXT_COLUMNS = {
    "site_no",
    "site_export_id",
    "station_nm",
    "location_type",
    "huc2",
    "huc2_region_name",
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
    return [
        {
            "key": c,
            "label": labels.get(c, c),
            "numeric": c not in TEXT_COLUMNS,
        }
        for c in cols
    ]


def _figure_schema(schema: dict) -> figures.FigureSchema:
    """Labels plus every metric worth showing in a hover box.

    Counts are deliberately included: "MI 0.42 over 31 paired days" is a very
    different claim from the same number over 3000 days, and the hover is where
    a reader decides whether to trust the bubble.
    """
    hover = (
        schema["medians"]
        + schema["mis"]
        + schema.get("nmis", [])
        + [c for c in schema["numeric"] if c.startswith(("n_g", "n_paired_"))]
    )
    return figures.schema_from_metrics(_labels(schema), hover)


def _build_figures(table, fk, fig_schema):
    """Both figures for one request, from one filtered table."""
    map_fig = figures.map_figure(
        table,
        color_col=fk["map_color"],
        schema=fig_schema,
        palette=fk["map_palette"],
        color_scale=fk["color_scale"],
    )
    scatter_fig = figures.scatter_figure(
        table,
        fk["scatter_x"],
        fk["scatter_y"],
        schema=fig_schema,
        log_x=figures.effective_log(fk["scatter_x"], fk["log_x"]),
        log_y=figures.effective_log(fk["scatter_y"], fk["log_y"]),
        color_col=fk["scatter_color"],
        palette=fk["map_palette"],
        color_scale=fk["color_scale"],
    )
    return map_fig, scatter_fig


def index(request, slug: str | None = None):
    if slug is None:
        ds = _get_dataset(None)
        return redirect("explorer:index", slug=ds.slug)
    ds = _get_dataset(slug)
    schema = ds.metric_schema()
    form = FilterForm(ds)

    # The range filters are grouped so the sidebar can label each block by what
    # it measures instead of presenting one undifferentiated wall of numbers.
    range_blocks = [
        {
            "key": GROUP_VALUES,
            "title": "Measured values",
            "hint": "Per-site median of each parameter group.",
            "rows": form.range_rows(form.median_cols),
        },
        {
            "key": GROUP_MI,
            "title": "Mutual information",
            "hint": "Raw dependence in nats. Unbounded; higher is stronger.",
            "rows": form.range_rows(form.mi_cols),
        },
        {
            "key": GROUP_NMI,
            "title": "Normalized MI",
            "hint": "I(A;B)/H(A), bounded 0 to 1 and comparable across sites.",
            "rows": form.range_rows(form.nmi_cols),
        },
        {
            "key": GROUP_COUNTS,
            "title": "Minimum observation counts",
            "hint": "Drop thinly sampled sites from the table, map and scatter.",
            "rows": form.count_rows(),
        },
    ]
    range_blocks = [b for b in range_blocks if b["rows"]]

    return render(
        request,
        "explorer/index.html",
        {
            "ds": ds,
            "form": form,
            "mode": data_mode(ds),
            "range_blocks": range_blocks,
            "has_regions": bool(form.fields["regions"].choices),
            "has_huc2": bool(form.fields["huc2"].choices),
            # json_script does the encoding; passing a pre-dumped string
            # here would double-encode it and JSON.parse would hand the
            # page a string instead of the lookup table.
            "palette_gradients": css_gradients(),
            "n_groups": len(schema["medians"]),
        },
    )


def results(request, slug: str):
    ds = _get_dataset(slug)
    form = FilterForm(ds, request.GET)
    if not form.is_valid():
        return JsonResponse({"errors": form.errors}, status=400)

    table, info = assemble(ds, **form.service_kwargs())
    schema = ds.metric_schema()
    fig_schema = _figure_schema(schema)
    fk = form.figure_kwargs()
    map_fig, scatter_fig = _build_figures(table, fk, fig_schema)

    info["active_filters"] = form.active_filters()

    return JsonResponse(
        {
            "info": info,
            "columns": _columns(schema, "site_export_id" in table.columns),
            "rows": json.loads(table.to_json(orient="records")),
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
    fig_schema = _figure_schema(ds.metric_schema())
    fk = form.figure_kwargs()
    map_fig, scatter_fig = _build_figures(table, fk, fig_schema)

    if kind == "map":
        fig, fname = map_fig, f"{ds.slug}_map.png"
    elif kind == "scatter":
        fig, fname = scatter_fig, f"{ds.slug}_scatter.png"
    else:
        return JsonResponse({"error": f"Unknown figure '{kind}'."}, status=404)

    try:
        png = figures.to_png(fig)
    except Exception as e:
        return JsonResponse({"error": _png_error(kind, e)}, status=500)

    resp = HttpResponse(png, content_type="image/png")
    resp["Content-Disposition"] = f'attachment; filename="{fname}"'
    return resp


def _png_error(kind: str, exc: Exception) -> str:
    """Explain a failed PNG export in terms of the thing to go fix.

    The three real causes look nothing alike and need different responses, so
    guessing at one generic message ("is kaleido installed?") sends people
    down the wrong path.
    """
    text = str(exc)
    if "topojson" in text.lower():
        return (
            "The map PNG needs Plotly's US basemap, which is fetched from "
            "cdn.plot.ly at export time and could not be reached. Check the "
            "network connection, or export the scatter instead. The map in the "
            "page itself is unaffected."
        )
    if "chrome" in text.lower() or "chromium" in text.lower():
        return (
            "PNG export needs a Chrome or Chromium binary for kaleido to drive. "
            "Install Chrome, or run `plotly_get_chrome`, then try again."
        )
    return f"PNG export of the {kind} failed: {text}"


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
