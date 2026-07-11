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


def compute_group_metrics(
    daily_by_pos: dict[int, pd.DataFrame],
    *,
    pairing_gates: dict[str, int] | None = None,
    start=None,
    end=None,
    months=None,
    min_paired_days: int = DEFAULT_MIN_PAIRED_DAYS,
) -> pd.DataFrame:
    """Generalized per-site metrics for N parameter groups.

    ``daily_by_pos`` maps group position -> daily table (site_no, datetime, value).
    Output columns: median_g<pos>, n_g<pos> per group; mi_g<i>_g<j>,
    n_paired_g<i>_g<j> for every pair (i < j).

    ``pairing_gates`` maps "i,j" to a rule dict (an int is shorthand for
    {"gate": int}): "gate" restricts group i's days to those also paired with
    the gate group before pairing with j (research1 paired DO against the
    flow-gated NO3 series); "x" picks which group's series is passed as the
    estimator's X (sklearn's kNN MI is not numerically symmetric — research1
    used flow as X for the flow/NO3 pair). New datasets use no rules.
    """
    from itertools import combinations

    positions = sorted(daily_by_pos)
    sliced = {pos: _slice(daily_by_pos[pos], start, end, months) for pos in positions}
    gates = pairing_gates or {}

    out: pd.DataFrame | None = None
    for pos in positions:
        stats = _median_count(sliced[pos], "value", f"median_g{pos}", f"n_g{pos}")
        out = stats if out is None else out.merge(stats, on="site_no", how="outer")

    def renamed(pos: int) -> pd.DataFrame:
        df = sliced[pos]
        if df is None or df.empty:
            return pd.DataFrame(columns=["site_no", "datetime", f"v{pos}"])
        return df.rename(columns={"value": f"v{pos}"})

    for i, j in combinations(positions, 2):
        rule = gates.get(f"{i},{j}")
        if isinstance(rule, int):  # legacy shorthand
            rule = {"gate": rule}
        rule = rule or {}
        gate = rule.get("gate")
        x_pos = rule.get("x", i)
        y_pos = j if x_pos == i else i

        left = renamed(i)
        if gate is not None and gate in sliced:
            gated = _paired(left, renamed(gate), [f"v{i}", f"v{gate}"])
            left = gated[["site_no", "datetime", f"v{i}"]] if not gated.empty else left.iloc[0:0]
        pr = _paired(left, renamed(j), [f"v{i}", f"v{j}"])
        mi = _mi_from_paired(
            pr, f"v{x_pos}", f"v{y_pos}", f"mi_g{i}_g{j}", f"n_paired_g{i}_g{j}", min_paired_days
        )
        if out is None:
            out = mi
        else:
            out = out.merge(mi, on="site_no", how="outer")

    return out if out is not None else pd.DataFrame(columns=["site_no"])
