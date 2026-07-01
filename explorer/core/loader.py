"""Parse raw research1 sitedata into tidy per-day, per-site tables.

These are faithful ports of:
  - nitro/heatmap_common.py::qualifying_site_nos / iter_qualifying_obs_frames
  - nitro/bubble_map_mutual_information.py::collect_daily_flow_no3_pairs
  - dissolved_oxygen/daily_do.py::collect_daily_do

The output tables are small enough to cache (Parquet) and slice in memory, so
medians and mutual information can be recomputed for any date/season window
without re-touching the 436 MB of raw CSVs.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .conversions import (
    TARGET_PMCODES,
    convert_no3no2_to_mg_per_l_as_n,
    clean_do_mg_l,
    normalize_usgs_site_no,
    pm_mean_columns,
    select_do_mean_columns,
)

DO_FOLDER = "00300site_data"


def _pmcode_from_folder(parent_name: str) -> str | None:
    pmcode = "".join(ch for ch in parent_name if ch.isdigit())
    if not pmcode or pmcode not in TARGET_PMCODES:
        return None
    return pmcode


def _window(df: pd.DataFrame, start, end, time_col: str = "datetime") -> pd.DataFrame:
    if isinstance(df[time_col].dtype, pd.DatetimeTZDtype):
        df[time_col] = df[time_col].dt.tz_convert(None)
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    return df[(df[time_col] >= start_ts) & (df[time_col] <= end_ts)]


def _iter_flow_no3_long(base_dir: Path, start, end, sites: set[str] | None):
    """Yield long-form (datetime, site_no, 00060_Mean, pm_value, pmcode) frames."""
    for csv_path in base_dir.rglob("usgs_*_all_obs.csv"):
        pmcode = _pmcode_from_folder(csv_path.parent.name)
        if pmcode is None:
            continue

        cols = list(pd.read_csv(csv_path, nrows=0).columns)
        if "00060_Mean" not in cols:
            continue
        pm_cols = pm_mean_columns(cols, pmcode)
        if not pm_cols:
            continue

        usecols = ["datetime", "site_no", "00060_Mean"] + pm_cols
        df = pd.read_csv(csv_path, usecols=usecols, parse_dates=["datetime"])
        df = _window(df, start, end)
        df = df[df["site_no"].astype(str).str.len() < 15]
        df["site_no"] = df["site_no"].map(normalize_usgs_site_no).astype(str)
        if sites is not None:
            df = df[df["site_no"].isin(sites)]
        if df.empty:
            continue

        long_df = df.melt(
            id_vars=["datetime", "site_no", "00060_Mean"],
            value_vars=pm_cols,
            var_name="pm_variable",
            value_name="pm_value",
        )
        long_df["pmcode"] = pmcode
        yield long_df


def qualifying_site_nos(base_dir: Path, start, end) -> set[str]:
    """Sites with >=1 non-null flow and >=1 non-null NO3+NO2 in the window."""
    flags: dict[str, list[bool]] = {}
    for long_df in _iter_flow_no3_long(base_dir, start, end, sites=None):
        g = long_df.copy()
        g["00060_Mean"] = g["00060_Mean"].replace(-999999, np.nan)
        g["pm_value"] = g["pm_value"].replace(-999999, np.nan)
        for site_no, sub in g.groupby("site_no"):
            if site_no not in flags:
                flags[site_no] = [False, False]
            flags[site_no][0] |= bool(sub["00060_Mean"].notna().any())
            flags[site_no][1] |= bool(sub["pm_value"].notna().any())
    out = {s for s, (has_flow, has_pm) in flags.items() if has_flow and has_pm}
    out.discard("")
    return out


def build_daily_flow_no3(
    base_dir: Path,
    start,
    end,
    sites: set[str] | None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build the daily flow and daily combined-NO3+NO2 tables in one scan.

    Returns ``(daily_flow, daily_no3)`` where:
      - ``daily_flow``: one row per (site_no, datetime) with mean daily flow over
        every flow-bearing day (mirrors collect_flow_stats' median pool, deduped
        across pmcode folders).
      - ``daily_no3``: one row per (site_no, datetime) with the daily combined
        NO3+NO2 (mg/L as N) -- the mean of all parameter means that day, after
        unit conversion -- mirroring collect_pm_site_medians.

    MI(flow, NO3+NO2) is then the inner join of these two on (site_no, datetime),
    exactly reproducing collect_daily_flow_no3_pairs.
    """
    empty_flow = pd.DataFrame(columns=["site_no", "datetime", "flow"])
    empty_no3 = pd.DataFrame(columns=["site_no", "datetime", "no3_combined"])

    records = list(_iter_flow_no3_long(base_dir, start, end, sites))
    if not records:
        return empty_flow, empty_no3

    all_pm = pd.concat(records, ignore_index=True)
    all_pm["00060_Mean"] = all_pm["00060_Mean"].replace(-999999, np.nan)
    all_pm["pm_value"] = all_pm["pm_value"].replace(-999999, np.nan)

    # Daily flow over all flow-bearing days (constant flow per day -> mean dedups).
    flow_src = all_pm.dropna(subset=["00060_Mean"])
    daily_flow = (
        flow_src.groupby(["site_no", "datetime"], as_index=False)
        .agg(flow=("00060_Mean", "mean"))
        if not flow_src.empty
        else empty_flow
    )

    # Daily combined NO3+NO2 (mg/L as N).
    all_pm["pm_value"] = convert_no3no2_to_mg_per_l_as_n(
        all_pm["pmcode"], all_pm["pm_value"], all_pm["00060_Mean"]
    )
    no3_src = all_pm.dropna(subset=["pm_value"])
    daily_no3 = (
        no3_src.groupby(["site_no", "datetime"], as_index=False)
        .agg(no3_combined=("pm_value", "mean"))
        if not no3_src.empty
        else empty_no3
    )

    return daily_flow, daily_no3


def build_daily_do(
    base_dir: Path,
    start,
    end,
    sites: set[str] | None,
) -> pd.DataFrame:
    """One row per (site_no, datetime) with cleaned daily DO (mg/L as O2)."""
    folder = base_dir / DO_FOLDER
    if not folder.is_dir():
        return pd.DataFrame(columns=["site_no", "datetime", "do_mg_l"])

    chunks: list[pd.DataFrame] = []
    for csv_path in sorted(folder.glob("usgs_*_all_obs.csv")):
        cols = list(pd.read_csv(csv_path, nrows=0).columns)
        time_col = next((c for c in ("datetime", "dateTime", "date_time") if c in cols), None)
        pm_cols = select_do_mean_columns(cols)
        if not time_col or not pm_cols:
            continue

        df = pd.read_csv(
            csv_path,
            usecols=[time_col, "site_no"] + pm_cols,
            parse_dates=[time_col],
            dtype={"site_no": str},
        )
        df = df.rename(columns={time_col: "datetime"})
        df = _window(df, start, end)
        df = df[df["site_no"].astype(str).str.len() < 15]
        df["site_no"] = df["site_no"].map(normalize_usgs_site_no).astype(str)
        if sites is not None:
            df = df[df["site_no"].isin(sites)]
        if df.empty:
            continue

        raw = df[pm_cols[0]].copy()
        for c in pm_cols[1:]:
            raw = raw.combine_first(df[c])
        out = pd.DataFrame(
            {
                "site_no": df["site_no"].to_numpy(),
                "datetime": df["datetime"].to_numpy(),
                "do_mg_l": clean_do_mg_l(raw).to_numpy(),
            }
        )
        out = out.dropna(subset=["do_mg_l"])
        if not out.empty:
            chunks.append(out)

    if not chunks:
        return pd.DataFrame(columns=["site_no", "datetime", "do_mg_l"])
    return pd.concat(chunks, ignore_index=True)
