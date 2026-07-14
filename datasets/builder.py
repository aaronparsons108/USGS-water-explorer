"""Build per-group daily tables (parquet) from a dataset's raw downloads.

For each group and each (site, day): value = mean of all that group's daily-Mean
columns present that day, after sentinel cleaning and per-code unit conversion
(datasets/units.py). Mirrors the research1 daily-combine rule from
bubble_map_mean_no3no2 / heatmap_NO3NO2 (melt all code Means, convert, mean per day).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .models import Dataset
from .units import apply_conversion, plan_group_units

NWIS_SENTINELS = (-999999.0, -99999.0)


def _mean_cols_for_code(columns, code: str, canonical_only: bool = False) -> list[str]:
    """Daily Mean columns belonging to one parameter code (never *_cd).

    ``canonical_only`` keeps just the primary ``<code>_Mean`` column, dropping
    labeled auxiliaries like ``00060_index velocity_Mean``.
    """
    if canonical_only:
        return [f"{code}_Mean"] if f"{code}_Mean" in columns else []
    out = []
    for c in columns:
        if c.endswith("_cd") or "Mean" not in c:
            continue
        if c == code or c.startswith(f"{code}_"):
            out.append(c)
    return out


def _clean(series: pd.Series) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce").astype(float)
    for v in NWIS_SENTINELS:
        s = s.replace(v, np.nan)
    return s


def build_daily_tables(dataset: Dataset, progress=None, log=None) -> dict:
    """Scan raw CSVs once; write daily_g<pos>.parquet per group. Returns counts."""
    groups = dataset.groups_ordered()
    flow_available = "00060" in dataset.all_pmcodes()

    plans, unit_report = {}, []
    for g in groups:
        target, actions, report = plan_group_units(g.pmcodes, flow_available)
        plans[g.position] = actions
        for r in report:
            unit_report.append({"group": g.position, "group_label": g.label, **r})

    chunks: dict[int, list[pd.DataFrame]] = {g.position: [] for g in groups}
    paths = sorted(dataset.raw_dir.glob("usgs_*_all_obs.csv"))
    for idx, csv_path in enumerate(paths):
        if progress and idx % 10 == 0:
            progress(idx / max(1, len(paths)), f"Building daily tables ({idx + 1}/{len(paths)})")
        df = pd.read_csv(csv_path, parse_dates=["datetime"])
        if isinstance(df["datetime"].dtype, pd.DatetimeTZDtype):
            df["datetime"] = df["datetime"].dt.tz_convert(None)
        df["site_no"] = df["site_no"].astype(str)

        # Load-based unit conversions divide by the primary daily discharge.
        flow_cols = _mean_cols_for_code(df.columns, "00060", canonical_only=True)
        flow = _clean(df[flow_cols[0]]) if flow_cols else None

        for g in groups:
            actions = plans[g.position]
            converted: list[pd.Series] = []
            for code in g.codes():
                act = actions.get(code, {"action": "exclude"})
                if act["action"] == "exclude":
                    continue
                for col in _mean_cols_for_code(df.columns, code, g.require_canonical):
                    vals = _clean(df[col])
                    if act["action"] == "convert":
                        vals = apply_conversion(vals, flow, act["conversion"])
                    converted.append(vals)
            if not converted:
                continue
            value = pd.concat(converted, axis=1).mean(axis=1)  # daily combine
            out = pd.DataFrame(
                {"site_no": df["site_no"], "datetime": df["datetime"], "value": value}
            ).dropna(subset=["value"])
            if not out.empty:
                chunks[g.position].append(out)

    dataset.store_dir.mkdir(parents=True, exist_ok=True)
    counts = {}
    for g in groups:
        parts = chunks[g.position]
        daily = (
            pd.concat(parts, ignore_index=True)
            .groupby(["site_no", "datetime"], as_index=False)["value"]
            .mean()
            if parts
            else pd.DataFrame(columns=["site_no", "datetime", "value"])
        )
        daily.to_parquet(dataset.daily_parquet(g.position), index=False)
        counts[f"g{g.position}"] = {
            "rows": len(daily),
            "sites": int(daily["site_no"].nunique()) if not daily.empty else 0,
        }
        if log:
            log(f"g{g.position} {g.label}: {len(daily)} daily rows, "
                f"{counts[f'g{g.position}']['sites']} sites")

    dataset.unit_report = unit_report
    dataset.save(update_fields=["unit_report", "updated_at"])
    return counts
