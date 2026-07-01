"""Recompute per-site medians and mutual information over a date/season slice.

The MI estimator is a faithful port of
``nitro/bubble_map_mutual_information.py::mutual_information_flow_no3`` (sklearn
k-NN ``mutual_info_regression``, values in nats). Medians and counts mirror the
research1 ``collect_*`` aggregations, just computed on an in-memory slice of the
cached daily tables instead of re-reading the raw CSVs.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

try:
    from sklearn.feature_selection import mutual_info_regression
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "explorer metrics require scikit-learn (pip install scikit-learn)"
    ) from e

DEFAULT_MIN_PAIRED_DAYS = 30

# Output column names (match merged_site_data.csv + DO CSVs where they overlap).
MEDIAN_FLOW_COL = "median_00060_Mean"
MEDIAN_NO3_COL = "median_no3no2"
MEDIAN_DO_COL = "median_do_mg_l"
MI_FLOW_NO3_COL = "mutual_information_flow_no3"
MI_NO3_DO_COL = "mutual_information_no3_do"


def mutual_information(x, y, *, random_state: int = 0) -> float:
    """MI between two paired, equal-length daily series. NaN if too few points."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    n = len(x)
    if n < 4:
        return float("nan")
    if np.nanstd(x) < 1e-12 or np.nanstd(y) < 1e-12:
        return 0.0
    mi = mutual_info_regression(
        x.reshape(-1, 1),
        y,
        random_state=random_state,
        n_neighbors=min(3, n - 1),
    )[0]
    return float(mi)


def _slice(df: pd.DataFrame, start, end, months) -> pd.DataFrame:
    """Restrict a daily table to a date window and/or a set of calendar months."""
    if df is None or df.empty:
        return df if df is not None else pd.DataFrame()
    out = df
    dt = pd.to_datetime(out["datetime"])
    mask = pd.Series(True, index=out.index)
    if start is not None:
        mask &= dt >= pd.Timestamp(start)
    if end is not None:
        mask &= dt <= pd.Timestamp(end)
    if months:
        mask &= dt.dt.month.isin(list(months))
    return out[mask]


def _median_count(df: pd.DataFrame, value_col: str, med_name: str, cnt_name: str) -> pd.DataFrame:
    cols = ["site_no", med_name, cnt_name]
    if df is None or df.empty:
        return pd.DataFrame(columns=cols)
    g = df.groupby("site_no", as_index=False).agg(
        **{med_name: (value_col, "median"), cnt_name: (value_col, "count")}
    )
    return g


def _paired(left: pd.DataFrame, right: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Inner-join two daily tables on (site_no, datetime), dropping NaN in cols."""
    if left is None or right is None or left.empty or right.empty:
        return pd.DataFrame(columns=["site_no", "datetime", *cols])
    return left.merge(right, on=["site_no", "datetime"], how="inner").dropna(subset=cols)


def _mi_from_paired(
    paired: pd.DataFrame,
    x_col: str,
    y_col: str,
    mi_name: str,
    n_name: str,
    min_paired_days: int,
) -> pd.DataFrame:
    """Per-site MI over an already-paired daily table."""
    cols = ["site_no", mi_name, n_name]
    if paired is None or paired.empty:
        return pd.DataFrame(columns=cols)
    rows = []
    floor = max(4, min_paired_days)
    for site_no, sub in paired.groupby("site_no"):
        n = len(sub)
        mi = (
            mutual_information(sub[x_col].to_numpy(), sub[y_col].to_numpy())
            if n >= floor
            else np.nan
        )
        rows.append({"site_no": site_no, mi_name: mi, n_name: n})
    return pd.DataFrame(rows)


def compute_site_metrics(
    daily_flow: pd.DataFrame,
    daily_no3: pd.DataFrame,
    daily_do: pd.DataFrame,
    *,
    start=None,
    end=None,
    months=None,
    min_paired_days: int = DEFAULT_MIN_PAIRED_DAYS,
) -> pd.DataFrame:
    """Per-site medians + MI over a date/month slice. Index-free, keyed on site_no."""
    f = _slice(daily_flow, start, end, months)
    c = _slice(daily_no3, start, end, months)
    d = _slice(daily_do, start, end, months)

    flow_stats = _median_count(f, "flow", MEDIAN_FLOW_COL, "n_flow_obs")
    no3_stats = _median_count(c, "no3_combined", MEDIAN_NO3_COL, "n_combined_days")
    do_stats = _median_count(d, "do_mg_l", MEDIAN_DO_COL, "n_do_days")

    # MI(flow, NO3+NO2): days with both flow and combined NO3+NO2.
    paired_fn = _paired(f, c, ["flow", "no3_combined"])
    mi_fn = _mi_from_paired(
        paired_fn, "flow", "no3_combined",
        MI_FLOW_NO3_COL, "n_paired_days_flow_no3", min_paired_days,
    )
    # MI(NO3+NO2, DO): research1 derives its NO3+NO2 series from the flow-paired
    # daily table, so DO is matched only on days that also had flow.
    no3_for_do = paired_fn[["site_no", "datetime", "no3_combined"]]
    paired_nd = _paired(no3_for_do, d, ["no3_combined", "do_mg_l"])
    mi_nd = _mi_from_paired(
        paired_nd, "no3_combined", "do_mg_l",
        MI_NO3_DO_COL, "n_paired_days_no3_do", min_paired_days,
    )

    out = flow_stats
    for part in (no3_stats, do_stats, mi_fn, mi_nd):
        out = out.merge(part, on="site_no", how="outer")
    return out
