"""Orchestration: assemble the filtered per-site table for a dataset.

Joins the dataset's site metadata with recomputed (or demo-fallback) metrics,
applies user filters, and reports which mode was used. Column names and labels
come from ``Dataset.metric_schema()`` — median_g<pos>, mi_g<i>_g<j>, etc.
"""

from __future__ import annotations

import pandas as pd

from . import cache, filters
from .metadata import load_dataset_metadata, load_fallback_metrics_general
from .seasons import months_for_period


def data_mode(dataset) -> dict:
    """What data backend is available for this dataset right now."""
    daily = cache.dataset_daily_available(dataset)
    return {
        "recompute_enabled": daily,
        "raw_available": cache.raw_sitedata_available() if dataset.is_demo else True,
        "is_demo": dataset.is_demo,
    }


def assemble(
    dataset,
    *,
    start=None,
    end=None,
    season=None,
    month=None,
    min_paired_days: int = 30,
    regions=None,
    huc2s=None,
    site_query: str | None = None,
    ranges=None,
) -> tuple[pd.DataFrame, dict]:
    """Build the filtered per-site table + info dict (mode, warnings, counts)."""
    schema = dataset.metric_schema()
    meta = load_dataset_metadata(dataset)
    mode = data_mode(dataset)
    warnings: list[str] = []

    wants_recompute = bool(start or end or season or month)
    months = months_for_period(season, month)

    if mode["recompute_enabled"]:
        metrics = cache.compute_metrics(
            dataset,
            start=start or None,
            end=end or None,
            months=months,
            min_paired_days=min_paired_days,
        )
        used_mode = "recompute"
    elif dataset.is_demo:
        metrics = load_fallback_metrics_general()
        used_mode = "fallback"
        if wants_recompute:
            warnings.append(
                "Date-range and season filters need the parsed demo cache. Set "
                "NITRO_DATA_ROOT to your nitro-research checkout and run "
                "`python manage.py build_cache`. Showing full-window values."
            )
    else:
        metrics = pd.DataFrame(columns=["site_no"])
        used_mode = "missing"
        warnings.append(
            "This dataset has no built daily tables yet — run the download step."
        )

    metrics["site_no"] = metrics.get("site_no", pd.Series(dtype=str)).astype(str)
    meta["site_no"] = meta["site_no"].astype(str)
    table = meta.merge(metrics, on="site_no", how="left")

    # Column order: schema meta+metrics, with legacy extras (site_export_id) kept.
    cols = list(schema["columns"])
    if "site_export_id" in table.columns:
        cols = cols[:1] + ["site_export_id"] + cols[1:]
    for col in cols:
        if col not in table.columns:
            table[col] = pd.NA
    table = table[cols]

    n_total = len(table)
    table = filters.apply_filters(
        table, regions=regions, huc2s=huc2s, site_query=site_query, ranges=ranges
    )
    sort_col = "site_export_id" if "site_export_id" in table.columns else "site_no"
    table = table.sort_values(sort_col, na_position="last").reset_index(drop=True)

    info = {
        "mode": used_mode,
        "recompute_enabled": mode["recompute_enabled"],
        "warnings": warnings,
        "n_total": int(n_total),
        "n_filtered": int(len(table)),
        "months": sorted(months) if months else None,
    }
    return table, info
