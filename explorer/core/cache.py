"""Parquet cache of the daily tables + memoized per-site metric recompute.

Parsing the 436 MB raw sitedata is slow, so ``build_caches`` does it once and
writes three small Parquet files. ``compute_metrics`` then recomputes medians /
MI over any date or season window straight from the cached tables (memoized by
the recompute-affecting parameters). When no cache and no raw data are present,
callers fall back to ``metadata.load_fallback_metrics``.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd
from django.conf import settings

from . import loader, metadata
from .metrics import compute_site_metrics

FLOW_PARQUET = "daily_flow.parquet"
NO3_PARQUET = "daily_no3.parquet"
DO_PARQUET = "daily_do.parquet"


def _cache_dir() -> Path:
    return Path(settings.CACHE_DIR)


def raw_sitedata_available() -> bool:
    return Path(settings.SITEDATA_DIR).is_dir()


def caches_built() -> bool:
    d = _cache_dir()
    return all((d / n).is_file() for n in (FLOW_PARQUET, NO3_PARQUET, DO_PARQUET))


def build_caches() -> dict:
    """Parse raw sitedata into the three daily Parquet tables. Returns row counts."""
    base = Path(settings.SITEDATA_DIR)
    if not base.is_dir():
        raise FileNotFoundError(
            f"Raw sitedata not found at {base}. Set NITRO_DATA_ROOT to your "
            "nitro-research checkout (it must contain sitedata/)."
        )
    start, end = settings.DATE_START, settings.DATE_END

    qualifying = loader.qualifying_site_nos(base, start, end)
    daily_flow, daily_no3 = loader.build_daily_flow_no3(base, start, end, qualifying)
    # DO is restricted to its own folder; keep all DO sites (some may be DO-only).
    daily_do = loader.build_daily_do(base, start, end, sites=None)

    out = _cache_dir()
    out.mkdir(parents=True, exist_ok=True)
    daily_flow.to_parquet(out / FLOW_PARQUET, index=False)
    daily_no3.to_parquet(out / NO3_PARQUET, index=False)
    daily_do.to_parquet(out / DO_PARQUET, index=False)

    clear_memo()
    load_daily.cache_clear()
    return {
        "qualifying_sites": len(qualifying),
        "daily_flow_rows": len(daily_flow),
        "daily_no3_rows": len(daily_no3),
        "daily_do_rows": len(daily_do),
        "flow_sites": int(daily_flow["site_no"].nunique()) if not daily_flow.empty else 0,
        "no3_sites": int(daily_no3["site_no"].nunique()) if not daily_no3.empty else 0,
        "do_sites": int(daily_do["site_no"].nunique()) if not daily_do.empty else 0,
    }


@lru_cache(maxsize=1)
def load_daily() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Read the three cached daily tables (in-memory cached)."""
    d = _cache_dir()
    flow = pd.read_parquet(d / FLOW_PARQUET)
    no3 = pd.read_parquet(d / NO3_PARQUET)
    do = pd.read_parquet(d / DO_PARQUET)
    for df in (flow, no3, do):
        df["datetime"] = pd.to_datetime(df["datetime"])
    return flow, no3, do


@lru_cache(maxsize=64)
def _compute_metrics_cached(
    start: str | None,
    end: str | None,
    months: tuple[int, ...] | None,
    min_paired_days: int,
) -> pd.DataFrame:
    flow, no3, do = load_daily()
    return compute_site_metrics(
        flow, no3, do,
        start=start, end=end,
        months=set(months) if months else None,
        min_paired_days=min_paired_days,
    )


def compute_metrics(
    *,
    start: str | None = None,
    end: str | None = None,
    months=None,
    min_paired_days: int = 30,
) -> pd.DataFrame:
    """Recompute per-site metrics from the cache (memoized). Returns a copy."""
    months_key = tuple(sorted(months)) if months else None
    return _compute_metrics_cached(start, end, months_key, int(min_paired_days)).copy()


def clear_memo() -> None:
    _compute_metrics_cached.cache_clear()
    metadata.clear_caches()
