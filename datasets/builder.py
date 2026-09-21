"""Build per-group daily tables (Parquet) from a dataset's raw downloads.

For each group and each (site, day) the value is the mean of every daily-Mean
column belonging to that group, after sentinel cleaning and per-code unit
conversion (see ``datasets/units.py``).

Two scoping rules matter for correctness, because ``raw/`` accumulates files
across runs and is never pruned:

* only the dataset's currently selected sites are read, so narrowing a
  selection and rebuilding does not silently keep the sites you dropped;
* rows are clipped to the dataset's date window, so narrowing the window does
  not leave the explorer computing medians over data the dataset no longer
  claims to cover.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .models import Dataset
from .units import ACTION_CONVERT, ACTION_EXCLUDE, apply_conversion, plan_group_units

NWIS_SENTINELS = (-999999.0, -99999.0)


def _mean_cols_for_code(columns, code: str, canonical_only: bool = False) -> list[str]:
    """Daily Mean columns belonging to one parameter code, never a *_cd flag.

    ``canonical_only`` keeps just the primary ``<code>_Mean`` column, dropping
    labeled auxiliaries such as ``00060_index velocity_Mean``.
    """
    if canonical_only:
        return [f"{code}_Mean"] if f"{code}_Mean" in columns else []
    return [
        c
        for c in columns
        if not c.endswith("_cd") and "Mean" in c and c.startswith(f"{code}_")
    ]


def _clean(series: pd.Series) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce").astype(float)
    for v in NWIS_SENTINELS:
        s = s.replace(v, np.nan)
    return s


def _raw_paths(dataset: Dataset) -> list:
    """Raw CSVs for the sites this dataset currently selects.

    ``raw/`` may hold files from an earlier, wider selection. Globbing it
    wholesale would fold those sites back into the daily tables even though the
    dataset no longer includes them.
    """
    selected = list(dataset.sites.filter(selected=True).values_list("site_no", flat=True))
    paths = []
    for site_no in selected:
        p = dataset.raw_dir / f"usgs_{site_no}_all_obs.csv"
        if p.is_file():
            paths.append(p)
    return sorted(paths)


def build_daily_tables(dataset: Dataset, progress=None, log=None) -> dict:
    """Read the selected sites' CSVs once and write daily_g<pos>.parquet per group."""
    groups = dataset.groups_ordered()
    flow_available = "00060" in dataset.all_pmcodes()

    plans, unit_report = {}, []
    for g in groups:
        _target, actions, report = plan_group_units(g.pmcodes, flow_available)
        plans[g.position] = actions
        for r in report:
            unit_report.append({"group": g.position, "group_label": g.label, **r})
            if r["action"] == "excluded" and log:
                log(f"g{g.position} {g.label}: code {r['code']} excluded, {r['detail']}")

    window_start = pd.Timestamp(dataset.start_date)
    window_end = pd.Timestamp(dataset.end_date)

    chunks: dict[int, list[pd.DataFrame]] = {g.position: [] for g in groups}
    paths = _raw_paths(dataset)
    if not paths and log:
        log(
            "No raw CSVs found for the selected sites. Nothing to build; "
            "run the download step first."
        )

    for idx, csv_path in enumerate(paths):
        if progress and (idx % 5 == 0 or idx == len(paths) - 1):
            # Building is the second half of the download job, so report into
            # the top of the bar rather than pinning it at 99 percent.
            frac = 0.9 + 0.1 * (idx + 1) / max(1, len(paths))
            progress(frac, f"Building daily tables ({idx + 1} of {len(paths)})")

        df = pd.read_csv(csv_path, parse_dates=["datetime"])
        if isinstance(df["datetime"].dtype, pd.DatetimeTZDtype):
            df["datetime"] = df["datetime"].dt.tz_convert(None)
        df = df[(df["datetime"] >= window_start) & (df["datetime"] <= window_end)]
        if df.empty:
            continue
        df["site_no"] = df["site_no"].astype(str)

        # Load-based conversions divide by the primary daily discharge series.
        flow_cols = _mean_cols_for_code(df.columns, "00060", canonical_only=True)
        flow = _clean(df[flow_cols[0]]) if flow_cols else None

        for g in groups:
            actions = plans[g.position]
            converted: list[pd.Series] = []
            for code in g.codes():
                act = actions.get(code, {"action": ACTION_EXCLUDE})
                if act["action"] == ACTION_EXCLUDE:
                    continue
                for col in _mean_cols_for_code(df.columns, code, g.require_canonical):
                    vals = _clean(df[col])
                    if act["action"] == ACTION_CONVERT:
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
    empty_groups = []
    for g in groups:
        parts = chunks[g.position]
        if parts:
            daily = (
                pd.concat(parts, ignore_index=True)
                .groupby(["site_no", "datetime"], as_index=False)["value"]
                .mean()
            )
        else:
            daily = pd.DataFrame(
                {
                    "site_no": pd.Series(dtype="string"),
                    "datetime": pd.Series(dtype="datetime64[ns]"),
                    "value": pd.Series(dtype="float64"),
                }
            )
            empty_groups.append(f"g{g.position} {g.label}")
        daily.to_parquet(dataset.daily_parquet(g.position), index=False)
        counts[f"g{g.position}"] = {
            "rows": len(daily),
            "sites": int(daily["site_no"].nunique()) if not daily.empty else 0,
        }
        if log:
            log(
                f"g{g.position} {g.label}: {len(daily)} daily rows, "
                f"{counts[f'g{g.position}']['sites']} sites"
            )

    if empty_groups:
        unit_report.append(
            {
                "group": "",
                "group_label": "",
                "code": "",
                "action": "excluded",
                "detail": (
                    "No daily values were built for: "
                    + ", ".join(empty_groups)
                    + ". Check the excluded codes above and the date window."
                ),
            }
        )

    dataset.unit_report = unit_report
    dataset.save(update_fields=["unit_report", "updated_at"])
    return counts
