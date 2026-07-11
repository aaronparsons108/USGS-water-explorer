"""Per-dataset daily-table loading + memoized metric recompute.

Every dataset's daily tables are parquet files of (site_no, datetime, value),
one per parameter group. The demo dataset maps onto the legacy research1 cache
(``.cache/daily_{flow,no3,do}.parquet`` built by ``manage.py build_cache``) so
its numbers keep matching the original exports; when even those are absent the
explorer falls back to the committed summary CSVs (see metadata.py).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd
from django.conf import settings

from . import loader, metadata
from .metrics import compute_group_metrics

# Legacy research1 cache files (demo dataset).
FLOW_PARQUET = "daily_flow.parquet"
NO3_PARQUET = "daily_no3.parquet"
DO_PARQUET = "daily_do.parquet"
# Demo group positions: g1 = NO3+NO2, g2 = Streamflow, g3 = Dissolved Oxygen.
_DEMO_FILES = {1: (NO3_PARQUET, "no3_combined"), 2: (FLOW_PARQUET, "flow"), 3: (DO_PARQUET, "do_mg_l")}


def _cache_dir() -> Path:
    return Path(settings.CACHE_DIR)


def raw_sitedata_available() -> bool:
    return Path(settings.SITEDATA_DIR).is_dir()


def legacy_caches_built() -> bool:
    d = _cache_dir()
    return all((d / n).is_file() for n in (FLOW_PARQUET, NO3_PARQUET, DO_PARQUET))


def dataset_daily_available(dataset) -> bool:
    """Do daily tables exist for this dataset?"""
    if dataset.is_demo:
        return legacy_caches_built()
    groups = dataset.groups_ordered()
    return bool(groups) and all(dataset.daily_parquet(g.position).is_file() for g in groups)


def build_caches() -> dict:
    """Legacy demo path: parse research1 raw sitedata into the 3 parquet tables."""
    base = Path(settings.SITEDATA_DIR)
    if not base.is_dir():
        raise FileNotFoundError(
            f"Raw sitedata not found at {base}. Set NITRO_DATA_ROOT to your "
            "nitro-research checkout (it must contain sitedata/)."
        )
    start, end = settings.DATE_START, settings.DATE_END

    qualifying = loader.qualifying_site_nos(base, start, end)
    daily_flow, daily_no3 = loader.build_daily_flow_no3(base, start, end, qualifying)
    daily_do = loader.build_daily_do(base, start, end, sites=None)

    out = _cache_dir()
    out.mkdir(parents=True, exist_ok=True)
    daily_flow.to_parquet(out / FLOW_PARQUET, index=False)
    daily_no3.to_parquet(out / NO3_PARQUET, index=False)
    daily_do.to_parquet(out / DO_PARQUET, index=False)

    clear_memo()
    return {
        "qualifying_sites": len(qualifying),
        "daily_flow_rows": len(daily_flow),
        "daily_no3_rows": len(daily_no3),
        "daily_do_rows": len(daily_do),
        "flow_sites": int(daily_flow["site_no"].nunique()) if not daily_flow.empty else 0,
        "no3_sites": int(daily_no3["site_no"].nunique()) if not daily_no3.empty else 0,
        "do_sites": int(daily_do["site_no"].nunique()) if not daily_do.empty else 0,
    }


@lru_cache(maxsize=8)
def _load_daily_by_slug(slug: str) -> dict[int, pd.DataFrame]:
    from datasets.models import Dataset

    dataset = Dataset.objects.get(slug=slug)
    out: dict[int, pd.DataFrame] = {}
    if dataset.is_demo:
        d = _cache_dir()
        for pos, (name, value_col) in _DEMO_FILES.items():
            df = pd.read_parquet(d / name).rename(columns={value_col: "value"})
            df["datetime"] = pd.to_datetime(df["datetime"])
            out[pos] = df
        return out
    for g in dataset.groups_ordered():
        df = pd.read_parquet(dataset.daily_parquet(g.position))
        df["datetime"] = pd.to_datetime(df["datetime"])
        out[g.position] = df
    return out


@lru_cache(maxsize=64)
def _compute_metrics_cached(
    slug: str,
    start: str | None,
    end: str | None,
    months: tuple[int, ...] | None,
    min_paired_days: int,
) -> pd.DataFrame:
    from datasets.models import Dataset

    dataset = Dataset.objects.get(slug=slug)  # slug determines pairing rules
    daily = _load_daily_by_slug(slug)
    return compute_group_metrics(
        daily,
        pairing_gates=dataset.pairing_gates or {},
        start=start,
        end=end,
        months=set(months) if months else None,
        min_paired_days=min_paired_days,
    )


def compute_metrics(
    dataset,
    *,
    start: str | None = None,
    end: str | None = None,
    months=None,
    min_paired_days: int = 30,
) -> pd.DataFrame:
    """Recompute per-site metrics for a dataset (memoized). Returns a copy."""
    months_key = tuple(sorted(months)) if months else None
    return _compute_metrics_cached(
        dataset.slug, start, end, months_key, int(min_paired_days)
    ).copy()


def clear_memo() -> None:
    _compute_metrics_cached.cache_clear()
    _load_daily_by_slug.cache_clear()
    metadata.clear_caches()
