"""Static per-site metadata + offline fallback metrics, from committed CSVs.

These small CSVs (``data/``) ship with the repo, so the app always has site
coordinates, names, region, and HUC2 without touching the 436 MB raw data. When
raw data is absent, ``load_fallback_metrics`` serves the research1 full-window
numbers so the app still renders.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd
from django.conf import settings

from .conversions import normalize_usgs_site_no
from .regions import site_location_type_label
from .metrics import (
    MEDIAN_FLOW_COL,
    MEDIAN_NO3_COL,
    MEDIAN_DO_COL,
    MI_FLOW_NO3_COL,
    MI_NO3_DO_COL,
)

MERGED_CSV = "merged_site_data.csv"
DO_MEDIAN_CSV = "site_median_do.csv"
DO_MI_CSV = "sites_mutual_information_no3_do.csv"

META_COLUMNS = [
    "site_no",
    "site_export_id",
    "station_nm",
    "dec_lat_va",
    "dec_long_va",
    "location_type",
    "huc2",
    "huc2_region_name",
]


def _data_dir() -> Path:
    return Path(settings.DATA_DIR)


def _read_csv(name: str) -> pd.DataFrame:
    path = _data_dir() / name
    if not path.is_file():
        return pd.DataFrame()
    df = pd.read_csv(path, dtype={"site_no": str})
    if "site_no" in df.columns:
        df["site_no"] = df["site_no"].map(normalize_usgs_site_no).astype(str)
    return df


@lru_cache(maxsize=1)
def load_site_metadata() -> pd.DataFrame:
    """One row per site with coords/name/region/HUC2. Universe = merged + DO sites."""
    merged = _read_csv(MERGED_CSV)
    do_med = _read_csv(DO_MEDIAN_CSV)

    frames = []
    if not merged.empty:
        keep = [c for c in META_COLUMNS if c in merged.columns]
        frames.append(merged[keep])
    if not do_med.empty:
        keep = [c for c in ["site_no", "station_nm", "dec_lat_va", "dec_long_va"] if c in do_med.columns]
        frames.append(do_med[keep])

    if not frames:
        return pd.DataFrame(columns=META_COLUMNS)

    meta = pd.concat(frames, ignore_index=True)
    meta = meta.sort_index().drop_duplicates(subset=["site_no"], keep="first")

    for col in META_COLUMNS:
        if col not in meta.columns:
            meta[col] = pd.NA
    meta["dec_lat_va"] = pd.to_numeric(meta["dec_lat_va"], errors="coerce")
    meta["dec_long_va"] = pd.to_numeric(meta["dec_long_va"], errors="coerce")

    # Fill region for any site missing one (e.g. DO-only) from its coordinates.
    need = meta["location_type"].isna() | (meta["location_type"].astype(str).str.strip() == "")
    if need.any():
        meta.loc[need, "location_type"] = meta.loc[need].apply(
            lambda r: site_location_type_label(r["site_no"], r["dec_lat_va"], r["dec_long_va"]),
            axis=1,
        )
    return meta[META_COLUMNS].reset_index(drop=True)


@lru_cache(maxsize=1)
def load_fallback_metrics() -> pd.DataFrame:
    """Full-window per-site metrics from the committed CSVs (used when no raw data).

    Columns match ``metrics.compute_site_metrics`` output so downstream code is
    identical on both paths.
    """
    merged = _read_csv(MERGED_CSV)
    do_med = _read_csv(DO_MEDIAN_CSV)
    do_mi = _read_csv(DO_MI_CSV)

    if merged.empty:
        return pd.DataFrame(columns=["site_no"])

    flow_no3 = merged.rename(
        columns={
            "mutual_information": MI_FLOW_NO3_COL,
            "n_paired_days": "n_paired_days_flow_no3",
        }
    )
    keep = [
        c
        for c in [
            "site_no",
            MEDIAN_FLOW_COL,
            "n_flow_obs",
            MEDIAN_NO3_COL,
            "n_combined_days",
            MI_FLOW_NO3_COL,
            "n_paired_days_flow_no3",
        ]
        if c in flow_no3.columns
    ]
    out = flow_no3[keep].copy()

    if not do_med.empty:
        dm = do_med[[c for c in ["site_no", MEDIAN_DO_COL, "n_do_days"] if c in do_med.columns]]
        out = out.merge(dm, on="site_no", how="outer")
    if not do_mi.empty:
        dmi = do_mi.rename(
            columns={
                "mutual_information": MI_NO3_DO_COL,
                "n_paired_days": "n_paired_days_no3_do",
            }
        )
        dmi = dmi[[c for c in ["site_no", MI_NO3_DO_COL, "n_paired_days_no3_do"] if c in dmi.columns]]
        out = out.merge(dmi, on="site_no", how="outer")

    return out


def clear_caches() -> None:
    load_site_metadata.cache_clear()
    load_fallback_metrics.cache_clear()
