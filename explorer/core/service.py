"""Orchestration: assemble the filtered per-site table for a dataset.

Joins the dataset's site metadata with recomputed (or demo-fallback) metrics,
applies the user's filters, and reports which mode was used. Column names and
labels come from ``Dataset.metric_schema()``: median_g<pos>, mi_g<i>_g<j>, and
so on.
"""

from __future__ import annotations

import pandas as pd

from . import cache, filters
from .metrics import DEFAULT_MIN_PAIRED_DAYS
from .conversions import normalize_usgs_site_no
from .metadata import load_dataset_metadata, load_fallback_metrics_general
from .seasons import months_for_period

# Internal join key, dropped before the table is returned.
_JOIN = "_site_key"


def data_mode(dataset) -> dict:
    """Which data backend is available for this dataset right now."""
    # Tables are only trustworthy once the download step has finished for the
    # configuration currently on the dataset. While it is a draft or mid-build,
    # anything on disk describes an older set of groups, so recompute is
    # refused rather than served under labels it was not built with.
    settled = dataset.is_demo or dataset.status == dataset.STATUS_READY
    return {
        "recompute_enabled": settled and cache.dataset_daily_available(dataset),
        "is_demo": dataset.is_demo,
    }


def assemble(
    dataset,
    *,
    start=None,
    end=None,
    season=None,
    month=None,
    min_paired_days: int = DEFAULT_MIN_PAIRED_DAYS,
    regions=None,
    huc2s=None,
    site_query: str | None = None,
    ranges=None,
) -> tuple[pd.DataFrame, dict]:
    """Build the filtered per-site table plus an info dict.

    The info dict carries everything the front end needs to explain the result:
    which compute mode ran, how many sites survived filtering, which months
    were included, and any warnings about controls that could not take effect.
    """
    schema = dataset.metric_schema()
    meta = load_dataset_metadata(dataset)
    mode = data_mode(dataset)
    warnings: list[str] = []

    months = months_for_period(season, month)
    # Controls that only mean something when metrics are recomputed from the
    # daily tables. If recompute is off, every one of these is inert, and
    # saying so is better than silently ignoring the user.
    time_controls = {
        "start date": bool(start),
        "end date": bool(end),
        "season": bool(season),
        "month": bool(month),
        "minimum paired days": int(min_paired_days) != DEFAULT_MIN_PAIRED_DAYS,
    }

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
        inert = [name for name, active in time_controls.items() if active]
        if inert:
            warnings.append(
                f"Showing full-window values: {_join(inert)} cannot be applied "
                "without the parsed daily cache. Point NITRO_DATA_ROOT at a "
                "nitro-research checkout and run `python manage.py build_cache` "
                "to enable them."
            )
    else:
        metrics = pd.DataFrame(columns=["site_no"])
        used_mode = "missing"
        warnings.append(
            "This dataset has no daily tables yet, so every metric is blank. "
            "Run the download step to build them."
        )

    table = _join_metrics(meta, metrics)

    # Column order comes from the schema; legacy extras (site_export_id) are
    # kept right after the site number where a reader expects an identifier.
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
        "mode_label": _MODE_LABELS.get(used_mode, used_mode),
        "recompute_enabled": mode["recompute_enabled"],
        "warnings": warnings,
        "n_total": int(n_total),
        "n_filtered": int(len(table)),
        "months": sorted(months) if months else None,
        # Reported on every response, not just when it differs from the
        # default: this threshold blanks MI for short records, and a reader
        # comparing against another analysis needs to know it was applied.
        "min_paired_days": int(min_paired_days),
    }
    return table, info


def _join_metrics(meta: pd.DataFrame, metrics: pd.DataFrame) -> pd.DataFrame:
    """Attach metrics to site metadata on a canonical site key.

    The two sides spell site numbers differently and always have. Metadata runs
    through ``normalize_usgs_site_no`` (leading zeros stripped, so the demo's
    several CSV exports agree with each other), while a wizard dataset's daily
    tables carry the full NWIS id straight from ``usgs_<id>_all_obs.csv``.
    Joining on the raw column therefore matched nothing for any site whose id
    begins with a zero, which is most of the eastern US, and every median and
    MI came back blank with no error anywhere.

    Normalizing into a separate key fixes the join without rewriting the
    displayed id: the table keeps showing the site number the user would
    actually paste into the USGS site page.
    """
    meta = meta.copy()
    meta[_JOIN] = meta["site_no"].astype(str).map(normalize_usgs_site_no)

    if metrics is None or metrics.empty or "site_no" not in metrics.columns:
        # Nothing to attach; the caller still needs the metadata frame back so
        # the metric columns can be filled in as missing further down.
        return meta.drop(columns=[_JOIN])

    metrics = metrics.copy()
    metrics[_JOIN] = metrics["site_no"].astype(str).map(normalize_usgs_site_no)
    metrics = metrics.drop(columns=["site_no"])
    # A duplicate key would fan the metadata row out into several table rows.
    metrics = metrics.drop_duplicates(subset=[_JOIN], keep="first")

    return meta.merge(metrics, on=_JOIN, how="left").drop(columns=[_JOIN])


_MODE_LABELS = {
    "recompute": "recomputed from daily data",
    "fallback": "full-window values",
    "missing": "no daily data",
}


def _join(items: list[str]) -> str:
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]
