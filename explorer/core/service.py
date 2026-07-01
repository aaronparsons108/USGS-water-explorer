"""Orchestration: assemble the filtered per-site table the views render.

Joins static metadata with recomputed (or fallback) metrics, applies the user's
filters, and reports which mode was used so the UI can show a banner when
date/season recompute is unavailable.
"""

from __future__ import annotations

import pandas as pd

from . import cache, filters
from .metadata import load_site_metadata, load_fallback_metrics
from .seasons import months_for_period

# Canonical output column order for table + CSV + figures.
OUTPUT_COLUMNS = [
    "site_no",
    "site_export_id",
    "station_nm",
    "location_type",
    "huc2",
    "huc2_region_name",
    "dec_lat_va",
    "dec_long_va",
    "median_00060_Mean",
    "n_flow_obs",
    "median_no3no2",
    "n_combined_days",
    "median_do_mg_l",
    "n_do_days",
    "mutual_information_flow_no3",
    "n_paired_days_flow_no3",
    "mutual_information_no3_do",
    "n_paired_days_no3_do",
]

# Human labels for metric columns (used by the table header and axis menus).
METRIC_LABELS = {
    "median_00060_Mean": "Median streamflow E(Q) (cfs)",
    "median_no3no2": "Median NO3+NO2 E(C) (mg/L as N)",
    "median_do_mg_l": "Median dissolved oxygen (mg/L)",
    "mutual_information_flow_no3": "MI(Q; NO3+NO2) (nats)",
    "mutual_information_no3_do": "MI(NO3+NO2; DO) (nats)",
    "n_flow_obs": "# flow days",
    "n_combined_days": "# NO3+NO2 days",
    "n_do_days": "# DO days",
    "n_paired_days_flow_no3": "# paired days (Q,C)",
    "n_paired_days_no3_do": "# paired days (C,DO)",
}

# Numeric columns offered as filter ranges and scatter axes.
NUMERIC_COLUMNS = [
    "median_00060_Mean",
    "median_no3no2",
    "median_do_mg_l",
    "mutual_information_flow_no3",
    "mutual_information_no3_do",
    "n_flow_obs",
    "n_combined_days",
    "n_do_days",
    "n_paired_days_flow_no3",
    "n_paired_days_no3_do",
]


def data_mode() -> dict:
    """Describe what data backend is available right now."""
    built = cache.caches_built()
    return {
        "caches_built": built,
        "raw_available": cache.raw_sitedata_available(),
        "recompute_enabled": built,
    }


def assemble(
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
    """Build the filtered per-site table and an info dict (mode, warnings, counts)."""
    meta = load_site_metadata()
    mode = data_mode()
    warnings: list[str] = []

    wants_recompute = bool(start or end or season or month)
    months = months_for_period(season, month)

    if mode["recompute_enabled"]:
        metrics = cache.compute_metrics(
            start=start or None,
            end=end or None,
            months=months,
            min_paired_days=min_paired_days,
        )
        used_mode = "recompute"
    else:
        metrics = load_fallback_metrics()
        used_mode = "fallback"
        if wants_recompute:
            warnings.append(
                "Date-range and season filters need the parsed cache. Set "
                "NITRO_DATA_ROOT to your nitro-research checkout and run "
                "`python manage.py build_cache`. Showing full-window values."
            )

    table = meta.merge(metrics, on="site_no", how="left")
    for col in OUTPUT_COLUMNS:
        if col not in table.columns:
            table[col] = pd.NA
    table = table[OUTPUT_COLUMNS]

    n_total = len(table)
    table = filters.apply_filters(
        table,
        regions=regions,
        huc2s=huc2s,
        site_query=site_query,
        ranges=ranges,
    )

    table = table.sort_values("site_export_id", na_position="last").reset_index(drop=True)

    info = {
        "mode": used_mode,
        "recompute_enabled": mode["recompute_enabled"],
        "raw_available": mode["raw_available"],
        "warnings": warnings,
        "n_total": int(n_total),
        "n_filtered": int(len(table)),
        "months": sorted(months) if months else None,
    }
    return table, info
