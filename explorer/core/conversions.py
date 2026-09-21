"""Unit conversions and column-selection rules for the demo (legacy) pipeline.

These are kept faithful to the original study so the demo dataset's metrics
match its published figures exactly. Datasets built through the wizard use the
general unit planner in ``datasets/units.py`` instead; nothing here runs for
them.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

import numpy as np
import pandas as pd

# --- NO3+NO2 (nitrate/nitrite) ---------------------------------------------
TARGET_PMCODES = {"99133", "00631", "91061", "91049", "83554", "00630"}

# Unit normalization to mg/L as nitrogen.
PERCFS_FACTOR_LBS_PER_DAY_TO_MG_L = 5.3937
PERCFS_FACTOR_TONS_PER_DAY_TO_MG_L = 0.002697

# --- Dissolved oxygen (00300) ----------------------------------------------
NWIS_DV_SENTINELS: frozenset[float] = frozenset({-999999.0, -99999.0})
DO_MG_L_MIN = 0.0
DO_MG_L_MAX = 25.0
_STAT_MEAN_RE = re.compile(r"^00300_\d+_Mean$")


def normalize_usgs_site_no(x) -> str:
    """Canonical site id for joins across sitedata vs metadata CSVs.

    Strips a trailing ``.0`` (pandas int->float reads) and leading zeros from
    digit-only ids so ``041482663`` and ``41482663`` match. Empty becomes "0".
    """
    s = str(x).strip()
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    if not s:
        return s
    if not s.isdigit():
        return s
    stripped = s.lstrip("0")
    return stripped if stripped else "0"


def pm_mean_columns(cols: list[str], pmcode: str) -> list[str]:
    """NO3+NO2 daily Mean columns for a given parameter code (excludes flow / _cd)."""
    return [
        c
        for c in cols
        if "Mean" in c
        and pmcode in c
        and not c.endswith("_cd")
        and not c.startswith("00060")
    ]


def convert_no3no2_to_mg_per_l_as_n(
    pmcode: "str | pd.Series",
    pm_value: pd.Series,
    flow_cfs: pd.Series,
) -> pd.Series:
    """Convert NO3+NO2 parameter values to mg/L as N.

    99133/00631/00630 are already mg/L as N. 91061/91049 are lb/day as N;
    83554 is short tons/day as N (both divided by flow * factor).
    """
    pmc = pmcode if isinstance(pmcode, pd.Series) else pd.Series(pmcode, index=pm_value.index)
    out = pd.to_numeric(pm_value, errors="coerce").astype(float).copy()
    flow = pd.to_numeric(flow_cfs, errors="coerce").astype(float)

    is_lbs_day = pmc.isin(["91061", "91049"])
    is_tons_day = pmc.eq("83554")
    load_based = is_lbs_day | is_tons_day

    bad_flow = (~np.isfinite(flow)) | (flow <= 0)
    out.loc[load_based & bad_flow] = np.nan
    out.loc[is_lbs_day & ~bad_flow] = (
        out.loc[is_lbs_day & ~bad_flow]
        / (flow.loc[is_lbs_day & ~bad_flow] * PERCFS_FACTOR_LBS_PER_DAY_TO_MG_L)
    )
    out.loc[is_tons_day & ~bad_flow] = (
        out.loc[is_tons_day & ~bad_flow]
        / (flow.loc[is_tons_day & ~bad_flow] * PERCFS_FACTOR_TONS_PER_DAY_TO_MG_L)
    )
    return out


def select_do_mean_columns(cols: Iterable[str]) -> list[str]:
    """Choose NWIS daily Mean columns for parameter 00300 (prefer canonical)."""
    candidates = [
        c
        for c in cols
        if "Mean" in c
        and c.startswith("00300")
        and not c.endswith("_cd")
        and not c.startswith("00060")
        and not c.startswith("00010")
    ]
    if not candidates:
        return []
    if "00300_Mean" in candidates:
        return ["00300_Mean"]

    stat_cols = [c for c in candidates if _STAT_MEAN_RE.match(c)]
    if len(stat_cols) == 1:
        return stat_cols

    descriptive_skip = (
        "discontinued",
        "upstream",
        "downstream",
        "multiparameter",
        "sonde",
        "supergage",
        "aoc",
        "exo",
        "ysi",
    )
    simple = [
        c
        for c in candidates
        if "," not in c and not any(tok in c.lower() for tok in descriptive_skip)
    ]
    if simple:
        return simple
    if stat_cols:
        return stat_cols
    return [candidates[0]]


def clean_do_mg_l(values: pd.Series) -> pd.Series:
    """Sentinel -> NaN; enforce plausible mg/L range for 00300."""
    out = pd.to_numeric(values, errors="coerce").astype(float)
    for sentinel in NWIS_DV_SENTINELS:
        out = out.replace(sentinel, np.nan)
    out = out.mask((out < DO_MG_L_MIN) | (out > DO_MG_L_MAX))
    return out
