"""Per-dataset daily-table loading and memoized metric recompute.

Every dataset's daily tables are Parquet files of (site_no, datetime, value),
one per parameter group. The demo dataset maps onto the legacy study cache
(``.cache/daily_{flow,no3,do}.parquet``, built by ``manage.py build_cache``) so
its numbers keep matching the original exports; when even those are absent, the
explorer falls back to the committed summary CSVs (see metadata.py).

Both memoized layers are keyed on a fingerprint of the underlying files
(path, size, mtime), so rebuilding a Parquet table in another process is picked
up on the next request rather than silently serving stale metrics until the
server restarts.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd
from django.conf import settings

from . import loader, metadata
from .metrics import compute_group_metrics

# Legacy study cache files, used by the demo dataset.
FLOW_PARQUET = "daily_flow.parquet"
NO3_PARQUET = "daily_no3.parquet"
DO_PARQUET = "daily_do.parquet"
# Demo group positions: g1 = NO3+NO2, g2 = Streamflow, g3 = Dissolved Oxygen.
_DEMO_FILES = {
    1: (NO3_PARQUET, "no3_combined"),
    2: (FLOW_PARQUET, "flow"),
    3: (DO_PARQUET, "do_mg_l"),
}


def _cache_dir() -> Path:
    return Path(settings.CACHE_DIR)


def raw_sitedata_available() -> bool:
    return Path(settings.SITEDATA_DIR).is_dir()


def legacy_caches_built() -> bool:
    d = _cache_dir()
    return all((d / n).is_file() for n in (FLOW_PARQUET, NO3_PARQUET, DO_PARQUET))


def daily_paths(dataset) -> list[Path]:
    """Every Parquet file this dataset's metrics are derived from."""
    if dataset.is_demo:
        d = _cache_dir()
        return [d / name for name, _ in _DEMO_FILES.values()]
    return [dataset.daily_parquet(g.position) for g in dataset.groups_ordered()]


def dataset_daily_available(dataset) -> bool:
    """Do usable daily tables exist for this dataset?

    A group that downloaded nothing still writes an empty Parquet file. Treating
    that as "available" would put the explorer in recompute mode with silently
    blank metrics, so a zero-byte-of-rows table counts as unavailable.
    """
    paths = daily_paths(dataset)
    if not paths or not all(p.is_file() for p in paths):
        return False
    return any(_parquet_rows(str(p), _stamp(p)) > 0 for p in paths)


def _stamp(path: Path) -> tuple[int, int]:
    """(size, mtime_ns) fingerprint; changes whenever the file is rewritten."""
    try:
        st = path.stat()
    except OSError:
        return (-1, -1)
    return (st.st_size, st.st_mtime_ns)


def _fingerprint(dataset) -> tuple:
    return tuple((str(p), _stamp(p)) for p in daily_paths(dataset))


@lru_cache(maxsize=32)
def _parquet_rows(path: str, stamp: tuple) -> int:
    """Row count of a Parquet file, memoized against its fingerprint."""
    del stamp  # part of the cache key only
    try:
        import pyarrow.parquet as pq

        return int(pq.ParquetFile(path).metadata.num_rows)
    except Exception:
        try:
            return int(len(pd.read_parquet(path, columns=["site_no"])))
        except Exception:
            return 0


def build_caches() -> dict:
    """Legacy demo path: parse the study's raw sitedata into three Parquet tables."""
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
def _load_daily_cached(slug: str, fingerprint: tuple) -> dict[int, pd.DataFrame]:
    del fingerprint  # part of the cache key only
    from datasets.models import Dataset

    dataset = Dataset.objects.get(slug=slug)
    out: dict[int, pd.DataFrame] = {}
    if dataset.is_demo:
        d = _cache_dir()
        for pos, (name, value_col) in _DEMO_FILES.items():
            df = pd.read_parquet(d / name).rename(columns={value_col: "value"})
            df["site_no"] = df["site_no"].astype(str)
            df["datetime"] = pd.to_datetime(df["datetime"])
            out[pos] = df
        return out
    for g in dataset.groups_ordered():
        df = pd.read_parquet(dataset.daily_parquet(g.position))
        df["site_no"] = df["site_no"].astype(str)
        df["datetime"] = pd.to_datetime(df["datetime"])
        out[g.position] = df
    return out


@lru_cache(maxsize=64)
def _compute_metrics_cached(
    slug: str,
    fingerprint: tuple,
    gates_key: str,
    start: str | None,
    end: str | None,
    months: tuple[int, ...] | None,
    min_paired_days: int,
) -> pd.DataFrame:
    import json

    daily = _load_daily_cached(slug, fingerprint)
    return compute_group_metrics(
        daily,
        pairing_gates=json.loads(gates_key),
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
    import json

    months_key = tuple(sorted(months)) if months else None
    return _compute_metrics_cached(
        dataset.slug,
        _fingerprint(dataset),
        json.dumps(dataset.pairing_gates or {}, sort_keys=True),
        start,
        end,
        months_key,
        int(min_paired_days),
    ).copy()


def clear_memo() -> None:
    _compute_metrics_cached.cache_clear()
    _load_daily_cached.cache_clear()
    _parquet_rows.cache_clear()
    metadata.clear_caches()
