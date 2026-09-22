"""Static per-site metadata and offline fallback metrics, from committed CSVs.

These small CSVs (in ``data/``) ship with the repo, so the app always has site
coordinates, names, region and HUC2 without touching the multi-hundred-megabyte
raw downloads. When the daily cache is absent, ``load_fallback_metrics`` serves
the original study's full-window numbers so the demo still renders.

The loaders are memoized, so every public function hands back a defensive copy:
callers routinely add columns to what they get, and a shared frame would let
one request's scratch column leak into the next.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd
from django.conf import settings

from .conversions import normalize_usgs_site_no, display_usgs_site_no
from .regions import site_location_type_label
from .metrics import (
    MEDIAN_FLOW_COL,
    MEDIAN_NO3_COL,
    MEDIAN_DO_COL,
    MI_FLOW_NO3_COL,
    MI_NO3_DO_COL,
)

# Legacy study CSV columns mapped onto the generalized demo columns.
# Demo groups: g1 = NO3+NO2, g2 = Streamflow, g3 = Dissolved Oxygen.
LEGACY_TO_GENERAL = {
    MEDIAN_NO3_COL: "median_g1",
    "n_combined_days": "n_g1",
    MEDIAN_FLOW_COL: "median_g2",
    "n_flow_obs": "n_g2",
    MEDIAN_DO_COL: "median_g3",
    "n_do_days": "n_g3",
    MI_FLOW_NO3_COL: "mi_g1_g2",
    "n_paired_days_flow_no3": "n_paired_g1_g2",
    MI_NO3_DO_COL: "mi_g1_g3",
    "n_paired_days_no3_do": "n_paired_g1_g3",
}

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
        # Show the id USGS uses. Normalizing here stripped the leading zeros
        # off every demo site, so the table and the CSV disagreed with the
        # wizard datasets about the same site and neither id pasted into the
        # USGS site page. Joins build their own key in service.py.
        df["site_no"] = df["site_no"].map(display_usgs_site_no).astype(str)
    return df


@lru_cache(maxsize=1)
def _site_metadata_cached() -> pd.DataFrame:
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
    # huc2 may parse as float ("5.0"); normalize to the zero-padded 2-char code.
    huc = meta["huc2"].astype(str).str.split(".").str[0].str.strip()
    meta["huc2"] = huc.where(huc.str.isdigit(), pd.NA)
    meta.loc[meta["huc2"].notna(), "huc2"] = meta.loc[meta["huc2"].notna(), "huc2"].str.zfill(2)

    # Fill region for any site missing one (e.g. DO-only) from its coordinates.
    need = meta["location_type"].isna() | (meta["location_type"].astype(str).str.strip() == "")
    if need.any():
        meta.loc[need, "location_type"] = meta.loc[need].apply(
            lambda r: site_location_type_label(r["site_no"], r["dec_lat_va"], r["dec_long_va"]),
            axis=1,
        )
    return meta[META_COLUMNS].reset_index(drop=True)


@lru_cache(maxsize=1)
def _fallback_metrics_cached() -> pd.DataFrame:
    """Full-window per-site metrics from the committed CSVs (used when no raw data).

    Columns use the legacy study names; ``load_fallback_metrics_general``
    renames them to the generalized median_g*/mi_g* scheme.
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


def load_site_metadata() -> pd.DataFrame:
    """One row per demo site, as a fresh copy the caller may modify."""
    return _site_metadata_cached().copy()


def load_fallback_metrics() -> pd.DataFrame:
    """Full-window demo metrics under the legacy column names (fresh copy)."""
    return _fallback_metrics_cached().copy()


def load_fallback_metrics_general() -> pd.DataFrame:
    """Demo fallback metrics under the generalized median_g*/mi_g* names."""
    return load_fallback_metrics().rename(columns=LEGACY_TO_GENERAL)


def load_dataset_metadata(dataset) -> pd.DataFrame:
    """Per-site metadata for a dataset.

    Demo datasets read the committed CSVs, which carry the study's own HUC2
    region names. Extracted datasets are built from their CandidateSite rows:
    region from coordinates, HUC2 from the inventory's huc_cd, and region names
    from the static WBD table.
    """
    if dataset.is_demo:
        return load_site_metadata()

    from datasets.catalog import HUC2_REGION_NAMES

    rows = []
    for s in dataset.sites.filter(selected=True):
        huc2 = s.huc2
        rows.append(
            {
                # The real NWIS id, leading zeros and all, because this is what
                # the user reads off the table and pastes into a USGS page.
                # The metrics join canonicalizes separately (see
                # explorer.core.service._join_metrics), so keeping the true
                # spelling here costs nothing.
                "site_no": str(s.site_no),
                "station_nm": s.station_nm,
                "dec_lat_va": s.dec_lat_va,
                "dec_long_va": s.dec_long_va,
                "location_type": site_location_type_label(s.site_no, s.dec_lat_va, s.dec_long_va),
                "huc2": huc2 or pd.NA,
                "huc2_region_name": HUC2_REGION_NAMES.get(huc2, pd.NA) if huc2 else pd.NA,
            }
        )
    if not rows:
        return pd.DataFrame(
            columns=[
                "site_no", "station_nm", "dec_lat_va", "dec_long_va",
                "location_type", "huc2", "huc2_region_name",
            ]
        )
    return pd.DataFrame(rows).drop_duplicates(subset=["site_no"]).reset_index(drop=True)


def clear_caches() -> None:
    _site_metadata_cached.cache_clear()
    _fallback_metrics_cached.cache_clear()
