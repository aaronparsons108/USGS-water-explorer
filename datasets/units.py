"""Unit normalization inside a parameter group.

Each group has a target unit: the one most of its member codes declare. Codes
already in that unit pass through, codes with a known conversion are converted,
and anything else is excluded from the group's daily mean. Nothing is silently
mixed, and every decision lands in the dataset's unit report.

One case sits between "convert" and "exclude": a code whose catalog entry
declares no unit at all. Excluding it would throw away data that is usually
fine, so it is kept and reported as ``assumed``, which the download page
highlights for review.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

import numpy as np
import pandas as pd

# lb/day to mg/L divides by flow_cfs * 5.3937; short tons/day by flow_cfs * 0.002697.
FACTOR_LBS = 5.3937
FACTOR_TONS = 0.002697

ACTION_KEEP = "keep"
ACTION_CONVERT = "convert"
ACTION_EXCLUDE = "exclude"


def norm_unit(u: str) -> str:
    """Case-folded, whitespace-collapsed unit string for comparison."""
    return " ".join(str(u or "").strip().lower().split())


def dominant(values: list[str]) -> str:
    """Most common value, breaking ties alphabetically.

    ``max(set(xs), key=xs.count)`` looks equivalent but is not: set iteration
    order depends on per-process string hashing, so a two-way tie resolves
    differently between server restarts. That would make one run convert a load
    to a concentration and the next run exclude the concentration instead, from
    identical inputs.
    """
    if not values:
        return ""
    counts = Counter(values)
    top = max(counts.values())
    return sorted(v for v, n in counts.items() if n == top)[0]


@dataclass(frozen=True)
class Conversion:
    factor: float  # value / (flow * factor)
    needs_flow: bool = True


# (from_unit, to_unit) -> Conversion. Every current entry is a flow-normalized
# nitrogen load; extend here as new needs come up.
CONVERSIONS: dict[tuple[str, str], Conversion] = {
    ("lb/d as n", "mg/l as n"): Conversion(FACTOR_LBS),
    ("lbs/day as n", "mg/l as n"): Conversion(FACTOR_LBS),
    ("ton/d as n", "mg/l as n"): Conversion(FACTOR_TONS),
    ("tons/day as n", "mg/l as n"): Conversion(FACTOR_TONS),
}


def plan_group_units(group_pmcodes: list[dict], flow_available: bool) -> tuple[str, dict, list]:
    """Decide per-code handling for one group.

    Returns ``(target_unit, actions, report)``, where ``actions`` maps a code to
    ``{"action": keep|convert|exclude, "conversion": Conversion|None}`` and
    ``report`` is a list of dicts for the dataset's unit report.
    """
    units = [norm_unit(p.get("unit")) for p in group_pmcodes]
    target = dominant([u for u in units if u])

    actions: dict[str, dict] = {}
    report: list[dict] = []

    def decide(code, action, conversion, reported, detail):
        actions[code] = {"action": action, "conversion": conversion}
        report.append({"code": code, "action": reported, "detail": detail})

    for p in group_pmcodes:
        code = str(p["code"])
        u = norm_unit(p.get("unit"))

        if not u:
            detail = (
                "no unit declared for this code; values used as-is"
                + (f", assumed to already be {target}" if target else "")
            )
            decide(code, ACTION_KEEP, None, "assumed", detail)
            continue

        if u == target:
            decide(code, ACTION_KEEP, None, "kept", f"already {target}")
            continue

        conv = CONVERSIONS.get((u, target))
        if conv is None:
            decide(
                code,
                ACTION_EXCLUDE,
                None,
                "excluded",
                f"no known conversion from {u} to {target}",
            )
        elif conv.needs_flow and not flow_available:
            decide(
                code,
                ACTION_EXCLUDE,
                None,
                "excluded",
                f"converting {u} to {target} needs streamflow (00060) in the dataset",
            )
        else:
            decide(
                code,
                ACTION_CONVERT,
                conv,
                "converted",
                f"{u} to {target}, divided by daily flow times {conv.factor:g}",
            )
    return target, actions, report


def apply_conversion(values: pd.Series, flow_cfs: pd.Series | None, conv: Conversion) -> pd.Series:
    """value / (flow * factor); missing or non-positive flow yields NaN."""
    out = pd.to_numeric(values, errors="coerce").astype(float)
    if not conv.needs_flow:
        return out / conv.factor
    if flow_cfs is None:
        return pd.Series(np.nan, index=out.index)
    flow = pd.to_numeric(flow_cfs, errors="coerce").astype(float)
    bad = (~np.isfinite(flow)) | (flow <= 0)
    res = out / (flow * conv.factor)
    res[bad] = np.nan
    return res
